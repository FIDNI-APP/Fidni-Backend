"""Rejette des brouillons de Pilotage › À valider (comme le bouton « Rejeter ») : doublons repérés à l'import, etc.
Rien n'est effacé : le brouillon passe dans l'onglet « Rejetés », avec le motif dans son historique."""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.ia.models import IAJob


class Command(BaseCommand):
    help = "Rejette un ou plusieurs brouillons (n° de Pilotage › À valider) : ia_rejeter 291 299 --motif \"doublon de 308\"."

    def add_arguments(self, parser):
        parser.add_argument('ids', nargs='+', type=int)
        parser.add_argument('--motif', default='Rejeté par Claude')

    def handle(self, ids, motif, **options):
        for pk in ids:
            job = IAJob.objects.filter(pk=pk).first()
            if job is None:
                raise CommandError(f'brouillon {pk} introuvable')
            if job.status not in (IAJob.PRET, IAJob.ERREUR):
                self.stdout.write(f'{pk} : déjà {job.get_status_display().lower()}, rien à faire')
                continue
            job.status = IAJob.REJETE
            job.history.append({'date': timezone.now().isoformat(), 'qui': 'claude', 'texte': f'Rejeté : {motif}'})
            job.save()
            job.files.all().delete()  # comme le bouton : le document n'est plus utile
            self.stdout.write(f'{pk} : rejeté ({motif})')
