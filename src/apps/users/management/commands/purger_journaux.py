"""python manage.py purger_journaux : journaux techniques plus vieux que la durée de conservation."""
from django.core.management.base import BaseCommand

from apps.users.legal import LOG_RETENTION, purge_old_logs


class Command(BaseCommand):
    help = "Supprime les journaux techniques plus anciens que la durée de conservation (RGPD)."

    def handle(self, **options):
        n = purge_old_logs()
        self.stdout.write(self.style.SUCCESS(f'{n} lignes de journaux supprimées (plus de {LOG_RETENTION.days} jours).'))
