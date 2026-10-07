"""
Base settings shared across all environments
"""
from pathlib import Path
import os
from datetime import timedelta
from dotenv import load_dotenv
import environ

# Initialize environment variables (single .env at the backend root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(BASE_DIR / '.env')

# Initialize environ for environment variable parsing (used in prod.py)
env = environ.Env()
env.read_env(BASE_DIR / '.env')

DEBUG = os.getenv('DEBUG', 'False') == 'True'
SECRET_KEY = os.getenv('SECRET_KEY', 'gr-5s4^9^nz%*1)843r*7)+xrk!zc3==nm#zgroldi0*x#y+8e')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*').split(',')

OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'o4-mini')
OPENAI_MAX_TOKENS = os.getenv('OPENAI_MAX_TOKENS', 4096)
OPENAI_TEMPERATURE = os.getenv('OPENAI_TEMPERATURE', 0.7)

# File upload limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB

# Apps
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    # Déconnexion et changement de mot de passe révoquent les jetons de rafraîchissement.
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'storages',
    'apps.things.apps.ThingsConfig',
    'apps.users.apps.UsersConfig',
    'apps.authentication.apps.AuthenticationConfig',
    'apps.caracteristics.apps.CaracteristicsConfig',
    'apps.interactions.apps.InteractionsConfig',
    'apps.notebooks.apps.NotebooksConfig',
    'apps.learningpath.apps.LearningpathConfig',
    'apps.logging.apps.LoggingConfig',
    'apps.skilliq.apps.SkilliqConfig',
    'apps.uploads.apps.UploadsConfig',
    'apps.classrooms.apps.ClassroomsConfig',
    'apps.concours.apps.ConcoursConfig',
    'apps.ia.apps.IaConfig',
    'apps.notifications.apps.NotificationsConfig',
]

MIDDLEWARE = [
    'config.middleware.HealthCheckMiddleware',  # /healthz — avant la validation du Host
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    # Protège les formulaires à session (admin Django). L'API n'est pas concernée : ses vues
    # DRF sont exemptées et s'authentifient par jeton JWT, pas par cookie.
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.logging.middleware.ErrorTrackingMiddleware',
    'apps.logging.middleware.APILoggingMiddleware',
]

CORS_ALLOW_HEADERS = [
    'accept', 'accept-encoding', 'authorization', 'content-type',
    'dnt', 'origin', 'user-agent', 'x-csrftoken', 'x-requested-with',
]

CORS_ALLOW_METHODS = ['DELETE', 'GET', 'OPTIONS', 'PATCH', 'POST', 'PUT']

CORS_ALLOWED_ORIGINS = [
    'https://fidni.fr',
    'https://api.fidni.fr',
    'http://localhost:3000',
    'http://localhost:5173',
]

CORS_ALLOW_CREDENTIALS = True
# Pas de CORS_ALLOW_ALL_ORIGINS ici : combiné aux credentials, il laissait n'importe quel
# site appeler l'API au nom du visiteur. Seul dev.py l'active, pour le travail en local.


ROOT_URLCONF = 'src.config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'src.config.wsgi.application'

DB_ENGINE = os.getenv('DB_ENGINE', 'sqlite')

if DB_ENGINE == 'postgresql':
    # DB_PASSWORD wins; otherwise fetch it from AWS Secrets Manager.
    password = os.getenv('DB_PASSWORD', '')
    arn = os.getenv('AWS_DB_SECRET_ARN', '')
    if not password and arn:
        import json
        import boto3
        region = os.getenv('AWS_REGION') or arn.split(':')[3]
        secret = boto3.client('secretsmanager', region_name=region).get_secret_value(SecretId=arn)
        password = json.loads(secret['SecretString'])['password']

    options = {
        'connect_timeout': 10,
        'options': '-c statement_timeout=30000 -c idle_in_transaction_session_timeout=60000',
        'sslmode': os.getenv('DB_SSLMODE', 'require'),
        # La box coupe en silence les connexions TCP inactives vers RDS : sans ces
        # « keepalives », la requête suivante tombait sur « server closed the connection ».
        'keepalives': 1,
        'keepalives_idle': 60,
        'keepalives_interval': 15,
        'keepalives_count': 4,
    }
    if os.getenv('DB_SSLROOTCERT'):
        options['sslrootcert'] = str(BASE_DIR / os.getenv('DB_SSLROOTCERT'))

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'fidni'),
            'USER': os.getenv('DB_USER', 'postgres'),
            'PASSWORD': password,
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
            'CONN_MAX_AGE': 600,
            # Vérifie qu'une connexion réutilisée est encore vivante (sinon, en rouvre une).
            'CONN_HEALTH_CHECKS': True,
            'OPTIONS': options,
        }
    }
