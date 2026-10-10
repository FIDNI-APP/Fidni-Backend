"""Erreurs d'affichage du site (10/10/2026) : POST /api/logs/client-errors/

Une page qui plante dans le navigateur ne laissait aucune trace côté serveur (la page blanche du Pilotage
n'a été vue que par l'administrateur). Les filets du front (components/common/ErrorBoundary) envoient
désormais l'erreur ici ; elle est rangée dans ErrorLog (console /logs), regroupée par message : la même
erreur ne fait qu'augmenter le compteur `count`. Ouvert aux visiteurs, limité par adresse IP.
"""
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from config.throttling import ClientErrorThrottle

from .middleware import get_client_ip
from .models import ErrorLog

EXCEPTION_TYPE = 'Erreur d’affichage (navigateur)'


def _text(value, limit):
    return str(value or '')[:limit] if isinstance(value, (str, int, float)) else ''


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([ClientErrorThrottle])
def client_error(request):
    data = request.data if isinstance(request.data, dict) else {}
    message = _text(data.get('message'), 500).strip()
    if not message:
        return Response({'detail': 'message manquant'}, status=400)
    path = _text(data.get('path'), 300) or None
    user = request.user if getattr(request.user, 'is_authenticated', False) else None

    existing = (ErrorLog.objects.filter(exception_type=EXCEPTION_TYPE, message=message,
                                        status__in=['new', 'investigating']).order_by('-last_seen').first())
    if existing:
        # Dernière page touchée, pour la retrouver dans la console.
        existing.endpoint = path
        existing.count += 1
        existing.save(update_fields=['endpoint', 'count', 'last_seen'])
    else:
        ErrorLog.objects.create(
            severity='error', message=message, exception_type=EXCEPTION_TYPE,
            traceback=_text(data.get('stack'), 4000) or None, endpoint=path, method='GET', user=user,
            ip_address=get_client_ip(request), user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            extra_context={'source': 'navigateur', 'component_stack': _text(data.get('component_stack'), 2000)},
        )
    return Response(status=204)
