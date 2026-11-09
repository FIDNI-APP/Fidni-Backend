"""API du défi du jour, ouverte aux visiteurs : seuls les membres ont une tentative et une série enregistrées.

Un visiteur n'a rien en base : son navigateur garde son nombre d'essais et le renvoie (« essai »). Tricher n'y gagne rien :
la solution d'un défi n'est pas un secret, seule la réponse attendue ne part pas avant la fin de la tentative.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from config.throttling import DefiReponseThrottle

from . import reponses
from .models import Defi, TentativeDefi

ESSAIS_MAX = 3
STATS_MIN = 20  # en dessous, le taux de réussite ne veut rien dire : on n'affiche rien
ARCHIVES_MAX = 120
MAROC = ZoneInfo('Africa/Casablanca')


def aujourdhui():
    """Le jour change à minuit au Maroc, où sont les élèves (le serveur est en UTC)."""
    return timezone.now().astimezone(MAROC).date()


def _publies():
    return Defi.objects.filter(valide=True, date__lte=aujourdhui())


def _defi(texte):
    try:
        jour = datetime.strptime(texte, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None
    return _publies().filter(date=jour).first()


def _connecte(request):
    return bool(request.user and request.user.is_authenticated)


def jours_trouves(user):
    """Jours dont le défi a été trouvé le jour même (ceux qui comptent dans une série)."""
    return set(TentativeDefi.objects.filter(user=user, statut=TentativeDefi.TROUVE, le_jour_meme=True)
               .values_list('defi__date', flat=True))


def serie(user, trouves=None):
    """Défis publiés d'affilée trouvés le jour même. Celui d'aujourd'hui, pas encore fait, ne casse pas la série."""
    trouves = jours_trouves(user) if trouves is None else trouves
    if not trouves:
        return 0
    n, jour = 0, aujourdhui()
    for d in _publies().order_by('-date').values_list('date', flat=True):
        if d in trouves:
            n += 1
        elif d != jour:
            break
    return n


def meilleure_serie(user, trouves=None):
    """Plus longue série de défis publiés trouvés le jour même (badge « Série du défi », profil). Même règle que
    `serie` : un jour sans défi publié ne casse rien, un défi publié manqué casse la série."""
    trouves = jours_trouves(user) if trouves is None else trouves
    if not trouves:
        return 0
    best = run = 0
    for d in _publies().filter(date__gte=min(trouves)).order_by('date').values_list('date', flat=True):
        run = run + 1 if d in trouves else 0
        best = max(best, run)
    return best


def _stats(defi):
    s = defi.tentatives.exclude(statut=TentativeDefi.EN_COURS).aggregate(
        total=Count('id'), trouves=Count('id', filter=Q(statut=TentativeDefi.TROUVE)))
    return s if s['total'] >= STATS_MIN else None


def _etat(defi, tentative=None, essais=0, statut=TentativeDefi.EN_COURS):
    """Partie qui dépend de la tentative : la réponse et la solution n'y figurent qu'une fois la tentative finie."""
    if tentative:
        essais, statut = tentative.essais, tentative.statut
    etat = {'statut': statut, 'essais': essais, 'essais_restants': max(ESSAIS_MAX - essais, 0),
            'indices_vus': tentative.indices_vus if tentative else 0}
    if statut != TentativeDefi.EN_COURS:
        etat.update(reponse=defi.reponse, solution=defi.solution, stats=_stats(defi))
    return etat


def _payload(defi, request):
    connecte = _connecte(request)
    tentative = TentativeDefi.objects.filter(user=request.user, defi=defi).first() if connecte else None
    return {'date': defi.date.isoformat(), 'du_jour': defi.date == aujourdhui(), 'titre': defi.titre, 'theme': defi.theme,
            'difficulte': defi.difficulte, 'enonce': defi.enonce, 'consigne': defi.consigne, 'indices': defi.indices,
            'essais_max': ESSAIS_MAX, 'serie': serie(request.user) if connecte else None, **_etat(defi, tentative)}


def _introuvable():
    return Response({'detail': 'Ce défi n’existe pas.'}, status=404)


def _tentative(request, defi):
    return TentativeDefi.objects.get_or_create(user=request.user, defi=defi)[0]


@api_view(['GET'])
@permission_classes([AllowAny])
def du_jour(request):
    defi = _publies().filter(date=aujourdhui()).first()
    return Response({'defi': _payload(defi, request) if defi else None})


