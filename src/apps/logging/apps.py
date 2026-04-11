"""
Logging app configuration
"""
from django.apps import AppConfig


class LoggingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.logging'
    label = 'logging'
    verbose_name = 'Logging'
