"""
Things app configuration
"""
from django.apps import AppConfig


class ThingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.things'
    label = 'things'
    verbose_name = 'Things'

    def ready(self):
        import apps.things.signals  # noqa: F401