else:
    # SQLite - use /app/data for Docker volume persistence
    sqlite_path = os.getenv('SQLITE_PATH', str(BASE_DIR / 'fidni_sqlite_data/db.sqlite3'))
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': sqlite_path,
        }
    }

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Stockages (réglage STORAGES : DEFAULT_FILE_STORAGE a été supprimé dans Django 5.1, et un
# fichier envoyé serait alors resté sur le disque du conteneur au lieu d'aller sur S3).
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# AWS S3 Configuration (optional - uses local storage if not enabled)
AWS_STORAGE_ENABLED = os.getenv('AWS_STORAGE_ENABLED', 'false').lower() == 'true'
if AWS_STORAGE_ENABLED:
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = os.getenv('AWS_S3_REGION_NAME', 'eu-west-1')
    # Regional endpoint — the global one 307-redirects (breaks presigned signatures)
    AWS_S3_ENDPOINT_URL = f'https://s3.{AWS_S3_REGION_NAME}.amazonaws.com'
    AWS_S3_CUSTOM_DOMAIN = os.getenv('AWS_S3_CUSTOM_DOMAIN', None)
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    AWS_S3_OBJECT_PARAMETERS = {
        'CacheControl': 'max-age=86400',
    }
    STORAGES['default'] = {'BACKEND': 'apps.uploads.storage.MediaStorage'}
    if AWS_S3_CUSTOM_DOMAIN:
        MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'
    else:
        MEDIA_URL = f'https://{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com/media/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Parcours (en cours de construction) : masqué à tous sauf au staff tant que ce n'est pas True.
PARCOURS_PUBLIC = os.getenv('PARCOURS_PUBLIC', 'False') == 'True'


# ── Email (defaults) ───────────────────────────────────────────────────────
# Dev prints emails to the console; prod.py overrides with a real SMTP backend.
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Fidni <no-reply@fidni.fr>')
# Read by config.email_backends.BrevoAPIEmailBackend; prod.py selects that
# backend automatically when the key is present.
BREVO_API_KEY = os.getenv('BREVO_API_KEY', '')
BREVO_TIMEOUT = int(os.getenv('BREVO_TIMEOUT', '10'))
# Public URL of the SPA — used to build links inside verification emails.
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')

# IndexNow (config/indexnow.py) : clé publique, dont le fichier est frontend/public/<clé>.txt. Actif en production.
INDEXNOW_KEY = os.getenv('INDEXNOW_KEY', '93ee34525bd85504f81a723d63fca280')
INDEXNOW_ENABLED = False

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'INFO'},
        # Pillow détaille chaque bloc d'image lu (« STREAM b'IHDR' … ») : bruit inutile.
        'PIL': {'level': 'WARNING'},
    },
}

# OpenAI Configuration for AI Correction
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4-vision-preview')
OPENAI_MAX_TOKENS = int(os.getenv('OPENAI_MAX_TOKENS', '4096'))
OPENAI_TEMPERATURE = float(os.getenv('OPENAI_TEMPERATURE', '0.7'))

# IA des administrateurs (Pilotage › IA) : import de documents, correction des signalements.
# La clé vit dans le fichier d'environnement du serveur (/opt/fidni/secrets), jamais dans le dépôt.
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
ANTHROPIC_WORKSPACE_ID = os.getenv('ANTHROPIC_WORKSPACE_ID', '')
ANTHROPIC_MODEL = os.getenv('ANTHROPIC_MODEL', 'claude-opus-5-5')
ANTHROPIC_MAX_TOKENS = int(os.getenv('ANTHROPIC_MAX_TOKENS', '64000'))
ANTHROPIC_THINKING = int(os.getenv('ANTHROPIC_THINKING', '16000'))
IA_LANCEMENT = os.getenv('IA_LANCEMENT', 'processus')  # « aucun » : tests (traitement appelé directement)

# Lien « mot de passe oublié » : valable 2 h, et une seule fois (voir authentication/emails.py).
PASSWORD_RESET_TIMEOUT = 2 * 60 * 60

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Par défaut : lecture pour tous, écriture pour les utilisateurs connectés. Une vue
    # qui doit accepter une écriture anonyme (inscription, suivi d'audience…) le déclare.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "auth": "40/min",           # connexion, inscription (par IP : une classe entière passe)
        "login_account": "15/hour", # essais de connexion sur un même compte
        "token_refresh": "60/min",  # renouvellement silencieux des jetons (par IP)
        "auth_email": "5/hour",     # renvoi de confirmation, mot de passe oublié (par IP)
        "pdf_parse": "20/hour",     # analyse de PDF (coûteuse, par utilisateur)
        "classroom_join": "30/hour",  # essais de code de classe (par utilisateur)
        "proposed_solution": "20/hour",  # solutions d'élèves publiées (par utilisateur)
        "content_report": "20/hour",  # signalements d'erreurs sur les contenus (par utilisateur)
    },
    "UNAUTHENTICATED_USER": None
}

SIMPLE_JWT = {
    # Jeton d'accès court (volé, il ne sert pas longtemps), renouvelé en silence par le
    # front avec le jeton de rafraîchissement : l'élève reste connecté deux semaines.
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
}
