"""API de la communauté (09/11/2026).

GET    /api/communaute/profils/<pseudo>/              profil public (ouvert aux visiteurs)
POST   /api/communaute/profils/<pseudo>/suivre/       s'abonner (ou le demander) ; DELETE : se désabonner / annuler
POST   /api/communaute/profils/<pseudo>/bloquer/      bloquer ; DELETE : débloquer
GET    /api/communaute/profils/<pseudo>/abonnes/      ses abonnés (cartes) ; …/abonnements/ : qui il suit
GET    /api/communaute/demandes/                      demandes d'abonnement reçues
POST   /api/communaute/demandes/<pseudo>/accepter/    (ou refuser/)
DELETE /api/communaute/abonnes/<pseudo>/              retirer un abonné
GET    /api/communaute/membres/?q=&role=&niveau=&matiere=&page=   recherche de membres
GET    /api/communaute/decouvrir/                     ta classe, professeurs, élèves de ton niveau, classements
GET    /api/communaute/fil/?avant=<date ISO>          activité des membres suivis
GET    /api/communaute/moi/ ; PATCH                   réglages du profil public
"""
import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Case, Count, F, IntegerField, Q, Value, When
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from config.throttling import CommunauteThrottle

from . import badges as B
from . import services as S
from .models import BANNIERES, BLOCS, OBJECTIF_MAX, VITRINE_MAX, Abonnement
from .presenters import cartes, filtre_recherche, profil

PAGE = 24
FIL_PAGE = 20
LIEN_OU_NUMERO = re.compile(r'(https?://|www\.|\.(com|ma|fr|net|org)\b|@|\d[\d .-]{6,}\d)', re.I)


def _membre(username):
    from apps.users.account_deletion import DELETED_USERNAME
    return (User.objects.filter(username=username, is_active=True).exclude(username=DELETED_USERNAME)
            .select_related('profile', 'profile__class_level').first())


def _introuvable():
    return Response({'detail': 'Ce membre n’existe pas.'}, status=404)


def _refus(e):
    return Response({'detail': e.message, 'code': e.code}, status=e.status)


def _users(qs):
    return qs.select_related('profile', 'profile__class_level', 'profil_public')


def _actifs_dabord():
    """Les plus récemment actifs d'abord, ceux sans activité connue à la fin. Sans nulls_last, PostgreSQL les mettrait en
    tête d'un tri décroissant (SQLite, des vérifications, à la fin : la différence ne se voit qu'en production)."""
    return F('profile__last_activity_date').desc(nulls_last=True)


@api_view(['GET'])
@permission_classes([AllowAny])
def profil_view(request, username):
    user = _membre(username)
    if not user:
        return _introuvable()
    return Response(profil(user, request.user, request))


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
@throttle_classes([CommunauteThrottle])
def suivre(request, username):
    user = _membre(username)
    if not user:
        return _introuvable()
    if request.method == 'DELETE':
        S.ne_plus_suivre(request.user, user)
        return Response({'abonne': None})
    try:
        return Response({'abonne': S.suivre(request.user, user)})
    except S.Refus as e:
        return _refus(e)


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
@throttle_classes([CommunauteThrottle])
def bloquer(request, username):
    user = _membre(username)
    if not user:
        return _introuvable()
    if request.method == 'DELETE':
        S.debloquer(request.user, user)
        return Response({'bloque': False})
    try:
        S.bloquer(request.user, user)
    except S.Refus as e:
        return _refus(e)
    return Response({'bloque': True})


def _page(request):
    try:
        return max(1, int(request.query_params.get('page', 1)))
    except (TypeError, ValueError):
        return 1


def _liste(request, qs):
    page = _page(request)
    users = list(qs[(page - 1) * PAGE:page * PAGE + 1])
    return Response({'results': cartes(users[:PAGE], request.user, request), 'page': page, 'suite': len(users) > PAGE})


@api_view(['GET'])
@permission_classes([AllowAny])
def abonnes(request, username):
    return _liste_relation(request, username, 'abonnes')


@api_view(['GET'])
@permission_classes([AllowAny])
def abonnements(request, username):
    return _liste_relation(request, username, 'abonnements')


def _liste_relation(request, username, sens):
    user = _membre(username)
    if not user:
        return _introuvable()
    if not S.voit_listes(request.user, user, S.profil_public(user)):
        return Response({'detail': 'Ce membre valide ses abonnés : sa liste est privée.', 'code': 'prive'}, status=403)
    if sens == 'abonnes':
        qs = User.objects.filter(abonnements__suivi=user, abonnements__statut=Abonnement.ACCEPTE)
        qs = qs.order_by('-abonnements__created_at')
    else:
        qs = User.objects.filter(abonnes__abonne=user, abonnes__statut=Abonnement.ACCEPTE).order_by('-abonnes__created_at')
    return _liste(request, _users(qs.filter(is_active=True)))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def demandes(request):
    qs = User.objects.filter(abonnements__suivi=request.user, abonnements__statut=Abonnement.EN_ATTENTE)
    return _liste(request, _users(qs.order_by('-abonnements__created_at')))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([CommunauteThrottle])
