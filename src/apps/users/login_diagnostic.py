"""Pilotage › Membres › « Un membre n'arrive pas à se connecter » : réservé aux administrateurs.

GET /api/pilotage/connexion/?q=<e-mail ou nom d'utilisateur>

Rassemble ce qui explique un échec de connexion, sans jamais montrer de mot de passe :
- le ou les comptes qui portent cet e-mail / ce nom (la connexion prend le plus ancien si deux comptes
  partagent la même adresse, à la casse près) et leur état (actif, e-mail confirmé, dernière connexion,
  connexion avec Google) ;
- le blocage temporaire après trop d'essais (LoginAccountThrottle : 15 essais par heure et par identifiant) ;
- les requêtes d'authentification en échec (APILog : connexion, connexion Google, inscription, confirmation
  d'e-mail, mot de passe oublié) qui contiennent l'identifiant ou viennent du compte, et les erreurs serveur
  du compte (ErrorLog).
Les journaux sont conservés 180 jours (apps/users/legal.py) ; une connexion réussie n'y figure pas
(seulement les réponses en erreur et les requêtes lentes) : elle se voit dans « dernière connexion ».
"""
import json
import time

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.logging.models import APILog, ErrorLog
from apps.users.admin_dashboard import IsSuperuser
from apps.users.models import GoogleAccount
from config.throttling import LoginAccountThrottle

AUTH_PATHS = ('/api/auth/', '/api/token')
GOOGLE_PATH = '/api/auth/google/'
MAX_LOGS = 60
# Codes renvoyés par les routes d'authentification → explication pour l'administrateur.
CODE_HINT = {
    'invalid_credentials': 'Mot de passe incorrect, ou aucun compte avec cet identifiant.',
    'email_not_verified': 'Adresse e-mail pas encore confirmée : le lien de confirmation n’a pas été cliqué.',
    'account_disabled': 'Compte désactivé.',
    'consent_required': 'Connexion Google, nouveau compte : les deux cases (conditions, accord parental) '
                        'n’ont pas encore été cochées. Le compte n’existe qu’après.',
    'invalid_token': 'Connexion Google refusée par le serveur : jeton expiré ou falsifié, Client ID différent '
                     'de GOOGLE_CLIENT_ID, ou adresse non confirmée chez Google.',
    'google_unavailable': 'Connexion Google : le serveur n’a pas pu joindre Google (réseau). Réessayer.',
    'set_password_first': 'Compte créé avec Google : définir un mot de passe avant de changer d’adresse e-mail.',
}


def _throttle_state(identifiers):
    """Essais de connexion dans l'heure pour chaque identifiant (clé du LoginAccountThrottle)."""
    throttle = LoginAccountThrottle()
    now = time.time()
    out = []
    for ident in identifiers:
        key = throttle.cache_format % {'scope': throttle.scope, 'ident': ident}
        history = [t for t in (cache.get(key) or []) if t > now - throttle.duration]
        if history:
            blocked = len(history) >= throttle.num_requests
            out.append({'identifier': ident, 'attempts': len(history), 'limit': throttle.num_requests,
                        'blocked': blocked,
                        'until_minutes': round((min(history) + throttle.duration - now) / 60) if blocked else None})
    return out


def _parse(body):
    try:
        return json.loads(body) if body else None
    except (TypeError, ValueError):
        return None


def _log_row(log):
    response = _parse(log.response_body) or {}
    request = _parse(log.request_body) or {}
    code = response.get('code') if isinstance(response, dict) else None
    message = None
    if isinstance(response, dict):
        message = response.get('error') or response.get('detail')
        if not message:
            # Erreurs de formulaire (inscription) : {"email": ["…"]}
            firsts = [f'{k} : {v[0]}' for k, v in response.items() if isinstance(v, list) and v]
            message = ' · '.join(firsts) or None
    if log.status_code == 429:
        message = message or 'Trop d’essais : bloqué temporairement.'
    return {
        'at': log.timestamp.isoformat(), 'method': log.method, 'endpoint': log.endpoint,
        'status': log.status_code, 'ip': log.ip_address, 'user': log.user.username if log.user_id else None,
        # Connexion Google : pas d'identifiant dans la requête (jeton), l'adresse est dans la réponse.
        'identifier': (request.get('identifier') or request.get('email') or request.get('username')
                       if isinstance(request, dict) else None)
        or (response.get('email') if isinstance(response, dict) else None),
        'code': code, 'message': str(message)[:300] if message else None, 'hint': CODE_HINT.get(code),
    }


