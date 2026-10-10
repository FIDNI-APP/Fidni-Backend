"""Erreurs d'affichage du site (10/10/2026) : POST /api/logs/client-errors/

Une page qui plante dans le navigateur ne laissait aucune trace côté serveur (la page blanche du Pilotage
n'a été vue que par l'administrateur). Les filets du front (components/common/ErrorBoundary) envoient
désormais l'erreur ici ; elle est rangée dans ErrorLog (console /logs), regroupée par message : la même
erreur ne fait qu'augmenter le compteur `count`. Ouvert aux visiteurs, donc borné : 30 envois par heure et
par adresse IP (ClientErrorThrottle), et au plus NEW_PER_HOUR nouvelles lignes par heure pour tout le site
(au-delà, seules les erreurs déjà connues sont comptées).
"""
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from config.throttling import ClientErrorThrottle

from .middleware import get_client_ip
from .models import ErrorLog

EXCEPTION_TYPE = 'Erreur d’affichage (navigateur)'
NEW_PER_HOUR = 200


def _text(value, limit):
    """Texte borné ; PostgreSQL refuse le caractère NUL dans une colonne texte (erreur 500)."""
    if not isinstance(value, (str, int, float)):
        return ''
    return str(value).replace('\x00', '')[:limit]


def _new_rows_allowed():
    key = f'client_errors:new:{timezone.now():%Y%m%d%H}'
    cache.add(key, 0, 3600)
    try:
        return cache.incr(key) <= NEW_PER_HOUR
    except ValueError:  # clé expirée entre add et incr
        return True


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

    known = (ErrorLog.objects.filter(exception_type=EXCEPTION_TYPE, message=message, status__in=['new', 'investigating'])
             .order_by('-last_seen').values_list('pk', flat=True).first())
    if known:
        # Incrément en base (deux envois simultanés ne perdent pas de compte) ; dernière page touchée gardée.
        ErrorLog.objects.filter(pk=known).update(count=F('count') + 1, endpoint=path, last_seen=timezone.now())
    elif _new_rows_allowed():
        ErrorLog.objects.create(
            severity='error', message=message, exception_type=EXCEPTION_TYPE,
            traceback=_text(data.get('stack'), 4000) or None, endpoint=path, method='GET', user=user,
            ip_address=get_client_ip(request), user_agent=_text(request.META.get('HTTP_USER_AGENT', ''), 500),
            extra_context={'source': 'navigateur', 'component_stack': _text(data.get('component_stack'), 2000)},
        )
    return Response(status=204)
