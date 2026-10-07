"""Exécute un travail de l'IA (lancé en arrière-plan par Pilotage › IA)."""
from django.core.management.base import BaseCommand

from apps.ia import pipeline


class Command(BaseCommand):
    help = "Traite un travail de l'IA (import d'un document ou correction d'un signalement)."

    def add_arguments(self, parser):
        parser.add_argument('job_id', type=int)

    def handle(self, job_id, **options):
        pipeline.traiter(job_id)