@api_view(['GET'])
@permission_classes([IsSuperuser])
def login_diagnostic(request):
    q = (request.query_params.get('q') or '').strip()
    if len(q) < 3:
        return Response({'detail': 'Indique au moins 3 caractères (e-mail ou nom d’utilisateur).'}, status=400)

    # Aussi le compte lié à cette adresse Google, si elle diffère de l'adresse du compte.
    users = list(User.objects.filter(Q(email__iexact=q) | Q(username__iexact=q) | Q(google_accounts__email__iexact=q))
                 .select_related('profile').distinct().order_by('id'))
    # Celui que la connexion choisit : même règle que apps/authentication/views._find_user.
    chosen = (User.objects.filter(email__iexact=q) if '@' in q else User.objects.filter(username=q)).order_by('id').first()

    google_ids = set(GoogleAccount.objects.filter(user__in=users).values_list('user_id', flat=True))
    accounts = []
    warnings = []
    for u in users:
        p = getattr(u, 'profile', None)
        verified = bool(p and p.email_verified)
        accounts.append({
            'id': u.id, 'username': u.username, 'email': u.email, 'is_active': u.is_active,
            'email_verified': verified, 'email_verified_at': p.email_verified_at.isoformat()
            if p and getattr(p, 'email_verified_at', None) else None,
            'has_password': u.has_usable_password(), 'date_joined': u.date_joined.isoformat(),
            'last_login': u.last_login.isoformat() if u.last_login else None,
            'used_for_login': chosen is not None and u.id == chosen.id,
            'google': u.id in google_ids,
        })
        if not u.is_active and not verified:
            warnings.append(f'« {u.username} » : e-mail jamais confirmé, la connexion est refusée tant que le lien '
                            'de confirmation n’a pas été cliqué (le membre peut demander un nouvel e-mail).')
        elif not u.is_active:
            warnings.append(f'« {u.username} » : compte désactivé.')
        if not u.has_usable_password():
            if u.id in google_ids:
                warnings.append(f'« {u.username} » : se connecte avec Google (aucun mot de passe) ; peut définir '
                                'un mot de passe via « Mot de passe oublié ».')
            else:
                # « Mot de passe oublié » n'envoie rien à un compte sans mot de passe ni Google.
                warnings.append(f'« {u.username} » : aucun mot de passe et pas de connexion Google — « Mot de '
                                'passe oublié » n’envoie rien ; en définir un depuis l’admin Django.')
    same_email = [u for u in users if u.email and u.email.lower() == q.lower()]
    if len(same_email) > 1:
        warnings.append(f'{len(same_email)} comptes partagent cette adresse : la connexion par e-mail prend le plus ancien '
                        f'(« {same_email[0].username} »). Se connecter avec le nom d’utilisateur pour l’autre.')
    if '@' not in q and chosen is None and users:
        warnings.append('Le nom d’utilisateur est sensible à la casse à la connexion : '
                        + ', '.join(f'« {u.username} »' for u in users) + '.')
    if not users:
        warnings.append('Aucun compte avec cet e-mail ou ce nom d’utilisateur : faute de frappe, ou inscription jamais terminée.')

    identifiers = {q.lower()} | {u.email.lower() for u in users if u.email} | {u.username.lower() for u in users}
    throttles = _throttle_state(sorted(identifiers))
    for t in throttles:
        if t['blocked']:
            warnings.append(f'Bloqué après {t["attempts"]} essais avec « {t["identifier"]} » : '
                            f'nouvel essai possible dans {t["until_minutes"]} min environ.')

    path_q = Q()
    for path in AUTH_PATHS:
        path_q |= Q(endpoint__startswith=path)
    who = Q()
    for ident in identifiers:
        who |= Q(request_body__icontains=json.dumps(ident, ensure_ascii=False)[1:-1])
        # Connexion Google refusée : l'adresse n'apparaît que dans la réponse (consentement demandé).
        who |= Q(endpoint__startswith=GOOGLE_PATH, response_body__icontains=json.dumps(ident, ensure_ascii=False)[1:-1])
    if users:
        who |= Q(user_id__in=[u.id for u in users])
    logs = APILog.objects.filter(path_q).filter(who).select_related('user').order_by('-timestamp')[:MAX_LOGS]
    errors = ErrorLog.objects.filter(user_id__in=[u.id for u in users]).order_by('-last_seen')[:20] if users else []

    return Response({
        'query': q,
        'accounts': accounts,
        'warnings': warnings,
        'throttles': throttles,
        'logs': [_log_row(log) for log in logs],
        'errors': [{'at': e.last_seen.isoformat(), 'endpoint': e.endpoint, 'message': e.message[:300],
                    'type': e.exception_type, 'count': e.count}
                   for e in errors],
    })
