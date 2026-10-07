"""Cloche de la barre du haut.

GET  /api/notifications/            les 30 dernières + nombre de non lues
GET  /api/notifications/non-lues/   nombre de non lues (interrogé toutes les minutes par le site)
POST /api/notifications/lues/       {ids: [..]} ou {} pour tout marquer comme lu
"""
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification

LIMIT = 30


def _unread(user):
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


def _avatar(user):
    from apps.users.serializers import AuthorSerializer
    return AuthorSerializer(user).data.get('avatar') if user else None


def _url(n):
    # Page d'un exercice, d'une leçon ou d'un examen : on ouvre la discussion sur le commentaire,
    # avec le champ de réponse prêt (ContentDetail lit « ?commentaire= »).
    if n.target.startswith('content:') and n.comment_id:
        return f'{n.link}?commentaire={n.comment_id}#discussion'
    return f'{n.link}#commentaires'


def serialize(n):
    return {
        'id': n.id, 'kind': n.kind, 'title': n.title, 'url': _url(n), 'excerpt': n.excerpt, 'count': n.count,
        'actor': {'username': n.actor.username, 'avatar': _avatar(n.actor)} if n.actor else None,
        'updated_at': n.updated_at, 'read': n.read_at is not None,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_list(request):
    rows = Notification.objects.filter(recipient=request.user).select_related('actor', 'actor__profile')[:LIMIT]
    return Response({'unread': _unread(request.user), 'results': [serialize(n) for n in rows]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unread_count(request):
    return Response({'unread': _unread(request.user)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_read(request):
    qs = Notification.objects.filter(recipient=request.user, read_at__isnull=True)
    ids = request.data.get('ids')
    if isinstance(ids, list):
        qs = qs.filter(id__in=[i for i in ids if isinstance(i, int)][:200])
    qs.update(read_at=timezone.now())
    return Response({'unread': _unread(request.user)})
