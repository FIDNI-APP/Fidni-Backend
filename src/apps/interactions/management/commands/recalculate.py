# management/commands/recalculate_taxonomy_time.py

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction
from datetime import timedelta
from apps.interactions.models import StudyTimeTracker, TaxonomyTimeSpent, update_taxonomy_time
import time


class Command(BaseCommand):
    help = 'Recalcule les temps par taxonomie à partir des StudyTimeTracker'

    def handle(self, *args, **options):
        # Test connection first
        max_retries = 3
        for attempt in range(max_retries):
            try:
                connection.ensure_connection()
                self.stdout.write(self.style.SUCCESS('✓ Connexion DB établie'))
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    self.stdout.write(self.style.WARNING(f'Tentative {attempt + 1}/{max_retries} échouée: {e}'))
                    time.sleep(2)
                else:
                    self.stdout.write(self.style.ERROR(f'Impossible de se connecter à la DB: {e}'))
                    return

        self.stdout.write('Suppression des anciennes données TaxonomyTimeSpent...')

        # Supprimer toutes les données existantes avec transaction
        try:
            with transaction.atomic():
                deleted_count = TaxonomyTimeSpent.objects.all().delete()[0]
                self.stdout.write(f'Supprimé {deleted_count} entrées')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Erreur lors de la suppression: {e}'))
            return

        # Recalculer à partir de StudyTimeTracker avec batching
        try:
            total = StudyTimeTracker.objects.count()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Erreur comptage: {e}'))
            return

        self.stdout.write(f'Recalcul de {total} entrées StudyTimeTracker...')

        processed = 0
        errors = 0
        batch_size = 100

        # Process in batches to avoid memory issues
        for offset in range(0, total, batch_size):
            try:
                batch = StudyTimeTracker.objects.select_related('content_type')[offset:offset + batch_size]

                for tracker in batch:
                    try:
                        if tracker.time_spent_seconds > 0 and tracker.content_object:
                            time_delta = timedelta(seconds=tracker.time_spent_seconds)
                            update_taxonomy_time(tracker.user, tracker.content_object, time_delta)
                        processed += 1

                        if processed % 100 == 0:
                            self.stdout.write(f'Traité {processed}/{total}...')

                    except Exception as e:
                        errors += 1
                        self.stdout.write(self.style.WARNING(f'Erreur tracker {tracker.id}: {str(e)}'))

                # Reconnect every batch to prevent timeout
                connection.close()

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Erreur batch {offset}-{offset+batch_size}: {e}'))
                errors += batch_size
                continue

        self.stdout.write(self.style.SUCCESS(
            f'Terminé ! {processed} entrées traitées, {errors} erreurs'
        ))

        # Afficher les totaux
        try:
            new_count = TaxonomyTimeSpent.objects.count()
            self.stdout.write(f'Nouvelles entrées TaxonomyTimeSpent: {new_count}')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Impossible de compter résultats: {e}'))