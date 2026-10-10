"""Mesure d'usage : pages vues et quelques actions sans autre trace en base (Pilotage › Usage).

POST /api/usage/  {kind: "page", name: "/exercises/:id"}  ou  {kind: "action", name: "imprimer"}
                  ou  {kind: "filtre", name: "exercise:difficulte:hard"}  (valeur d'un filtre des listes)

Le navigateur n'envoie que le motif de la route (jamais l'adresse exacte ni le contenu) ; les robots et les
comptes maison ne sont pas comptés. Une même personne n'est comptée qu'une fois par jour dans `visitors`.
Les visiteurs non connectés sont aussi comptés à part (anon_count, anon_visitors), et chaque page vue alimente
la ligne du jour « site / visites » (personnes distinctes sur tout le site).
"""
import hashlib
import re

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from apps.users.models import UsageDaily

PAGE_RE = re.compile(r'^/[a-z0-9/:_-]{0,78}$')
# Actions mesurées côté navigateur : le reste (auto-évaluations, j'aime, commentaires…) se compte en base.
ACTIONS = {
    'voir-solution',      # « Voir la solution » d'une question
    'toutes-solutions',   # « Voir les solutions » de tout l'exercice
    'tout-reussi',        # « Tout réussi »
    'trouve-apres-solution',  # « Tu avais trouvé ? » sous une solution ouverte : réponse donnée
    'rattrapage-liste',   # « Réussi » / « À revoir » depuis le bandeau de rattrapage de la liste
    'imprimer',           # impression / PDF d'un contenu, d'une liste, d'un cahier
    'visite-guidee',      # visite guidée lancée (bouton ?)
    'recherche',          # recherche lancée
    'onglet-activite',    # onglet « Activité » d'un contenu ouvert
    'onglet-solutions',   # onglet « Solutions des élèves » ouvert
    # Audit du 10/10/2026 : gestes jusqu'ici invisibles.
    'partager',           # « Partager » d'un contenu
    'chrono-demarre',     # chrono d'un exercice lancé (seule la sauvegarde laissait une trace)
    'epreuve-demarree', 'epreuve-terminee',  # épreuve chronométrée d'un examen
    'similaire',          # clic dans « Pour continuer »
    'suivant-apres-resultat',  # « Exercice suivant » proposé après Réussi / À revoir
    'ressenti',           # « C'était : plus facile / comme annoncé / plus dur »
    'cloche',             # cloche des notifications ouverte
    'retour-liste',       # bouton retour d'un contenu vers la liste
    'sommaire-lecon',     # sommaire d'une leçon utilisé
    'affichage-enonces',  # liste passée en mode « Énoncés »
    'charger-plus',       # « Charger plus » dans une liste
    'recherche-vide',     # recherche sans résultat
    'accueil-reprendre', 'accueil-pour-toi', 'annoncer-ds',  # accueil connecté
    'prog-entrainer', 'prog-cours', 'prog-quiz',  # Ma progression › chapitre
    'quiz-refait',        # quiz de chapitre repassé
    'mode-revision',      # liste de révision ouverte en mode révision
    'barre-mobile',       # barre d'onglets en bas sur téléphone
    'visite-auto', 'visite-passee', 'visite-finie',  # visites guidées
    'signaler-ouvert',    # fenêtre « Signaler une erreur » ouverte (envoyée ou non)
    'auth-ouverte',       # fenêtre de connexion / inscription ouverte
    'connexion-google',   # bouton « Continuer avec Google » utilisé
    # Filtres des listes (exercices, examens, leçons) : un filtre ajouté, le tri, « Tout effacer ».
    'filtre-niveau', 'filtre-matiere', 'filtre-sous-domaine', 'filtre-chapitre', 'filtre-theoreme',
    'filtre-difficulte', 'filtre-statut', 'filtre-national', 'filtre-date', 'filtre-effacer', 'tri',
}


