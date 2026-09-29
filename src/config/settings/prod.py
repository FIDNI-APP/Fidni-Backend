"""Production settings"""
from .base import *

DEBUG = False

# Obligatoire en production : la valeur de repli de base.py est publique (dépôt GitHub).
SECRET_KEY = env('SECRET_KEY')

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')

# Security settings
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=False)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# L'interface navigable de DRF expose formulaires et détails internes : JSON seulement.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    'DEFAULT_RENDERER_CLASSES': ('rest_framework.renderers.JSONRenderer',),
}

# Database config lives in base.py (env-driven: DB_ENGINE, DB_HOST, ...).

# CORS — liste explicite uniquement
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])
CORS_ALLOW_CREDENTIALS = True

# CSRF
# Add any domains that are allowed in the Origin header for safe POST requests.
# NOTE: Include the scheme (e.g., https://api.fidni.fr) as required by Django
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=['https://api.fidni.fr'])

# ── Reverse proxy / Cloudflare Tunnel ──────────────────────────────────────
# The tunnel (and any proxy) forwards requests to the container over plain HTTP
# while the public connection is HTTPS. Trust the forwarded-proto header so
# Django recognises requests as secure — otherwise SECURE_SSL_REDIRECT loops
# forever and Secure cookies are never set.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# ── Email (SMTP) ───────────────────────────────────────────────────────────
# Provider-agnostic: point these at Brevo / Resend / Mailgun / SES via env.
# Used for account email verification and password resets.
# Defaults to real SMTP; set EMAIL_BACKEND=...console.EmailBackend to test
# without a provider (emails print to the container logs).
#
# Set BREVO_API_KEY to send over Brevo's HTTP API instead of its SMTP relay.
# The relay authorises by source IP and answers `525 Unauthorized IP address`
# from any host that is not on the allow-list; the API does not care where the
# request comes from. An explicit EMAIL_BACKEND in the environment still wins.
BREVO_API_KEY = env('BREVO_API_KEY', default='')
_default_email_backend = (
    'config.email_backends.BrevoAPIEmailBackend' if BREVO_API_KEY
    else 'django.core.mail.backends.smtp.EmailBackend'
)

EMAIL_BACKEND = env('EMAIL_BACKEND', default=_default_email_backend)
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='Fidni <no-reply@fidni.fr>')

# Public URL of the SPA — used to build links inside verification emails.
FRONTEND_URL = env('FRONTEND_URL', default='https://fidni.fr')

# Logging — console only; docker captures stdout (`docker compose logs`)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
