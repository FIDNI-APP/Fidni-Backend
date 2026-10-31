"""Importe des questions de quiz (fichiers JSON) en brouillon « à relire » : skilliq/constats.py, importer.

Sans argument : tous les fichiers de apps/skilliq/quiz/ (rédigés par Claude d'après les résultats des élèves).
Rejouable : une question déjà présente (même texte, même quiz) est ignorée. « "type": "approfondissement" » dans un
fichier : ses questions vont au second quiz du chapitre.
"""
import glob
import json
import os

from django.core.management.base import BaseCommand, CommandError

from apps.skilliq.constats import importer
from apps.skilliq.models import APPROFONDISSEMENT

DOSSIER = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'quiz')


class Command(BaseCommand):
    help = "Importe des QCM en brouillon « à relire » (invisibles des élèves avant validation dans Pilotage › Quiz)."

    def add_arguments(self, parser):
        parser.add_argument('fichiers', nargs='*', help=f'Fichiers JSON (par défaut : {DOSSIER}/*.json)')
        parser.add_argument('--simulation', action='store_true', help='Contrôler sans rien écrire')

    def handle(self, fichiers, simulation=False, **options):
        fichiers = fichiers or sorted(glob.glob(os.path.join(DOSSIER, '*.json')))
        if not fichiers:
            raise CommandError('Aucun fichier à importer.')
        total = 0
        for chemin in fichiers:
            try:
                with open(chemin, encoding='utf-8') as f:
                    bilan = importer(json.load(f), simulation=simulation)
            except (OSError, ValueError) as exc:
                raise CommandError(f'{chemin} : {exc}')
            self.stdout.write(f'== {os.path.basename(chemin)}')
            for ligne in bilan:
                total += ligne['creees']
                quoi = ' — approfondissement' if ligne['type'] == APPROFONDISSEMENT else ''
                self.stdout.write(f"{ligne['chapitre']} ({ligne['niveau']}){quoi} : {ligne['creees']} question(s)"
                                  + (' (simulation)' if simulation else ''))
                for e in ligne['ecartees']:
                    self.stdout.write(f"   écartée : {e['question']} — {e['raison']}")
        self.stdout.write(f'{total} question(s) {"à importer" if simulation else "importées, à relire dans Pilotage › Quiz"}.')