@api_view(['GET'])
@permission_classes([AllowAny])
def etat(request):
    """Pastille « Défi du jour » du menu (09/11/2026) : y a-t-il un défi aujourd'hui, et où en est le membre. Léger : ni
    l'énoncé ni les indices. Un visiteur garde son état dans son navigateur (le site le relit lui-même)."""
    defi = _publies().filter(date=aujourdhui()).only('id', 'date').first()
    if not defi:
        return Response({'date': None, 'statut': None, 'serie': None})
    if not _connecte(request):
        return Response({'date': defi.date.isoformat(), 'statut': None, 'serie': None})
    statut = TentativeDefi.objects.filter(user=request.user, defi=defi).values_list('statut', flat=True).first()
    return Response({'date': defi.date.isoformat(), 'statut': statut or TentativeDefi.EN_COURS, 'serie': serie(request.user)})


@api_view(['GET'])
@permission_classes([AllowAny])
def archives(request):
    """Défis des jours passés, du plus récent au plus ancien, avec l'état du membre connecté."""
    defis = list(_publies().filter(date__lt=aujourdhui()).order_by('-date')[:ARCHIVES_MAX])
    statuts = {}
    if _connecte(request):
        statuts = dict(TentativeDefi.objects.filter(user=request.user, defi__in=defis).values_list('defi_id', 'statut'))
    return Response({'results': [
        {'date': d.date.isoformat(), 'titre': d.titre, 'theme': d.theme, 'difficulte': d.difficulte,
         'statut': statuts.get(d.id, TentativeDefi.EN_COURS)} for d in defis]})


@api_view(['GET'])
@permission_classes([AllowAny])
def detail(request, jour):
    defi = _defi(jour)
    return Response(_payload(defi, request)) if defi else _introuvable()


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([DefiReponseThrottle])
def repondre(request, jour):
    defi = _defi(jour)
    if not defi:
        return _introuvable()
    texte = request.data.get('reponse')
    if reponses.lire(texte) is None:
        return Response({'detail': 'Écris un nombre, par exemple 12, -3 ou 3/4.', 'code': 'format'}, status=400)
    bonne = reponses.juste(texte, defi.reponse)

    if not _connecte(request):
        essai = request.data.get('essai')
        essai = essai if isinstance(essai, int) and not isinstance(essai, bool) and 1 <= essai <= ESSAIS_MAX else 1
        statut = TentativeDefi.TROUVE if bonne else TentativeDefi.RATE if essai >= ESSAIS_MAX else TentativeDefi.EN_COURS
        return Response({'juste': bonne, **_etat(defi, essais=essai, statut=statut)})

    t = _tentative(request, defi)
    if t.statut != TentativeDefi.EN_COURS:  # déjà fini (autre onglet) : l'état ne bouge plus
        return Response({'juste': t.statut == TentativeDefi.TROUVE, 'serie': serie(request.user), **_etat(defi, t)})
    t.essais += 1
    if bonne:
        t.statut, t.le_jour_meme = TentativeDefi.TROUVE, defi.date == aujourdhui()
    elif t.essais >= ESSAIS_MAX:
        t.statut = TentativeDefi.RATE
    t.save()
    return Response({'juste': bonne, 'serie': serie(request.user), **_etat(defi, t)})


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([DefiReponseThrottle])
def indice(request, jour):
    """Note qu'un membre a ouvert un indice de plus (statistique du Pilotage). Les indices sont déjà dans le défi."""
    defi = _defi(jour)
    if not defi:
        return _introuvable()
    if not _connecte(request):
        return Response({'indices_vus': None})
    t = _tentative(request, defi)
    if t.indices_vus < len(defi.indices):
        t.indices_vus += 1
        t.save(update_fields=['indices_vus', 'updated_at'])
    return Response({'indices_vus': t.indices_vus})


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([DefiReponseThrottle])
def abandonner(request, jour):
    """« Voir la solution » : met fin à la tentative d'un membre ; un défi déjà trouvé reste trouvé."""
    defi = _defi(jour)
    if not defi:
        return _introuvable()
    if not _connecte(request):
        return Response(_etat(defi, statut=TentativeDefi.RATE))
    t = _tentative(request, defi)
    if t.statut == TentativeDefi.EN_COURS:
        t.statut = TentativeDefi.RATE
        t.save(update_fields=['statut', 'updated_at'])
    return Response({'serie': serie(request.user), **_etat(defi, t)})
