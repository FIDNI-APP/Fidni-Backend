"""Badges (09/11/2026) : trois paliers (bronze, argent, or) par badge, calculés sur ce qui est déjà enregistré.

Un palier atteint est gardé (BadgeObtenu), même si le chiffre redescend ensuite (série cassée, quiz repassé…).
Les chiffres viennent de leurs propriétaires : la série et les défis trouvés de apps/defis, la maîtrise des chapitres
de « Ma progression » (apps/users/maitrise.py, même calcul, en cache), les quiz de apps/skilliq, les votes « utile »
de l'espace Discussions.

Quand :
- après une action qui fait bouger un chiffre (signals.py : défi trouvé, exercice réussi, quiz passé, vote « utile »
  reçu, contenu publié) : la famille concernée, avec une notification par palier gagné ;
- à l'affichage d'un profil : toutes les familles (la maîtrise et « Membre fondateur » ne changent que là).
Le premier calcul d'un compte enregistre sans notification ce qu'il avait déjà gagné (ProfilPublic.badges_init_le).
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import BadgeObtenu

PALIERS = {1: 'Bronze', 2: 'Argent', 3: 'Or'}
FONDATEUR_AVANT = datetime(2027, 1, 1, tzinfo=dt_timezone.utc)
QUIZ_REUSSI = 80  # % : un quiz du cours ou un approfondissement « réussi »

# pour : à qui le badge est proposé (les badges obtenus s'affichent toujours). « tous », « eleve » ou « prof ».
# unite / un : l'unité au pluriel et au singulier (« 1 publication », « 10 publications »).
BADGES = [
    {'id': 'serie', 'nom': 'Série du défi', 'unite': 'jours d’affilée', 'un': 'jour d’affilée', 'paliers': (3, 7, 30), 'pour': 'tous'},
    {'id': 'defis', 'nom': 'Défis trouvés', 'unite': 'défis', 'un': 'défi', 'paliers': (5, 25, 100), 'pour': 'tous'},
    {'id': 'exercices', 'nom': 'Exercices réussis', 'unite': 'exercices', 'un': 'exercice', 'paliers': (10, 50, 200),
     'pour': 'eleve'},
    {'id': 'maitrise', 'nom': 'Chapitres maîtrisés', 'unite': 'chapitres', 'un': 'chapitre', 'paliers': (1, 4, 8), 'pour': 'eleve'},
    {'id': 'quiz', 'nom': 'Quiz du cours', 'unite': 'quiz réussis', 'un': 'quiz réussi', 'paliers': (3, 8, 15), 'pour': 'eleve'},
    {'id': 'approfondi', 'nom': 'Chapitres approfondis', 'unite': 'chapitres', 'un': 'chapitre', 'paliers': (1, 3, 6),
     'pour': 'eleve'},
    {'id': 'entraide', 'nom': 'Entraide', 'unite': '« utile » reçus', 'un': '« utile » reçu', 'paliers': (1, 10, 30), 'pour': 'tous'},
    {'id': 'auteur', 'nom': 'Auteur', 'unite': 'publications', 'un': 'publication', 'paliers': (1, 10, 50), 'pour': 'prof'},
    {'id': 'fondateur', 'nom': 'Membre fondateur', 'unite': '', 'un': '', 'paliers': (1,), 'pour': 'tous'},
]
PAR_ID = {b['id']: b for b in BADGES}
FAMILLES = tuple(PAR_ID)


def texte_seuil(badge, n):
    """« 1 publication », « 10 publications » ; vide pour un badge sans unité (Membre fondateur)."""
    b = PAR_ID[badge]
    if not b['unite']:
        return ''
    return f'{n} {b["un"] if n == 1 else b["unite"]}'


def palier_de(badge, valeur):
    """Plus haut palier atteint (0 : aucun)."""
    return sum(1 for seuil in PAR_ID[badge]['paliers'] if valeur >= seuil)


def utiles_recus(user_ids, depuis=None):
    """Votes « utile » reçus par des membres sur leurs discussions et leurs réponses, sans les leurs → {user_id: n}."""
    from apps.discussions.models import Discussion, Reply
    from apps.interactions.models import Vote

    totaux = {}
    for model in (Discussion, Reply):
        ct = ContentType.objects.get_for_model(model)
        par_objet = dict(model.objects.filter(author_id__in=user_ids).values_list('id', 'author_id'))
        if not par_objet:
            continue
        votes = Vote.objects.filter(content_type=ct, value=Vote.UP, object_id__in=[str(i) for i in par_objet])
        if depuis is not None:
            votes = votes.filter(created_at__gte=depuis)
        for oid, votant in votes.values_list('object_id', 'user_id'):
            auteur = par_objet.get(int(oid)) if str(oid).isdigit() else None
            if auteur is not None and auteur != votant:
                totaux[auteur] = totaux.get(auteur, 0) + 1
    return totaux


def _quiz_reussis(user, type_quiz):
    from apps.skilliq.models import SkillAssessment
    chapitres = set()
    for chapter_id, score, max_score in SkillAssessment.objects.filter(user=user, type=type_quiz).values_list(
            'chapter_id', 'score', 'max_score'):
        if max_score and score * 100 >= QUIZ_REUSSI * max_score:
            chapitres.add(chapter_id)
    return len(chapitres)


def _exercices_reussis(user):
    from apps.interactions.models import Complete
    from apps.things.models import Content
    ct = ContentType.objects.get_for_model(Content)
    ids = [int(o) for o in Complete.objects.filter(user=user, content_type=ct, status='success')
           .values_list('object_id', flat=True) if str(o).isdigit()]
    return Content.objects.filter(id__in=ids, type='exercise').count() if ids else 0


def chapitres_maitrises(user, calculer=True):
    """Chapitres « maîtrisés » de Ma progression, au niveau de l'élève : [{id, name}] (même calcul, en cache).
    calculer=False : seulement s'ils sont déjà calculés (None sinon), sans remplir le cache (maitrise.en_cache)."""
    from apps.users import maitrise
    level = getattr(getattr(user, 'profile', None), 'class_level', None)
    data = maitrise.evaluer(user, level) if calculer else maitrise.en_cache(user, level)
    if data is None:
        return None
    return [{'id': c['id'], 'name': c['name']} for c in data['chapters'] if c.get('etat') == 'maitrise']


