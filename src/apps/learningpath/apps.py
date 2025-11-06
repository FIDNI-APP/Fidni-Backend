"""
LearningPath app configuration
"""
from django.apps import AppConfig


class LearningpathConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.learningpath'
    label = 'learningpath'
    verbose_name = 'LearningPath'
