"""Connexion avec Google (Google Identity Services, 10/10/2026).

Le front reçoit de Google un jeton d'identité (JWT signé RS256) et nous l'envoie. On vérifie ici sa
signature avec les clés publiques de Google, son audience (notre Client ID public), son émetteur, son
expiration et que l'adresse e-mail est confirmée chez Google. Le code secret OAuth n'est ni utilisé
ni stocké : ce flux n'en a pas besoin.

`verify_google_credential` est la seule porte vers Google : les tests la remplacent par une fonction
factice (ou remplacent `_jwks_client` par un faux client qui renvoie leur propre clé publique).
"""
import jwt
from django.conf import settings

GOOGLE_CERTS_URL = 'https://www.googleapis.com/oauth2/v3/certs'
GOOGLE_ISSUERS = ('accounts.google.com', 'https://accounts.google.com')
MAX_TOKEN_LENGTH = 4096  # un jeton Google fait ~1 200 caractères

# Clés publiques de Google, gardées en mémoire (une heure) par processus : une requête vers Google
# seulement au démarrage, à l'expiration du cache ou quand Google change de clé (kid inconnu).
_jwks_client = None


class GoogleTokenError(Exception):
    """Jeton refusé : mal formé, signature, audience, émetteur, expiration ou e-mail non confirmé."""


class GoogleUnavailable(Exception):
    """Clés publiques de Google injoignables (réseau) : ce n'est pas la faute du jeton."""


def _jwks():
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(GOOGLE_CERTS_URL, cache_keys=True, lifespan=3600, timeout=5)
    return _jwks_client


def verify_google_credential(token):
    """Jeton d'identité Google → {sub, email, given_name, family_name, name}. Lève GoogleTokenError
    (jeton refusé) ou GoogleUnavailable (Google injoignable)."""
    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '')
    if not client_id:
        raise GoogleTokenError('GOOGLE_CLIENT_ID non configuré.')
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_LENGTH:
        raise GoogleTokenError('Jeton absent ou mal formé.')
    try:
        signing_key = _jwks().get_signing_key_from_jwt(token)
    except jwt.PyJWKClientConnectionError as e:
        raise GoogleUnavailable(str(e)) from e
    except jwt.PyJWTError as e:  # kid inconnu, en-tête illisible…
        raise GoogleTokenError(str(e)) from e
    try:
        claims = jwt.decode(
            token, signing_key.key, algorithms=['RS256'], audience=client_id, issuer=GOOGLE_ISSUERS,
            options={'require': ['exp', 'iat', 'iss', 'aud', 'sub']},
            leeway=60,  # horloge du serveur légèrement décalée
        )
    except jwt.PyJWTError as e:
        raise GoogleTokenError(str(e)) from e

    email = str(claims.get('email') or '').strip().lower()
    # Google envoie un booléen ; d'anciens jetons portaient la chaîne « true ».
    if not email or claims.get('email_verified') not in (True, 'true'):
        raise GoogleTokenError('Adresse e-mail absente ou non confirmée chez Google.')
    sub = str(claims.get('sub') or '').strip()
    if not sub:
        raise GoogleTokenError('Identifiant Google absent.')
    return {
        'sub': sub,
        'email': email,
        'given_name': str(claims.get('given_name') or '').strip(),
        'family_name': str(claims.get('family_name') or '').strip(),
        'name': str(claims.get('name') or '').strip(),
    }