def valeurs(user, familles=None, cache_defi=None, calculer=True):
    """Chiffre de chaque famille demandée (toutes par défaut). `cache_defi` : jours trouvés déjà lus (profil).
    calculer=False (après une action) : la maîtrise n'est lue que si elle est déjà calculée, sinon elle est absente."""
    from apps.defis.views import jours_trouves, meilleure_serie
    from apps.skilliq.models import APPROFONDISSEMENT, COURS
    from apps.things.models import Content

    familles = FAMILLES if familles is None else familles
    out = {}
    trouves = cache_defi
    if {'serie', 'defis'} & set(familles):
        trouves = jours_trouves(user) if trouves is None else trouves
    for f in familles:
        if f == 'serie':
            out[f] = meilleure_serie(user, trouves)
        elif f == 'defis':
            from apps.defis.models import TentativeDefi
            out[f] = TentativeDefi.objects.filter(user=user, statut=TentativeDefi.TROUVE).count()
        elif f == 'exercices':
            out[f] = _exercices_reussis(user)
        elif f == 'maitrise':
            chapitres = chapitres_maitrises(user, calculer) if _eleve(user) else []
            if chapitres is not None:
                out[f] = len(chapitres)
        elif f == 'quiz':
            out[f] = _quiz_reussis(user, COURS)
        elif f == 'approfondi':
            out[f] = _quiz_reussis(user, APPROFONDISSEMENT)
        elif f == 'entraide':
            out[f] = utiles_recus([user.id]).get(user.id, 0)
        elif f == 'auteur':
            out[f] = Content.objects.filter(author=user).count()
        elif f == 'fondateur':
            out[f] = int(bool(user.date_joined and user.date_joined < FONDATEUR_AVANT))
    return out


def _eleve(user):
    profile = getattr(user, 'profile', None)
    return not (profile is not None and profile.user_type == 'teacher')


def obtenus(user_ids):
    """Plus haut palier obtenu par famille, pour plusieurs membres → {user_id: {badge: (palier, obtenu_le)}}."""
    out = {}
    for uid, badge, palier, quand in BadgeObtenu.objects.filter(user_id__in=user_ids).values_list(
            'user_id', 'badge', 'palier', 'obtenu_le'):
        if badge not in PAR_ID:
            continue
        mine = out.setdefault(uid, {})
        if badge not in mine or palier > mine[badge][0]:
            mine[badge] = (palier, quand)
    return out


