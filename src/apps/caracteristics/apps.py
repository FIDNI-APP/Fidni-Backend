"""
Caracteristics app configuration
"""
from django.apps import AppConfig


class CaracteristicsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.caracteristics'
    label = 'caracteristics'
    verbose_name = 'Caracteristics'
