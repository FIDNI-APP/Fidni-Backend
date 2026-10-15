"""Travaux de l'IA sur les copies (lancés en arrière-plan par Classes › Évaluations ; --reprendre : tâche planifiée)."""
from django.core.management.base import BaseCommand, CommandError

from apps.copies import traitement


class Command(BaseCommand):
    help = 'Corrige les copies d’une évaluation, découpe un PDF de classe ou lit un sujet privé.'

    def add_arguments(self, parser):
        parser.add_argument('sorte', nargs='?', choices=['evaluation', 'lot', 'sujet'])
        parser.add_argument('ident', nargs='?', type=int)
        parser.add_argument('--reprendre', action='store_true',
                            help='Remet en file les travaux interrompus et relance ce qui attend.')

    def handle(self, sorte=None, ident=None, reprendre=False, **options):
        if reprendre:
            traitement.reprendre()
            return
        if not sorte or not ident:
            raise CommandError('Préciser : evaluation|lot|sujet <id>, ou --reprendre.')
        {'evaluation': traitement.traiter_evaluation, 'lot': traitement.traiter_lot,
         'sujet': traitement.traiter_sujet}[sorte](ident)
