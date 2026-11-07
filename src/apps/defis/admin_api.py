"""Pilotage › Défis : relire, corriger et valider les défis à venir ; voir comment les élèves s'en sortent."""
from datetime import datetime, timedelta

from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.users.admin_dashboard import IsSuperuser

from . import reponses
from .models import DIFFICULTES, THEMES, Defi, TentativeDefi
from .views import aujourdhui


def _ligne(d):
    return {'id': d.id, 'cle': d.cle, 'date': d.date.isoformat(), 'titre': d.titre, 'theme': d.theme,
            'difficulte': d.difficulte, 'enonce': d.enonce, 'consigne': d.consigne, 'reponse': d.reponse,
            'indices': d.indices, 'solution': d.solution, 'source': d.source, 'valide': d.valide,
            'participants': d.participants, 'trouves': d.trouves, 'indices_moyens': round(d.indices_moyens or 0, 1)}


def _liste():
    return Defi.objects.annotate(
        participants=Count('tentatives', filter=~Q(tentatives__statut=TentativeDefi.EN_COURS)),
        trouves=Count('tentatives', filter=Q(tentatives__statut=TentativeDefi.TROUVE)),
        indices_moyens=Avg('tentatives__indices_vus'))


def a_valider():
    """Défis à venir qui attendent la relecture (pastille de l'onglet)."""
    return Defi.objects.filter(valide=False, date__gte=aujourdhui()).count()


@api_view(['GET'])
@permission_classes([IsSuperuser])
def liste(request):
    jour = aujourdhui()
    defis = list(_liste().order_by('date'))
    # Jours d'affilée couverts par un défi validé, à partir d'aujourd'hui : l'accueil n'affiche rien au-delà.
    valides = {d.date for d in defis if d.valide}
    couverts, cur = 0, jour
    while cur in valides:
        couverts, cur = couverts + 1, cur + timedelta(days=1)
    return Response({'aujourdhui': jour.isoformat(), 'jours_couverts': couverts, 'a_valider': a_valider(),
                     'results': [_ligne(d) for d in defis]})


def _indices_valides(v):
    return isinstance(v, list) and all(
        isinstance(i, dict) and isinstance(i.get('titre'), str) and isinstance(i.get('texte'), str)
        and i['titre'].strip() and i['texte'].strip() for i in v)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsSuperuser])
def un_defi(request, pk):
    d = get_object_or_404(Defi, pk=pk)
    if request.method == 'DELETE':
        if d.tentatives.exists():
            return Response({'detail': 'Des élèves ont déjà répondu à ce défi : il reste en place.'}, status=400)
        d.delete()
        return Response(status=204)

    err = {}
    data = request.data
    for champ, maxi in (('titre', 120), ('enonce', 4000), ('consigne', 120), ('solution', 8000)):
        if champ in data:
            v = data[champ]
            if not isinstance(v, str) or not v.strip() or len(v) > maxi:
                err[champ] = 'Texte obligatoire, ou trop long.'
            else:
                setattr(d, champ, v.strip())
    if 'reponse' in data:
        if reponses.lire(data['reponse']) is None:
            err['reponse'] = 'La réponse doit être un nombre : 12, -3, 0,5 ou 3/4.'
        else:
            d.reponse = data['reponse'].strip()
    if 'difficulte' in data:
        if data['difficulte'] not in dict(DIFFICULTES):
            err['difficulte'] = 'Difficulté inconnue.'
        else:
            d.difficulte = data['difficulte']
    if 'theme' in data:
        if data['theme'] not in dict(THEMES):
            err['theme'] = 'Thème inconnu.'
        else:
            d.theme = data['theme']
    if 'indices' in data:
        if not _indices_valides(data['indices']):
            err['indices'] = 'Chaque indice a un titre et un texte.'
        else:
            d.indices = data['indices']
    if 'date' in data:
        try:
            jour = datetime.strptime(str(data['date']), '%Y-%m-%d').date()
        except ValueError:
            err['date'] = 'Date invalide.'
        else:
            if Defi.objects.filter(date=jour).exclude(pk=d.pk).exists():
                err['date'] = 'Un autre défi est déjà prévu ce jour-là.'
            elif jour != d.date and d.tentatives.exists():
                err['date'] = 'Des élèves ont déjà répondu à ce défi : sa date reste en place.'
            else:
                d.date = jour
    if 'valide' in data:
        if not isinstance(data['valide'], bool):
            err['valide'] = 'Vrai ou faux attendu.'
        else:
            d.valide = data['valide']
    if err:
        return Response(err, status=400)
    d.save()
    return Response(_ligne(_liste().get(pk=d.pk)))


@api_view(['POST'])
@permission_classes([IsSuperuser])
def valider(request):
    """Valide d'un coup les défis cochés (« ids »)."""
    ids = request.data.get('ids')
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        return Response({'ids': 'Liste de défis attendue.'}, status=400)
    return Response({'valides': Defi.objects.filter(pk__in=ids).update(valide=True)})
