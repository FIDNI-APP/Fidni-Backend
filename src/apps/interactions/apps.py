"""
Interactions app configuration
"""
from django.apps import AppConfig


class InteractionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.interactions'
    label = 'interactions'
    verbose_name = 'Interactions'

    def ready(self):
        """Import signals when app is ready"""
        import apps.interactions.signals  # noqa
