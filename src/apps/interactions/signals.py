from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import StudyTimeTracker, update_taxonomy_time
from datetime import timedelta


@receiver(post_save, sender=StudyTimeTracker)
def aggregate_taxonomy_time_from_study_tracker(sender, instance, created, **kwargs):
    """
    Signal to aggregate time to taxonomies when StudyTimeTracker is saved
    StudyTimeTracker stores individual time entries, so we add each entry
    """
    if not created:
        # Only process new entries, not updates
        return

    if instance.time_spent_seconds <= 0:
        return

    # Convert seconds to timedelta
    time_delta = timedelta(seconds=instance.time_spent_seconds)

    if instance.content_object and instance.user:
        update_taxonomy_time(instance.user, instance.content_object, time_delta)
