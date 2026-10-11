"""Pilotage › Membres : comptes bannis (liste, ajout à la main, débannir). Logique : users/bans.py."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.users.admin_dashboard import IsSuperuser
from apps.users.bans import IP_BAN_DAYS, active_bans, add_ban
from apps.users.models import Bannissement


def _serialize(ban):
    return {'id': ban.id, 'kind': ban.kind, 'value': ban.value, 'username': ban.username, 'motif': ban.motif,
            'created_at': ban.created_at, 'expires_at': ban.expires_at,
            'created_by': ban.created_by.username if ban.created_by_id else None}


@api_view(['GET', 'POST'])
@permission_classes([IsSuperuser])
def bans_view(request):
    """GET /api/pilotage/bannis/ : bannissements en cours. POST {kind: email|ip, value, motif} : bannir à la main
    (par exemple l'adresse d'un compte déjà supprimé, retrouvée dans les journaux d'envoi des e-mails)."""
    if request.method == 'GET':
        bans = active_bans().select_related('created_by')[:500]
        return Response({'results': [_serialize(b) for b in bans], 'ip_days': IP_BAN_DAYS})
    data = request.data if isinstance(request.data, dict) else {}
    kind = data.get('kind')
    if kind not in (Bannissement.KIND_EMAIL, Bannissement.KIND_IP):
        return Response({'error': 'Type : adresse e-mail ou adresse IP.'}, status=400)
    ban = add_ban(kind, str(data.get('value') or ''), motif=str(data.get('motif') or 'Ajout manuel'), by=request.user)
    if ban is None:
        return Response({'error': 'Adresse e-mail invalide.' if kind == Bannissement.KIND_EMAIL else 'Adresse IP invalide.'},
                        status=400)
    return Response(_serialize(ban), status=201)


@api_view(['DELETE'])
@permission_classes([IsSuperuser])
def ban_delete_view(request, pk):
    """DELETE /api/pilotage/bannis/<id>/ : débannir."""
    deleted = Bannissement.objects.filter(pk=pk).delete()[0]
    if not deleted:
        return Response({'error': 'Bannissement introuvable.'}, status=404)
    return Response(status=204)
