from django.apps import AppConfig


class MessagerieConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.messagerie'
    verbose_name = 'Messages et appels'

    def ready(self):
        from . import signals  # noqa: F401  (un blocage fait quitter les groupes communs)
