"""python manage.py purger_comptes_inactifs [--appliquer]

Comptes sans connexion depuis 3 ans (politique de confidentialité) : supprimés comme une
suppression demandée par l'utilisateur (contributions gardées sous « Compte supprimé »).
Sans --appliquer, affiche seulement la liste. À planifier (cron) sur le serveur de production.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.things.importing import EDITORIAL_USERNAME
from apps.users.account_deletion import DELETED_USERNAME, delete_account
from apps.users.legal import INACTIVE_ACCOUNT_RETENTION


class Command(BaseCommand):
    help = "Supprime les comptes inactifs depuis plus de 3 ans (sauf administrateurs)."

    def add_arguments(self, parser):
        parser.add_argument('--appliquer', action='store_true', help='Supprimer réellement (sinon, simulation).')

    def handle(self, appliquer, **options):
        cutoff = timezone.now() - INACTIVE_ACCOUNT_RETENTION
        # Le compte éditorial ne se connecte jamais : il porte les contenus importés.
        qs = (User.objects.exclude(username__in=[DELETED_USERNAME, EDITORIAL_USERNAME]).filter(is_staff=False, is_superuser=False)
              .filter(Q(last_login__lt=cutoff) | Q(last_login__isnull=True, date_joined__lt=cutoff)))
        names = list(qs.values_list('username', flat=True))
        if not appliquer:
            self.stdout.write(f'{len(names)} compte(s) inactif(s) : {", ".join(names) or "aucun"} (simulation).')
            return
        for user in qs:
            delete_account(user, keep_contributions=True)
        self.stdout.write(self.style.SUCCESS(f'{len(names)} compte(s) inactif(s) supprimé(s).'))
