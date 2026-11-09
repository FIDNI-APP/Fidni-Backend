"""Ce que l'API de la communauté renvoie : cartes de membres (par lots) et profil public complet."""
import logging
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q, Sum

from apps.users.serializers import AuthorSerializer

from . import badges as B
from .models import Abonnement, ProfilPublic
from .services import banniere_par_defaut, est_mineur, profil_public, relation, role, voit_listes

logger = logging.getLogger('django')
CALENDRIER_JOURS = 84  # 12 semaines de défis sur le profil
ACTIVITE = 6


def _reglages_par_user(users):
    rows = {p.user_id: p for p in ProfilPublic.objects.filter(user__in=users)}
    return {u.id: rows.get(u.id) or profil_public(u) for u in users}


def cartes(users, viewer, request):
    """Cartes de membres : pseudo, photo, rôle, niveau, objectif, bannière, 3 badges, abonnés, relation au visiteur.
    Une poignée de requêtes quel que soit le nombre de membres."""
    users = list(users)
    if not users:
        return []
    ids = [u.id for u in users]
    reglages = _reglages_par_user(users)
    obtenus = B.obtenus(ids)
    abonnes = dict(Abonnement.objects.filter(suivi_id__in=ids, statut=Abonnement.ACCEPTE).values('suivi_id')
                   .annotate(n=Count('id')).values_list('suivi_id', 'n'))
    liens, me_suivent = {}, set()
    if viewer and viewer.is_authenticated:
        liens = dict(Abonnement.objects.filter(abonne=viewer, suivi_id__in=ids).values_list('suivi_id', 'statut'))
        me_suivent = set(Abonnement.objects.filter(suivi=viewer, abonne_id__in=ids, statut=Abonnement.ACCEPTE)
                         .values_list('abonne_id', flat=True))
    out = []
    for u in users:
        r = reglages[u.id]
        mine = obtenus.get(u.id, {})
        out.append({
            **_identite(u, r, request),
            'badges': _top_badges(mine, r.vitrine),
            'abonnes': abonnes.get(u.id, 0),
            'relation': {'abonne': liens.get(u.id), 'me_suit': u.id in me_suivent,
                         'moi': bool(viewer and viewer.is_authenticated and viewer.id == u.id)},
        })
    return out


def _identite(u, reglages, request):
    profile = getattr(u, 'profile', None)
    rl = role(u)
    data = AuthorSerializer(u, context={'request': request}).data
    return {
        'id': u.id, 'username': u.username, 'avatar': data.get('avatar'), 'role': rl,
        'level': profile.class_level.name if rl == 'eleve' and profile and profile.class_level_id else None,
        'objectif': reglages.objectif or None, 'banniere': reglages.banniere or banniere_par_defaut(u),
        'verifie': bool(reglages.verifie and rl == 'prof'),
    }


def _badge_item(badge, palier, quand=None):
    b = B.PAR_ID[badge]
    return {'id': badge, 'nom': b['nom'], 'palier': palier, 'seuil': b['paliers'][palier - 1], 'unite': b['unite'], 'un': b['un'],
            'obtenu_le': quand}


def _top_badges(mine, vitrine, n=3):
    """Vitrine choisie (badges encore obtenus), complétée par les plus hauts paliers."""
    choisis = [b for b in (vitrine or []) if b in mine][:n]
    reste = sorted((b for b in mine if b not in choisis), key=lambda b: (-mine[b][0], B.FAMILLES.index(b)))
    return [_badge_item(b, *mine[b]) for b in (choisis + reste)[:n]]


def _chiffres(user, rl, valeurs, serie_en_cours):
    from apps.things.models import Content
    if rl == 'eleve':
        # Un chiffre inconnu (maîtrise en échec) n'est pas affiché : ce n'est pas un zéro.
        return [{'id': 'serie', 'valeur': serie_en_cours, 'record': valeurs.get('serie', 0)}] + [
            {'id': f, 'valeur': valeurs[f]} for f in ('exercices', 'maitrise', 'approfondi', 'entraide') if f in valeurs]
    contenus = Content.objects.filter(author=user)
    ct = ContentType.objects.get_for_model(Content)
    from apps.interactions.models import Vote
    ids = [str(i) for i in contenus.values_list('id', flat=True)]
    votes = Vote.objects.filter(content_type=ct, object_id__in=ids, value=Vote.UP).count() if ids else 0
    profile = getattr(user, 'profile', None)
    eleves = profile.students.count() if profile is not None and hasattr(profile, 'students') else 0
    return [
        {'id': 'publications', 'valeur': len(ids)},
        {'id': 'vues', 'valeur': contenus.aggregate(s=Sum('view_count'))['s'] or 0},
        {'id': 'votes', 'valeur': votes},
        {'id': 'eleves', 'valeur': eleves},
        {'id': 'entraide', 'valeur': valeurs.get('entraide', 0)},
    ]


