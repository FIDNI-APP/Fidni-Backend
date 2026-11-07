"""Rapports de la politique de sécurité du contenu (CSP) : POST /api/logs/csp/ (07/11/2026).

Le site envoie d'abord sa politique en « Content-Security-Policy-Report-Only » (frontend/security-headers.conf) :
rien n'est bloqué, mais chaque navigateur signale ici ce qu'elle aurait bloqué (script, cadre, image d'une origine
non prévue). On regarde ces rapports dans la console /logs, on complète la politique, puis on la rend bloquante.
Rangés dans ErrorLog, regroupés par directive et origine ; ouvert aux visiteurs, donc borné comme les erreurs
d'affichage (client_errors.py) : par IP, et un plafond de nouvelles lignes par heure pour tout le site.
"""
import json

from django.db.models import F
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.request import Request

from config.throttling import ClientErrorThrottle

from .client_errors import _new_rows_allowed, _text
from .middleware import get_client_ip
from .models import ErrorLog

EXCEPTION_TYPE = 'Politique CSP (navigateur)'
BODY_MAX = 20_000


def _rapports(body):
    """Corps d'un rapport → [(directive, origine bloquée, page)] : format report-uri ({"csp-report": …}) ou
    Reporting API ([{"type": "csp-violation", "body": …}])."""
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return []
    items = data if isinstance(data, list) else [data]
    out = []
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        r = item.get('csp-report') if 'csp-report' in item else item.get('body')
        if not isinstance(r, dict):
            continue
        directive = r.get('effective-directive') or r.get('effectiveDirective') or r.get('violated-directive') or ''
        bloque = r.get('blocked-uri') or r.get('blockedURL') or ''
        page = r.get('document-uri') or r.get('documentURL') or ''
        out.append((_text(directive, 80), _text(bloque, 300), _text(page, 300)))
    return out


@csrf_exempt
@require_POST
def csp_report(request):
    if len(request.body) > BODY_MAX:
        return HttpResponse(status=413)
    throttle = ClientErrorThrottle()
    if not throttle.allow_request(Request(request), None):
        return HttpResponse(status=429)
    for directive, bloque, page in _rapports(request.body):
        message = f'CSP {directive} : {bloque}'[:500]
        known = (ErrorLog.objects.filter(exception_type=EXCEPTION_TYPE, message=message, status__in=['new', 'investigating'])
                 .values_list('pk', flat=True).first())
        if known:
            ErrorLog.objects.filter(pk=known).update(count=F('count') + 1, endpoint=page or None, last_seen=timezone.now())
        elif _new_rows_allowed():
            ErrorLog.objects.create(
                severity='warning', message=message, exception_type=EXCEPTION_TYPE, endpoint=page or None,
                method='POST', ip_address=get_client_ip(request),
                user_agent=_text(request.META.get('HTTP_USER_AGENT', ''), 500),
                extra_context={'source': 'csp', 'directive': directive, 'bloque': bloque},
            )
    return HttpResponse(status=204)
