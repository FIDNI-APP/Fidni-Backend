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
    # Réponse à un signalement : le message en entier, dans l'onglet « Messages » du profil (18/10/2026).
    if n.kind in (Notification.KIND_REPORT, Notification.KIND_MESSAGE):
        return f'/profile/{n.recipient.username}?tab=messages&message={n.id}'
    if n.kind in (Notification.KIND_QUIZ, Notification.KIND_COPIE):
        return n.link
    # Page d'un exercice, d'une leçon ou d'un examen : on ouvre la discussion sur le commentaire,
    # avec le champ de réponse prêt (ContentDetail lit « ?commentaire= »).
    if n.target.startswith('content:') and n.comment_id:
        return f'{n.link}?commentaire={n.comment_id}#discussion'
    return f'{n.link}#commentaires'


def serialize(n):
    return {
        'id': n.id, 'kind': n.kind, 'title': n.title, 'url': _url(n), 'excerpt': n.excerpt, 'count': n.count,
        'message': n.message,
        'actor': {'username': n.actor.username, 'avatar': _avatar(n.actor)} if n.actor else None,
        'updated_at': n.updated_at, 'read': n.read_at is not None,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_list(request):
    rows = Notification.objects.filter(recipient=request.user).select_related('recipient', 'actor', 'actor__profile')[:LIMIT]
    return Response({'unread': _unread(request.user), 'results': [serialize(n) for n in rows]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def messages(request):
    """GET /api/notifications/messages/ : les réponses de l'équipe à ses signalements, en entier, avec son
    signalement (motif, endroit, texte) et le contenu concerné — onglet « Messages » du profil."""
    from apps.things.models import ContentReport

    rows = list(Notification.objects.filter(recipient=request.user,
                                            kind__in=(Notification.KIND_REPORT, Notification.KIND_MESSAGE))[:100])
    ids = [int(n.target.split(':', 1)[1]) for n in rows if n.kind == Notification.KIND_REPORT and n.target.split(':', 1)[-1].isdigit()]
    reports = {r.id: r for r in ContentReport.objects.filter(id__in=ids, user=request.user).select_related('content')}
    out = []
    for n in rows:
        r = (reports.get(int(n.target.split(':', 1)[1]))
             if n.kind == Notification.KIND_REPORT and n.target.split(':', 1)[-1].isdigit() else None)
        out.append({
            'id': n.id, 'kind': n.kind, 'title': n.title, 'link': n.link, 'message': n.message or n.excerpt,
            'updated_at': n.updated_at, 'read': n.read_at is not None,
            'report': {
                'reason': r.get_reason_display(), 'item_label': r.item_label, 'description': r.description,
                'status': r.status, 'created_at': r.created_at,
            } if r else None,
        })
    return Response({'results': out})


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
