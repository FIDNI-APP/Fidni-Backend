from django.apps import AppConfig


class CommunauteConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.communaute'
    verbose_name = 'Communauté'

    def ready(self):
        from . import signals  # noqa: F401  (badges recalculés après les actions qui les font bouger)