# Valeur d'un filtre : « <liste>:<filtre>:<valeur> » (identifiant, difficulté, tri…), traduite au Pilotage.
FILTER_RE = re.compile(
    r'^(exercise|exam|lesson):(niveau|matiere|sous-domaine|chapitre|theoreme|difficulte|statut|national|date|tri)'
    r':[A-Za-z0-9_-]{1,40}$'
    # Porte d'entrée de la fenêtre d'inscription (10/10/2026) : « auth:porte:vote », « auth:porte:bandeau »…
    r'|^auth:porte:[a-z0-9-]{1,30}$')


class UsageAnonThrottle(AnonRateThrottle):
    rate = '240/hour'


class UsageUserThrottle(UserRateThrottle):
    rate = '600/hour'


def _bump(day, kind, name, new_visitor, anon):
    inc = {'count': F('count') + 1}
    if new_visitor:
        inc['visitors'] = F('visitors') + 1
    if anon:
        inc['anon_count'] = F('anon_count') + 1
        if new_visitor:
            inc['anon_visitors'] = F('anon_visitors') + 1
    if UsageDaily.objects.filter(date=day, kind=kind, name=name).update(**inc):
        return
    try:
        with transaction.atomic():
            UsageDaily.objects.create(date=day, kind=kind, name=name, count=1, visitors=1 if new_visitor else 0,
                                      anon_count=1 if anon else 0, anon_visitors=1 if anon and new_visitor else 0)
    except IntegrityError:
        UsageDaily.objects.filter(date=day, kind=kind, name=name).update(**inc)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([UsageAnonThrottle, UsageUserThrottle])
def record(request):
    from apps.things.views import BOT_UA
    from apps.users.admin_dashboard import _house_filter

    kind = request.data.get('kind')
    name = str(request.data.get('name') or '')
    # fullmatch : « $ » seul laisserait passer un saut de ligne final, stocké tel quel dans le nom.
    if kind == UsageDaily.KIND_PAGE:
        if not PAGE_RE.fullmatch(name):
            return Response({'counted': False}, status=400)
    elif kind == UsageDaily.KIND_ACTION:
        if name not in ACTIONS:
            return Response({'counted': False}, status=400)
    elif kind == UsageDaily.KIND_FILTER:
        if not FILTER_RE.fullmatch(name):
            return Response({'counted': False}, status=400)
    else:
        return Response({'counted': False}, status=400)

    ua = request.META.get('HTTP_USER_AGENT', '')
    if not ua or BOT_UA.search(ua):
        return Response({'counted': False})
    user = request.user if (request.user and request.user.is_authenticated) else None
    if user is not None and User.objects.filter(pk=user.pk).filter(_house_filter()).exists():
        return Response({'counted': False})

    if user is not None:
        who = f'u{user.pk}'
    else:
        ip = request.META.get('HTTP_CF_CONNECTING_IP', '').strip() or request.META.get('REMOTE_ADDR', '')
        who = hashlib.sha256(f'{ip}|{ua}'.encode()).hexdigest()[:32]
    day = timezone.localdate()
    tag = hashlib.sha256(f'{kind}|{name}'.encode()).hexdigest()[:16]
    # Double envoi (rechargement, double rendu) dans les 5 secondes : compté une fois.
    if not cache.add(f'usage:recent:{tag}:{who}', 1, 5):
        return Response({'counted': False})
    new_visitor = cache.add(f'usage:jour:{day.isoformat()}:{tag}:{who}', 1, 26 * 3600)
    anon = user is None
    _bump(day, kind, name, new_visitor, anon)
    if kind == UsageDaily.KIND_PAGE:
        # Personnes distinctes sur tout le site ce jour-là (membres et visiteurs non connectés).
        new_on_site = cache.add(f'usage:site:{day.isoformat()}:{who}', 1, 26 * 3600)
        _bump(day, UsageDaily.KIND_SITE, 'visites', new_on_site, anon)
    return Response({'counted': True})