def _activite(user):
    """Dernières discussions lancées, commentaires et réponses écrits (tous publics), avec leurs « utile »."""
    from apps.discussions.models import COMMENTAIRE, Discussion, Reply
    from apps.discussions.presenters import utile_counts
    from apps.discussions.services import link, reply_link, titre
    disc = list(Discussion.objects.filter(author=user).prefetch_related('contents').order_by('-created_at')[:ACTIVITE])
    reps = list(Reply.objects.filter(author=user).select_related('discussion').prefetch_related('discussion__contents')
                .order_by('-created_at')[:ACTIVITE])
    u_disc, _ = utile_counts(Discussion, [d.id for d in disc], None)
    u_rep, _ = utile_counts(Reply, [r.id for r in reps], None)
    items = [{'type': 'commentaire' if d.genre == COMMENTAIRE else 'discussion', 'id': d.id, 'titre': titre(d),
              'url': link(d), 'date': d.created_at, 'utiles': u_disc.get(d.id, 0), 'reponses': d.reply_count} for d in disc]
    items += [{'type': 'reponse', 'id': r.id, 'titre': titre(r.discussion), 'url': reply_link(r), 'date': r.created_at,
               'utiles': u_rep.get(r.id, 0)} for r in reps]
    return sorted(items, key=lambda x: x['date'], reverse=True)[:ACTIVITE]


def profil(user, viewer, request):
    """Profil public complet. Le propriétaire reçoit aussi ses réglages, les blocs qu'il masque et la progression de ses
    badges ; les autres ne voient ni les blocs masqués, ni la ville d'un mineur, ni les badges pas encore obtenus."""
    from apps.defis.views import aujourdhui, jours_trouves, serie
    reglages = profil_public(user)
    proprietaire = bool(viewer and viewer.is_authenticated and viewer.id == user.id)
    rl = role(user)
    masques = set(reglages.blocs_masques or []) if not proprietaire else set()
    mineur = est_mineur(user)

    trouves = jours_trouves(user)
    chiffres_badges = B.valeurs(user, cache_defi=trouves)
    try:
        B.actualiser(user, valeurs_connues=chiffres_badges)
    except Exception:  # des paliers pas enregistrés cette fois-ci ne doivent pas empêcher de voir le profil
        logger.exception('Communauté : badges non actualisés pour le membre %s', user.id)
    catalogue =B.catalogue(user, proprietaire, chiffres_badges if proprietaire else None)
    par_id = {b['id']: b for b in catalogue if b['palier']}  # vitrine : badges obtenus seulement, dans l'ordre choisi

    profile = getattr(user, 'profile', None)
    abonnes = Abonnement.objects.filter(suivi=user, statut=Abonnement.ACCEPTE)
    data = {
        **_identite(user, reglages, request),
        'bio': getattr(profile, 'bio', '') or '',
        'ville': (getattr(profile, 'location', '') or None) if (proprietaire or not mineur) else None,
        'depuis': getattr(profile, 'joined_at', None) or user.date_joined,
        'abonnes': abonnes.count(),
        'abonnements': Abonnement.objects.filter(abonne=user, statut=Abonnement.ACCEPTE).count(),
        'apercu_abonnes': [],
        'listes_visibles': voit_listes(viewer, user, reglages),
        'relation': relation(viewer, user),
        'vitrine': [par_id[b] for b in (reglages.vitrine or []) if b in par_id][:3],
        'badges': catalogue if 'badges' not in masques else None,
        'enseigne': None,
    }
    if data['listes_visibles']:
        apercu = [a.abonne for a in abonnes.select_related('abonne__profile').order_by('-created_at')[:8]]
        data['apercu_abonnes'] = [{'username': u.username, 'avatar': AuthorSerializer(u, context={'request': request})
                                   .data.get('avatar')} for u in apercu]
    if rl != 'eleve' and profile is not None:
        data['enseigne'] = {'matieres': [s.name for s in profile.teaching_subjects.all()],
                            'niveaux': [c.name for c in profile.teaching_class_levels.order_by('order')]}

    data['chiffres'] = _chiffres(user, rl, chiffres_badges, serie(user, trouves)) if 'chiffres' not in masques else None
    data['chapitres'] = (B.chapitres_maitrises(user) if rl == 'eleve' else []) if 'chapitres' not in masques else None
    if 'defi' not in masques:
        debut = aujourdhui() - timedelta(days=CALENDRIER_JOURS - 1)
        data['defi'] = {'serie': serie(user, trouves), 'record': chiffres_badges.get('serie', 0),
                        'trouves': chiffres_badges.get('defis', 0), 'debut': debut.isoformat(),
                        'jours': sorted(d.isoformat() for d in trouves if d >= debut)}
    else:
        data['defi'] = None
    data['activite'] = _activite(user) if 'activite' not in masques else None
    if proprietaire:
        data['reglages'] = {
            'banniere': reglages.banniere, 'objectif': reglages.objectif, 'vitrine': reglages.vitrine or [],
            'blocs_masques': reglages.blocs_masques or [], 'abonnes_a_valider': reglages.abonnes_a_valider,
            'visible_recherche': reglages.visible_recherche, 'mineur': mineur,
            'demandes': Abonnement.objects.filter(suivi=user, statut=Abonnement.EN_ATTENTE).count(),
        }
    return data


def filtre_recherche(qs, viewer):
    """Membres qu'on peut trouver : actifs, pas le compte fantôme, pas cachés de la recherche, pas bloqués."""
    from apps.users.account_deletion import DELETED_USERNAME
    from .models import Blocage
    qs = qs.filter(is_active=True).exclude(username=DELETED_USERNAME).exclude(profil_public__visible_recherche=False)
    if viewer and viewer.is_authenticated:
        bloques = Blocage.objects.filter(Q(auteur=viewer) | Q(bloque=viewer)).values_list('auteur_id', 'bloque_id')
        exclus = {i for pair in bloques for i in pair} - {viewer.id}
        if exclus:
            qs = qs.exclude(id__in=exclus)
    return qs
