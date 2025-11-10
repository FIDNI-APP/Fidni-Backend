"""
Base settings shared across all environments
"""
from json import load
from pathlib import Path
import os
from datetime import timedelta
from dotenv import load_dotenv 

# Initialize environment variables
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(BASE_DIR / 'src/config/.env')
DEBUG = os.getenv('DEBUG', 'False') == 'True'
SECRET_KEY = os.getenv('SECRET_KEY', 'gr-5s4^9^nz%*1)843r*7)+xrk!zc3==nm#zgroldi0*x#y+8e')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*').split(',')
SECRET_KEY = os.getenv('SECRET_KEY', 'your-default-secret-key')


# Apps
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'apps.things.apps.ThingsConfig',
    'apps.users.apps.UsersConfig',
    'apps.authentication.apps.AuthenticationConfig',
    'apps.caracteristics.apps.CaracteristicsConfig',
    'apps.interactions.apps.InteractionsConfig',
    'apps.notebooks.apps.NotebooksConfig',
    'apps.learningpath.apps.LearningpathConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
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

# Temporary - allow all origins for debugging
CORS_ALLOW_ALL_ORIGINS = True


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
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'fidni'),
            'USER': os.getenv('DB_USER', 'postgres'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
            'CONN_MAX_AGE': 600,
            'OPTIONS': {
                'connect_timeout': 10,
                'options': '-c statement_timeout=30000 -c idle_in_transaction_session_timeout=60000'
            }
        }
    }
else:
    # SQLite - use /app/data for Docker volume persistence
    sqlite_path = os.getenv('SQLITE_PATH', str(BASE_DIR / 'db.sqlite3'))
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

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "UNAUTHENTICATED_USER": None
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=1000),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
}
