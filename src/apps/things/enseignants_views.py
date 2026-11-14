"""Pilotage › Enseignants (14/11/2026) : l'équipe seule nomme, relie à un compte, fusionne les enseignants et les pose
sur les contenus (Natsu : « moi seul, avec toi quand tu importes »). Logique : things/enseignants.py."""
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.caracteristics.models import School
from apps.users.admin_dashboard import IsSuperuser
from apps.users.noms import nom_complet

from .enseignants import serialiser
from .models import Content, Enseignant

CIVILITES = ('M.', 'Mme', '')


def _carte(e, n=None):
    u = e.user
    return {
        'id': e.id, 'civilite': e.civilite, 'prenom': e.prenom, 'nom': e.nom, 'nom_affiche': e.nom_affiche,
        'school': {'id': e.school.id, 'name': e.school.name, 'city': e.school.city} if e.school_id else None,
        'compte': {'id': u.id, 'username': u.username, 'nom': nom_complet(u) or u.username} if u else None,
        'contenus': n if n is not None else e.contenus.count(),
    }


def _appliquer(e, data):
    """Champs envoyés (les autres restent) ; renvoie un message d'erreur ou None."""
    if 'civilite' in data:
        if data['civilite'] not in CIVILITES:
            return 'Civilité : « M. », « Mme » ou rien.'
        e.civilite = data['civilite']
    for champ, longueur in (('prenom', 60), ('nom', 80)):
        if champ in data:
            v = ' '.join(str(data[champ] or '').split())
            if len(v) > longueur:
                return f'{champ.capitalize()} : {longueur} caractères au plus.'
            setattr(e, champ, v)
    if not e.nom:
        return 'Le nom est obligatoire.'
    if 'school' in data:
        e.school = School.objects.filter(pk=data['school']).first() if data['school'] else None
    if 'compte' in data:
        pseudo = str(data['compte'] or '').strip().lstrip('@')
        if not pseudo:
            e.user = None
        else:
            u = User.objects.filter(username__iexact=pseudo).first()
            if u is None:
                return f'Aucun compte « {pseudo} ».'
            autre = Enseignant.objects.filter(user=u).exclude(pk=e.pk).first()
            if autre is not None:
                return f'Ce compte est déjà relié à {autre.nom_affiche}.'
            e.user = u
    return None


@api_view(['GET', 'POST'])
@permission_classes([IsSuperuser])
def enseignants_view(request):
    """GET : tous les enseignants avec leur nombre de contenus. POST {civilite, prenom, nom, school, compte} : créer."""
    if request.method == 'GET':
        rows = (Enseignant.objects.select_related('school', 'user').annotate(n=Count('contenus', distinct=True))
                .order_by('nom', 'prenom'))
        return Response({'results': [_carte(e, e.n) for e in rows]})
    e = Enseignant()
    erreur = _appliquer(e, request.data if isinstance(request.data, dict) else {})
    if erreur:
        return Response({'error': erreur}, status=400)
    e.save()
    return Response(_carte(e, 0), status=201)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsSuperuser])
def enseignant_view(request, pk):
    """PATCH : renommer, établissement, compte relié (pseudo, vide = aucun). DELETE : supprimer (les contenus perdent
    seulement ce nom)."""
    e = Enseignant.objects.select_related('school', 'user').filter(pk=pk).first()
    if e is None:
        return Response({'error': 'Enseignant introuvable.'}, status=404)
    if request.method == 'DELETE':
        e.delete()
        return Response(status=204)
    erreur = _appliquer(e, request.data if isinstance(request.data, dict) else {})
    if erreur:
        return Response({'error': erreur}, status=400)
    e.save()
    return Response(_carte(e))


@api_view(['POST'])
@permission_classes([IsSuperuser])
def enseignant_fusionner_view(request, pk):
    """POST {dans: id} : « Naoufal » et « Naoufel » sont la même personne. Les contenus passent à `dans`, qui garde son
    nom et reprend ce qui lui manque (prénom, civilité, établissement, compte) ; l'autre est supprimé."""
    source = Enseignant.objects.filter(pk=pk).first()
    cible = Enseignant.objects.filter(pk=(request.data or {}).get('dans')).first() if isinstance(request.data, dict) else None
    if source is None or cible is None or source.pk == cible.pk:
        return Response({'error': 'Choisir deux enseignants différents.'}, status=400)
    with transaction.atomic():
        for c in source.contenus.all():
            c.enseignants.add(cible)
        cible.prenom = cible.prenom or source.prenom
        cible.civilite = cible.civilite or source.civilite
        cible.school = cible.school or source.school
        compte = source.user if cible.user_id is None else None
        source.delete()
        if compte is not None:
            cible.user = compte
        cible.save()
    return Response(_carte(cible))


@api_view(['GET'])
@permission_classes([IsSuperuser])
def enseignant_contenus_view(request, pk):
    """Contenus d'un enseignant (fiche du Pilotage)."""
    rows = Content.objects.filter(enseignants__id=pk).order_by('type', 'title').values('id', 'type', 'title')[:500]
    return Response({'results': list(rows)})


@api_view(['PUT'])
@permission_classes([IsSuperuser])
def contenu_enseignants_view(request, pk):
    """PUT {ids: [..]} : enseignants d'un contenu (page du contenu, équipe seulement)."""
    content = Content.objects.filter(pk=pk).first()
    if content is None:
        return Response({'error': 'Contenu introuvable.'}, status=404)
    ids = (request.data or {}).get('ids') if isinstance(request.data, dict) else None
    if not isinstance(ids, list) or len(ids) > 6:
        return Response({'error': 'ids : liste de 6 enseignants au plus.'}, status=400)
    ens = list(Enseignant.objects.filter(pk__in=[i for i in ids if isinstance(i, int)]))
    if len(ens) != len(set(i for i in ids if isinstance(i, int))) or len(ens) != len(ids):
        return Response({'error': 'Enseignant inconnu.'}, status=400)
    content.enseignants.set(ens)
    ordre = {i: n for n, i in enumerate(ids)}
    return Response({'enseignants': serialiser(sorted(ens, key=lambda e: ordre[e.id]), request.user)})
