"""Correction de sa propre copie par l'IA (fonction cachée, 20/10/2026).

Un élève photographie sa copie d'un devoir, d'un examen, d'un bac national ou d'un simili ; l'IA (même modèle et même
chaîne que Classes › Évaluations : transcription, puis note question par question) la compare au corrigé de Fidni et
lui montre où il a perdu des points. Pas de professeur : le résultat est visible tout de suite, par l'élève seul.

Accès : les administrateurs (sans limite) et les personnes à qui un administrateur a donné un nombre de corrections
(AccesCorrection, géré dans Pilotage). Pour les autres, rien n'existe : les routes répondent 404.
Techniquement c'est une Evaluation sans classe (created_by = l'élève) avec une seule Copie de cet élève.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.users.admin_dashboard import IsSuperuser
from config.throttling import CopiesIAThrottle, CopiesUploadThrottle

from . import analyse, images, traitement
from .bareme import completer_ids, questions
from .models import AccesCorrection, Copie, Evaluation, Page
from .views import _actif, _detail_copie, _err, _note

TYPES = ('exam', 'exercise')


def _acces(user):
    """(autorisé, restant, limite) : restant et limite valent None pour un administrateur."""
    if user.is_superuser:
        return True, None, None
    a = AccesCorrection.objects.filter(user=user, actif=True).first()
    return (True, a.restant, a.limite) if a else (False, 0, 0)


def _etat(user):
    ok, restant, limite = _acces(user)
    return {'acces': ok, 'restant': restant, 'limite': limite}


def _exiger(user):
    _actif()
    if not _acces(user)[0]:
        raise Http404


def _solo(request, pk):
    _exiger(request.user)
    return get_object_or_404(Copie.objects.select_related('evaluation__content', 'eleve'), pk=pk,
                             eleve=request.user, evaluation__classroom__isnull=True)


def _contenu(e):
    return {'id': e.content.id, 'type': e.content.type, 'title': e.content.title} if e.content else None


def _carte(c):
    e = c.evaluation
    q = questions(e.sujet, e.maxima)
    return {'id': c.id, 'statut': c.statut, 'etape': c.etape, 'titre': e.titre, 'created_at': c.created_at.isoformat(),
            'content': _contenu(e), **_note(e, c, q)}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def acces(request):
    """Le bouton n'apparaît que si `acces` est vrai ; `restant` : corrections encore permises (null : sans limite)."""
    if not getattr(settings, 'COPIES_ACTIVES', True):
        return Response({'acces': False, 'restant': 0, 'limite': 0})
    return Response(_etat(request.user))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def mes_corrections(request):
    _exiger(request.user)
    qs = (Copie.objects.filter(eleve=request.user, evaluation__classroom__isnull=True)
          .select_related('evaluation__content').order_by('-created_at'))
    if request.query_params.get('contenu'):
        qs = qs.filter(evaluation__content_id=request.query_params['contenu'])
    return Response({'corrections': [_carte(c) for c in qs[:50]], **_etat(request.user)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([CopiesIAThrottle, CopiesUploadThrottle])
def soumettre(request):
    """multipart : `contenu` (id d'un examen) et `fichiers` (photos ou PDF de la copie, dans l'ordre)."""
    _exiger(request.user)
    from apps.things.models import Content
    content = Content.objects.filter(pk=request.data.get('contenu') or 0, type__in=TYPES).first()
    if content is None:
        return _err('Contenu introuvable.', 404)
    sujet = completer_ids(content.json_content)
    if not questions(sujet):
        return _err('Ce contenu n’a pas de questions à corriger.')
    fichiers = request.FILES.getlist('fichiers')
    if not fichiers:
        return _err('Ajoute au moins une photo ou un PDF de ta copie.')
    if Copie.objects.filter(eleve=request.user, evaluation__classroom__isnull=True,
                            statut__in=(Copie.EN_ATTENTE, Copie.EN_COURS)).exists():
        return _err('Une de tes copies est déjà en cours de correction : attends qu’elle soit finie.', 409)
    pages = []
    try:
        for f in fichiers:
            pages += images.pages(f.read(), f.name, f.content_type, limite=settings.COPIES_PAGES_MAX - len(pages))
    except images.FichierRefuse as exc:
        return _err(str(exc))
    if not pages:
        return _err('Aucune page lisible.')
    with transaction.atomic():
        if not request.user.is_superuser:
            a = AccesCorrection.objects.select_for_update().filter(user=request.user, actif=True).first()
            if a is None or a.restant <= 0:
                return _err('Tu as utilisé toutes tes corrections.', 429)
            a.utilisees += 1
            a.save(update_fields=['utilisees', 'updated_at'])
        e = Evaluation.objects.create(classroom=None, created_by=request.user, titre=content.title[:200],
                                      content=content, source=Evaluation.FIDNI, sujet=sujet, note_sur=20, pas=0.5)
        c = Copie.objects.create(evaluation=e, eleve=request.user, statut=Copie.EN_ATTENTE, etape='En attente')
        for i, (jpeg, w, h) in enumerate(pages, 1):
            Page.objects.create(copie=c, numero=i, largeur=w, hauteur=h, fichier=ContentFile(jpeg, name='page.jpg'))
    traitement.demarrer_corrections(e)
    return Response({'id': c.id, 'statut': c.statut, **_etat(request.user)}, status=202)


@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
def correction(request, pk):
    c = _solo(request, pk)
    e = c.evaluation
    if request.method == 'DELETE':
        if c.statut == Copie.EN_COURS:
            return _err('Correction en cours.', 409)
        e.delete()  # la copie, les pages et leurs fichiers partent avec
        return Response(status=204)
    out = _detail_copie(e, c, request.user, prof=False)
    out['finales'] = {k: {kk: vv for kk, vv in v.items() if kk != 'source'} for k, v in out['finales'].items()}
    tr, ia = c.transcription or {}, c.ia or {}
    out['reponses'] = {q['chemin']: {'texte': (tr.get(q['chemin']) or {}).get('texte', ''),
                                     'illisible': bool((tr.get(q['chemin']) or {}).get('illisible')),
                                     'confiance': (ia.get(q['chemin']) or {}).get('confiance')}
                       for q in out['questions']}
    out['content'] = _contenu(e)
    out['corrigee'] = c.statut == Copie.CORRIGEE
    out['points_faibles'] = analyse.points_faibles(e, c) if out['corrigee'] else []
    return Response(out)


# --------------------------------------------------------------------------- Pilotage : qui a le droit

def _ligne(a):
    return {'user': {'id': a.user_id, 'username': a.user.username}, 'limite': a.limite, 'utilisees': a.utilisees,
            'restant': a.restant, 'actif': a.actif, 'note': a.note, 'created_at': a.created_at.isoformat()}


def _limite(valeur):
    return max(0, min(10000, int(valeur)))


@api_view(['GET', 'POST'])
@permission_classes([IsSuperuser])
def admin_acces(request):
    """GET : les personnes qui ont accès. POST {username, limite, note?} : donne l'accès (ou change la limite)."""
    if request.method == 'GET':
        qs = AccesCorrection.objects.select_related('user').order_by('user__username')
        return Response({'acces': [_ligne(a) for a in qs], 'defaut': 5})
    nom = str(request.data.get('username') or '').strip().lstrip('@')
    user = User.objects.filter(username__iexact=nom).first() if nom else None
    if user is None:
        return _err('Aucun compte à ce nom d’utilisateur.', 404)
    try:
        limite = _limite(request.data.get('limite', 5))
    except (TypeError, ValueError):
        return _err('Limite invalide.')
    a, _ = AccesCorrection.objects.get_or_create(user=user)
    a.limite, a.actif = limite, True
    if 'note' in request.data:
        a.note = str(request.data.get('note') or '')[:200]
    a.save()
    return Response(_ligne(a), status=201)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsSuperuser])
def admin_acces_un(request, uid):
    a = get_object_or_404(AccesCorrection.objects.select_related('user'), user_id=uid)
    if request.method == 'DELETE':
        a.delete()
        return Response(status=204)
    d = request.data
    if 'limite' in d:
        try:
            a.limite = _limite(d['limite'])
        except (TypeError, ValueError):
            return _err('Limite invalide.')
    if 'actif' in d:
        a.actif = bool(d['actif'])
    if 'note' in d:
        a.note = str(d['note'] or '')[:200]
    if d.get('remettre_a_zero'):
        a.utilisees = 0
    a.save()
    return Response(_ligne(a))
