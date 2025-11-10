"""
Management command to backfill TaxonomyTimeSpent from existing StudyTimeTracker data
Run with: python manage.py backfill_taxonomy_time
"""
from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from apps.interactions.models import StudyTimeTracker, TaxonomyTimeSpent, update_taxonomy_time
from datetime import timedelta


class Command(BaseCommand):
    help = 'Backfill TaxonomyTimeSpent records from existing StudyTimeTracker data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Reset all TaxonomyTimeSpent records before backfilling',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Starting taxonomy time backfill...'))

        if options['reset']:
            self.stdout.write(self.style.WARNING('Resetting all TaxonomyTimeSpent records...'))
            deleted_count, _ = TaxonomyTimeSpent.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_count} existing records'))

        # Get all StudyTimeTracker entries
        study_trackers = StudyTimeTracker.objects.select_related(
            'user', 'content_type'
        ).prefetch_related('content_object').all()

        total_count = study_trackers.count()
        self.stdout.write(f'Found {total_count} StudyTimeTracker entries to process')

        processed = 0
        skipped = 0
        errors = 0

        for tracker in study_trackers:
            try:
                if not tracker.content_object or tracker.time_spent_seconds <= 0:
                    skipped += 1
                    continue

                # Convert to timedelta
                time_delta = timedelta(seconds=tracker.time_spent_seconds)

                # Update taxonomy time
                update_taxonomy_time(tracker.user, tracker.content_object, time_delta)

                processed += 1

                if processed % 100 == 0:
                    self.stdout.write(f'Processed {processed}/{total_count}...')

            except Exception as e:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(f'Error processing tracker {tracker.id}: {str(e)}')
                )

        self.stdout.write(self.style.SUCCESS(
            f'\nBackfill complete!\n'
            f'Processed: {processed}\n'
            f'Skipped: {skipped}\n'
            f'Errors: {errors}'
        ))

        # Show summary stats
        taxonomy_count = TaxonomyTimeSpent.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f'Total TaxonomyTimeSpent records: {taxonomy_count}'
        ))