def repondre_demande(request, username, reponse):
    demandeur = _membre(username)
    if not demandeur or reponse not in ('accepter', 'refuser'):
        return _introuvable()
    ok = S.accepter(request.user, demandeur) if reponse == 'accepter' else S.refuser(request.user, demandeur)
    if not ok:
        return Response({'detail': 'Aucune demande de ce membre.'}, status=404)
    return Response({'ok': True})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
@throttle_classes([CommunauteThrottle])
def retirer_abonne(request, username):
    abonne = _membre(username)
    if not abonne:
        return _introuvable()
    S.retirer(request.user, abonne)
    return Response({'ok': True})


def _role_q(role):
    prof = Q(profile__user_type='teacher')
    equipe = Q(is_staff=True) | Q(is_superuser=True)
    if role == 'prof':
        return prof & ~equipe
    if role == 'eleve':
        return ~prof & ~equipe
    return Q()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def membres(request):
    q = (request.query_params.get('q') or '').strip()[:60]
    role = request.query_params.get('role')
    qs = filtre_recherche(User.objects.all(), request.user).filter(_role_q(role))
    niveau, matiere = request.query_params.get('niveau'), request.query_params.get('matiere')
    if niveau and niveau.isdigit():
        qs = qs.filter(Q(profile__class_level_id=int(niveau)) | Q(profile__teaching_class_levels__id=int(niveau)))
    if matiere and matiere.isdigit():
        qs = qs.filter(profile__teaching_subjects__id=int(matiere))
    if q:
        qs = qs.filter(username__icontains=q).annotate(debut=Case(
            When(username__istartswith=q, then=Value(0)), default=Value(1), output_field=IntegerField()))
        qs = qs.order_by('debut', 'username')
    else:
        qs = qs.order_by(_actifs_dabord(), '-date_joined')
    return _liste(request, _users(qs.distinct()))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def decouvrir(request):
    from apps.classrooms.models import Classroom, ClassroomMembership
    viewer = request.user
    base = filtre_recherche(User.objects.all(), viewer).exclude(id=viewer.id)

    classes = list(ClassroomMembership.objects.filter(student=viewer).values_list('classroom_id', flat=True))
    classes += list(Classroom.objects.filter(owner=viewer).values_list('id', flat=True))
    classe = []
    if classes:
        ids = set(ClassroomMembership.objects.filter(classroom_id__in=classes).values_list('student_id', flat=True))
        ids |= set(Classroom.objects.filter(id__in=classes).values_list('owner_id', flat=True))
        classe = list(_users(base.filter(id__in=ids)).order_by(_actifs_dabord())[:12])

    # Vérifiés d'abord : un professeur sans réglages enregistrés n'a pas de ligne (NULL), donc nulls_last ici aussi.
    profs = list(_users(base.filter(_role_q('prof'))).annotate(n=Count('content_items', distinct=True))
                 .order_by(F('profil_public__verifie').desc(nulls_last=True), '-n', _actifs_dabord())[:8])

    niveau = []
    level_id = getattr(getattr(viewer, 'profile', None), 'class_level_id', None)
    if level_id:
        niveau = list(_users(base.filter(_role_q('eleve'), profile__class_level_id=level_id))
                      .exclude(id__in=[u.id for u in classe]).order_by(_actifs_dabord())[:8])

    utiles = B.classement_utiles(timezone.now() - timedelta(days=30))
    series = B.classement_series()
    tous = {u.id: u for u in classe + profs + niveau + [u for _, u in utiles] + [u for _, u in series]}
    par_id = {c['id']: c for c in cartes(list(tous.values()), viewer, request)}
    return Response({
        'classe': [par_id[u.id] for u in classe],
        'profs': [par_id[u.id] for u in profs],
        'niveau': [par_id[u.id] for u in niveau],
        'utiles': [{'membre': par_id[u.id], 'n': n} for n, u in utiles if u.id in par_id],
        'series': [{'membre': par_id[u.id], 'n': n} for n, u in series if u.id in par_id],
    })


def _mini(u, request):
    from apps.discussions.presenters import author
    return author(u, request)