def actualiser(user, familles=None, valeurs_connues=None, notifier=True, calculer=True):
    """Enregistre les paliers nouvellement atteints → [(badge, palier)] gagnés. Le premier calcul d'un compte
    (toutes familles) n'envoie aucune notification : ce sont des badges déjà mérités avant leur arrivée.
    calculer=False (après une action, signals.py) : la maîtrise n'est comptée que si elle est déjà calculée."""
    from . import services

    reglages = services.profil_public(user, creer=True)
    premier = reglages.badges_init_le is None
    if premier:
        familles = FAMILLES  # le premier calcul couvre tout, pour ne jamais notifier d'anciens badges plus tard
    chiffres = dict(valeurs_connues or {})
    manquants = [f for f in (familles or FAMILLES) if f not in chiffres]
    if manquants:
        chiffres.update(valeurs(user, manquants, calculer=calculer))
    deja = {(b, p) for b, p in BadgeObtenu.objects.filter(user=user).values_list('badge', 'palier')}
    gagnes = []
    for f in (familles or FAMILLES):
        for p in range(1, palier_de(f, chiffres.get(f, 0)) + 1):
            if (f, p) in deja:
                continue
            try:
                with transaction.atomic():
                    BadgeObtenu.objects.create(user=user, badge=f, palier=p)
            except IntegrityError:
                continue  # gagné au même moment par une autre requête
            gagnes.append((f, p))
    if premier:
        type(reglages).objects.filter(pk=reglages.pk).update(badges_init_le=timezone.now())
    elif gagnes and notifier:
        services.notifier_badges(user, gagnes)
    return gagnes


def catalogue(user, est_proprietaire, chiffres=None):
    """Badges d'un profil. Visiteur : les badges obtenus seulement. Propriétaire : aussi ceux qui lui sont proposés,
    avec son chiffre et le palier suivant."""
    mine = obtenus([user.id]).get(user.id, {})
    role = 'prof' if not _eleve(user) else 'eleve'
    out = []
    for b in BADGES:
        palier, quand = mine.get(b['id'], (0, None))
        propose = b['pour'] in ('tous', role)
        if not palier and not (est_proprietaire and propose):
            continue
        item = {'id': b['id'], 'nom': b['nom'], 'unite': b['unite'], 'un': b['un'], 'paliers': list(b['paliers']),
                'palier': palier, 'obtenu_le': quand}
        if est_proprietaire and chiffres is not None:
            item['valeur'] = chiffres.get(b['id'], 0)
        out.append(item)
    # Obtenus d'abord (du plus haut palier au plus bas), puis ceux à gagner.
    out.sort(key=lambda x: (-x['palier'], FAMILLES.index(x['id'])))
    return out


def recents_obtenus(user_ids, avant=None, limite=50):
    """Derniers paliers gagnés par ces membres (fil des abonnements), sans « Membre fondateur » (rien d'un exploit)."""
    rows = BadgeObtenu.objects.filter(user_id__in=user_ids).exclude(badge='fondateur')
    if avant is not None:
        rows = rows.filter(obtenu_le__lt=avant)
    return rows.select_related('user__profile', 'user__profile__class_level').order_by('-obtenu_le')[:limite]


def classement_series(limite=5):
    """Meilleures séries EN COURS (défi trouvé aujourd'hui ou hier, sinon la série est déjà cassée)."""
    from apps.defis.models import TentativeDefi
    from apps.defis.views import aujourdhui, serie

    jour = aujourdhui()
    actifs = (TentativeDefi.objects.filter(statut=TentativeDefi.TROUVE, le_jour_meme=True,
                                           defi__date__gte=jour - timedelta(days=1))
              .values_list('user_id', flat=True).distinct())
    users = User.objects.filter(id__in=list(actifs)[:200], is_active=True).select_related('profile')
    rangs = sorted(((serie(u), u) for u in users), key=lambda x: (-x[0], x[1].username.lower()))
    return [(n, u) for n, u in rangs if n >= 2][:limite]


def classement_utiles(depuis, limite=5, exclure=()):
    """Membres qui ont reçu le plus de « utile » depuis `depuis` → [(n, user)]."""
    from apps.discussions.models import Discussion, Reply
    auteurs = set(Discussion.objects.values_list('author_id', flat=True).distinct()) | set(
        Reply.objects.values_list('author_id', flat=True).distinct())
    totaux = utiles_recus(list(auteurs - set(exclure)), depuis=depuis)
    users = {u.id: u for u in User.objects.filter(id__in=totaux, is_active=True).select_related('profile')}
    rangs = sorted(((n, users[uid]) for uid, n in totaux.items() if uid in users), key=lambda x: (-x[0], x[1].username.lower()))
    return rangs[:limite]
