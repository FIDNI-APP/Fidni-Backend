"""Pilotage › Messages à valider (20/11/2026, discussions/moderation.py) : premiers messages des nouveaux comptes.

GET  /api/pilotage/messages-a-valider/                         → les messages en attente, les plus anciens d'abord
POST /api/pilotage/messages-a-valider/<discussion|reponse>/<id>/accepter/  → visible, compté, notifications envoyées
POST /api/pilotage/messages-a-valider/<discussion|reponse>/<id>/refuser/   → supprimé (avec ses fichiers)
Réservé à l'équipe (superuser), comme les signalements.
"""
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.users.admin_dashboard import IsSuperuser

from .models import COMMENTAIRE, Discussion, Reply, plain_text
from .services import delete_files, later, link, notify_new_comment, notify_new_discussion, notify_new_reply

MAX = 100


def _auteur(user):
    profil = getattr(user, 'profile', None)
    return {
        'id': user.id, 'username': user.username,
        'nom': f'{user.first_name} {user.last_name}'.strip(),
        'inscrit_le': user.date_joined,
        'niveau': getattr(getattr(profil, 'class_level', None), 'name', None),
        'valides': Discussion.objects.filter(author=user, en_attente=False).count()
        + Reply.objects.filter(author=user, en_attente=False).count(),
    }


def _ligne(obj, type_, discussion):
    return {
        'type': type_,
        'id': obj.id,
        'genre': discussion.genre,
        'titre': discussion.title,
        'texte': plain_text(obj.body)[:2000],
        'html': obj.body,
        'cree_le': obj.created_at,
        'url': link(discussion) + (f'#reponse-{obj.id}' if type_ == 'reponse' else ''),
        'contexte': plain_text(discussion.body)[:200] if type_ == 'reponse' else '',
        'fichiers': obj.attachments.count(),
        'auteur': _auteur(obj.author),
    }


@api_view(['GET'])
@permission_classes([IsSuperuser])
def a_valider(request):
    lignes = [_ligne(d, 'discussion', d) for d in Discussion.objects.filter(en_attente=True)
              .select_related('author__profile__class_level').order_by('created_at')[:MAX]]
    lignes += [_ligne(r, 'reponse', r.discussion) for r in Reply.objects.filter(en_attente=True)
               .select_related('author__profile__class_level', 'discussion').order_by('created_at')[:MAX]]
    lignes.sort(key=lambda x: x['cree_le'])
    return Response({'count': len(lignes), 'results': lignes})


def _objet(type_, pk):
    if type_ == 'discussion':
        return get_object_or_404(Discussion, pk=pk, en_attente=True)
    if type_ == 'reponse':
        return get_object_or_404(Reply.objects.select_related('discussion'), pk=pk, en_attente=True)
    return None


@api_view(['POST'])
@permission_classes([IsSuperuser])
def accepter(request, type_, pk):
    obj = _objet(type_, pk)
    if obj is None:
        return Response({'error': 'type inconnu'}, status=400)
    with transaction.atomic():
        if type_ == 'discussion':
            Discussion.objects.filter(pk=obj.pk).update(en_attente=False, last_activity_at=timezone.now())
            obj.refresh_from_db()
            later(notify_new_comment if obj.genre == COMMENTAIRE else notify_new_discussion, obj)
        else:
            Reply.objects.filter(pk=obj.pk).update(en_attente=False)
            Discussion.objects.filter(pk=obj.discussion_id).update(
                reply_count=F('reply_count') + 1, last_activity_at=timezone.now())
            obj.refresh_from_db()
            later(notify_new_reply, obj)
    return Response({'accepte': True})


@api_view(['POST'])
@permission_classes([IsSuperuser])
def refuser(request, type_, pk):
    obj = _objet(type_, pk)
    if obj is None:
        return Response({'error': 'type inconnu'}, status=400)
    if type_ == 'discussion':
        delete_files([(Discussion, [obj.id]), (Reply, list(obj.replies.values_list('id', flat=True)))])
    else:
        delete_files([(Reply, [obj.id])])
    obj.delete()
    return Response({'refuse': True})


def compte():
    """Nombre de messages en attente (Pilotage › À traiter, moniteur)."""
    return Discussion.objects.filter(en_attente=True).count() + Reply.objects.filter(en_attente=True).count()