def _avant(request):
    """Curseur du fil (?avant=<date ISO>) : maintenant s'il est absent ou illisible (parse_datetime lève ValueError sur
    une date bien formée mais impossible, comme le 45 du mois)."""
    try:
        quand = parse_datetime(request.query_params.get('avant') or '')
    except ValueError:
        quand = None
    if quand is None:
        return timezone.now()
    return timezone.make_aware(quand) if timezone.is_naive(quand) else quand


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def fil(request):
    """Activité des membres suivis (abonnements acceptés) : discussions lancées, commentaires, badges gagnés, contenus publiés."""
    from apps.discussions.models import COMMENTAIRE, Discussion
    from apps.things.models import Content
    from apps.discussions.presenters import TYPE_PATH
    from apps.discussions.services import link, titre
    avant = _avant(request)
    suivis = list(Abonnement.objects.filter(abonne=request.user, statut=Abonnement.ACCEPTE).values_list('suivi_id', flat=True))
    if not suivis:
        return Response({'results': [], 'suite': None, 'suivis': 0})
    items = []
    for d in Discussion.objects.filter(author_id__in=suivis, created_at__lt=avant).select_related(
            'author__profile', 'author__profile__class_level').prefetch_related('contents').order_by('-created_at')[:FIL_PAGE]:
        items.append({'type': 'commentaire' if d.genre == COMMENTAIRE else 'discussion', 'date': d.created_at, 'membre': d.author,
                      'objet': {'id': d.id, 'titre': titre(d), 'url': link(d), 'salon': d.salon, 'reponses': d.reply_count}})
    for b in B.recents_obtenus(suivis, avant=avant, limite=FIL_PAGE):
        info = B.PAR_ID.get(b.badge)
        if info:
            items.append({'type': 'badge', 'date': b.obtenu_le, 'membre': b.user,
                          'objet': {'id': b.badge, 'nom': info['nom'], 'palier': b.palier,
                                    'seuil': info['paliers'][b.palier - 1], 'unite': info['unite'], 'un': info['un']}})
    for c in Content.objects.filter(author_id__in=suivis, created_at__lt=avant).select_related(
            'author__profile', 'author__profile__class_level').order_by('-created_at')[:FIL_PAGE]:
        items.append({'type': 'publication', 'date': c.created_at, 'membre': c.author,
                      'objet': {'id': c.id, 'titre': c.title, 'type': c.type,
                                'url': f'/{TYPE_PATH.get(c.type, "exercises")}/{c.id}'}})
    items.sort(key=lambda x: x['date'], reverse=True)
    page = items[:FIL_PAGE]
    for it in page:
        it['membre'] = _mini(it['membre'], request)
    suite = page[-1]['date'].isoformat() if len(items) > FIL_PAGE else None
    return Response({'results': page, 'suite': suite, 'suivis': len(suivis)})


def _reglages(user):
    r = S.profil_public(user)
    return {'banniere': r.banniere, 'objectif': r.objectif, 'vitrine': r.vitrine or [],
            'blocs_masques': r.blocs_masques or [], 'abonnes_a_valider': r.abonnes_a_valider,
            'visible_recherche': r.visible_recherche, 'mineur': S.est_mineur(user),
            'demandes': Abonnement.objects.filter(suivi=user, statut=Abonnement.EN_ATTENTE).count()}


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def moi(request):
    user = request.user
    if request.method == 'GET':
        return Response(_reglages(user))
    d = request.data if isinstance(request.data, dict) else {}
    erreurs = {}
    champs = {}
    if 'banniere' in d:
        if d['banniere'] not in ('', *BANNIERES):
            erreurs['banniere'] = 'Bannière inconnue.'
        else:
            champs['banniere'] = d['banniere']
    if 'objectif' in d:
        texte = ' '.join(str(d['objectif'] or '').split())
        if len(texte) > OBJECTIF_MAX:
            erreurs['objectif'] = f'{OBJECTIF_MAX} caractères au plus.'
        elif LIEN_OU_NUMERO.search(texte):
            erreurs['objectif'] = 'Pas de lien, d’adresse ni de numéro.'
        else:
            champs['objectif'] = texte
    if 'vitrine' in d:
        v = d['vitrine']
        mine = B.obtenus([user.id]).get(user.id, {})
        if not isinstance(v, list) or len(v) > VITRINE_MAX or len(set(map(str, v))) != len(v):
            erreurs['vitrine'] = f'{VITRINE_MAX} badges au plus.'
        elif any(b not in mine for b in v):
            erreurs['vitrine'] = 'Seulement des badges obtenus.'
        else:
            champs['vitrine'] = v
    if 'blocs_masques' in d:
        v = d['blocs_masques']
        if not isinstance(v, list) or any(b not in BLOCS for b in v):
            erreurs['blocs_masques'] = 'Bloc inconnu.'
        else:
            champs['blocs_masques'] = sorted(set(v))
    for cle in ('abonnes_a_valider', 'visible_recherche'):
        if cle in d:
            if not isinstance(d[cle], bool):
                erreurs[cle] = 'Vrai ou faux.'
            else:
                champs[cle] = d[cle]
    if erreurs:
        return Response(erreurs, status=400)
    r = S.profil_public(user, creer=True)
    ouvrait = r.abonnes_a_valider and champs.get('abonnes_a_valider') is False
    for k, v in champs.items():
        setattr(r, k, v)
    r.save()
    if ouvrait:
        S.accepter_tout(user)
    return Response(_reglages(user))
