from django.apps import AppConfig


class CopiesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.copies'
    label = 'copies'
    verbose_name = 'Copies des élèves (correction assistée)'
