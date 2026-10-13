"""Taxonomie et programme officiel (apps/caracteristics/programme.py).

    python manage.py programme_officiel             écarts entre la base et le programme (lecture seule)
    python manage.py programme_officiel --a-blanc   répétition à blanc de la migration caracteristics/0003 sur cette
                                                    base : migration (données figées), migrations de données
                                                    suivantes (0004 : « 2ème Bac PC » → « 2ème Bac PC/SVT ») + seeder
                                                    + vérifications, rapport imprimé, puis TOUT est annulé (rollback)

À lancer sur la base de production avec la nouvelle image AVANT le déploiement de 0003 ; lire le rapport (matières hors
Mathématiques, chapitres d'administrateurs, conflits, quiz à réaffecter).
"""
import importlib
import runpy

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor

from apps.caracteristics.programme import ecarts_base
from apps.caracteristics.programme_migration import appliquer

MIGRATION = ('caracteristics', '0003_programme_officiel')
# Migrations de données jouées ensuite, avant le seeder (comme `migrate` dans l'entrypoint) : (app, nom), fonction avant().
SUIVANTES = [('caracteristics', '0004_pc_svt')]


class Command(BaseCommand):
    help = "Écarts base / programme officiel ; --a-blanc : répétition de la migration 0003, entièrement annulée."

    def add_arguments(self, parser):
        parser.add_argument('--a-blanc', action='store_true', dest='a_blanc',
                            help='rejoue la migration 0003 et le seeder dans une transaction annulée')

    def handle(self, *args, a_blanc=False, **options):
        if not a_blanc:
            self.ecarts()
            return
        donnees = importlib.import_module('apps.caracteristics.migrations.' + MIGRATION[1]).DONNEES
        apps = MigrationExecutor(connection).loader.project_state(MIGRATION).apps
        with transaction.atomic():
            appliquer(apps, donnees, a_blanc=True, log=self.stdout.write)
            for app, nom in SUIVANTES:
                importlib.import_module(f'apps.{app}.migrations.{nom}').avant(
                    MigrationExecutor(connection).loader.project_state((app, nom)).apps, None)
            self.stdout.write('\nSeeder (tests/base_tables.py)…')
            runpy.run_path(str(settings.BASE_DIR / 'tests' / 'base_tables.py'))
            self.stdout.write('\nVérifications après migration et seeder :')
            self.ecarts()
            transaction.set_rollback(True)
        self.stdout.write(self.style.WARNING('\nRépétition à blanc : tout a été annulé, la base est inchangée.'))

    def ecarts(self):
        ecarts = ecarts_base()
        for quoi, titre in (('chapitres', 'Chapitres'), ('theoremes', 'Théorèmes')):
            if ecarts[quoi]:
                self.stdout.write(self.style.ERROR(f'{titre} : {len(ecarts[quoi])} écart(s)'))
                for e in ecarts[quoi]:
                    self.stdout.write(f'  - {e}')
            else:
                self.stdout.write(self.style.SUCCESS(f'{titre} : conformes au programme officiel'))
