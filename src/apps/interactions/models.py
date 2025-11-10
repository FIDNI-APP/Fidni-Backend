from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from datetime import timedelta
from django.utils import timezone
import logging

logger = logging.getLogger('django')
    
#----------------------------VOTE-------------------------------
class Vote(models.Model):
    UP = 1
    DOWN = -1
    UNVOTE = 0

    VOTE_CHOICES = [
        (UP, 'Upvote'),
        (DOWN, 'Downvote'),
        (UNVOTE, 'Unvote'),
    ]

    user = models.ForeignKey(User, on_delete=models.PROTECT)
    value = models.SmallIntegerField(choices=VOTE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        app_label = 'interactions'
        unique_together = ('user', 'content_type', 'object_id')
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
        ]

class VotableMixin(models.Model):
    votes = GenericRelation(Vote)

    class Meta:
        app_label = 'interactions'
        abstract = True

    @property
    def vote_count(self):
        return self.votes.filter(value=Vote.UP).count() - self.votes.filter(value=Vote.DOWN).count()
    

#----------------------------SAVE-------------------------------

class Save(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_exercises')
    saved_at = models.DateTimeField(auto_now_add=True)

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        app_label = 'interactions'
        unique_together = ('user', 'content_type', 'object_id')
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f"{self.user.username} saved {self.content_object.title}"
    
class SaveableMixin(models.Model):
    saved = GenericRelation(Save)

    class Meta:
        app_label = 'interactions'
        abstract = True

    @property
    def is_saved(self):
        return self.saved.exists()
    


#----------------------------EXERCISE PROGRESS-------------------------------
class Complete(models.Model):
    PROGRESS_CHOICES = [
        ('success', 'success'),
        ('review', 'review'),
        # ('in_progress', 'in_progress'),
        # ('not_started', 'not_started'),
        # ('failed', 'failed'),
        # ('abandoned', 'abandoned'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='exercise_progress')
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    status = models.CharField(max_length=10, choices=PROGRESS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        app_label = 'interactions'
        unique_together = ('user', 'content_type', 'object_id')
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.content_object.title}: {self.get_status_display()}"
    
class CompleteableMixin(SaveableMixin,VotableMixin):
    completed = GenericRelation('interactions.Complete')

    class Meta:
        app_label = 'interactions'
        abstract = True

    @property
    def is_completed(self):
        return self.completed.exists()
    


#----------------------------REPORT-------------------------------

class Report(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'interactions'
        unique_together = ('user', 'content_type', 'object_id')
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f"Report by {self.user.username} on {self.content_object}"
    

#----------------------------PERCEIVED DIFFICULTY-------------------------------
class Evaluate(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='difficulty_ratings')
    rating = models.PositiveSmallIntegerField(choices=[(i, i) for i in range(1, 6)])  # Échelle de 1 à 5
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    class Meta:
        app_label = 'interactions'
        unique_together = ('user', 'content_type', 'object_id')
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f"{self.user.username} rated {self.content_object.title} as {self.rating}/5"
    
#----------------------------TIME SPENT-------------------------------

class TimeSession(models.Model):
    """
    Enregistre chaque session de travail sur un contenu spécifique
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='time_sessions')
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Temps de cette session spécifique
    session_duration = models.DurationField()
    
    # Métadonnées de la session
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Optionnel : type de session pour analytics
    session_type = models.CharField(max_length=20, choices=[
        ('study', 'Étude'),
        ('review', 'Révision'),
        ('practice', 'Pratique'),
        ('exam', 'Examen'),
    ], default='study')
    
    # Notes optionnelles de l'utilisateur sur cette session
    notes = models.TextField(blank=True)
    
    class Meta:
        app_label = 'interactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'content_type', 'object_id']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.session_duration} on {self.content_object}"

    @property
    def session_duration_in_seconds(self):
        """Convert session_duration DurationField to seconds for easy calculations"""
        return int(self.session_duration.total_seconds()) if self.session_duration else 0


#----------------------------STUDY TIME TRACKER-------------------------------

class StudyTimeTracker(models.Model):
    """
    Track total study time automatically when users view content pages
    One entry per user+content combination (accumulated time)
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='study_time_entries')
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    # Total accumulated time in seconds
    time_spent_seconds = models.PositiveIntegerField(default=0)

    # When this entry was last updated
    recorded_at = models.DateTimeField(auto_now=True)  # Changed to auto_now for updates

    class Meta:
        app_label = 'interactions'
        ordering = ['-recorded_at']
        unique_together = ('user', 'content_type', 'object_id')  # ONE entry per user+content
        indexes = [
            models.Index(fields=['user', 'content_type', 'object_id']),
            models.Index(fields=['recorded_at']),
            models.Index(fields=['user', 'recorded_at']),  # For study stats queries
            models.Index(fields=['user', 'content_type']),  # For content type filtering
        ]

    def __str__(self):
        return f"{self.user.username} - {self.time_spent_seconds}s on {self.content_object}"





class TaxonomyTimeSpent(models.Model):
    """
    Tracks time spent aggregated by taxonomy (subject, subfield, chapter, theorem)
    Updated in real-time when content time is tracked
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='taxonomy_time_spent')

    # Taxonomy type: 'subject', 'subfield', 'chapter', 'theorem'
    taxonomy_type = models.CharField(max_length=20)

    # Generic foreign key to the taxonomy object
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    taxonomy_object = GenericForeignKey('content_type', 'object_id')

    # Aggregated time spent
    total_time = models.DurationField(default=timedelta(0))

    # Time breakdown by content type
    exercise_time = models.DurationField(default=timedelta(0))
    lesson_time = models.DurationField(default=timedelta(0))
    exam_time = models.DurationField(default=timedelta(0))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'interactions'
        unique_together = ('user', 'taxonomy_type', 'content_type', 'object_id')
        indexes = [
            models.Index(fields=['user', 'taxonomy_type']),
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.taxonomy_type} ({self.taxonomy_object}): {self.total_time}"

    @property
    def total_time_in_seconds(self):
        """Return total time in seconds"""
        if self.total_time:
            return int(self.total_time.total_seconds())
        return 0


def update_taxonomy_time(user, content_object, time_delta):
    """
    Helper function to aggregate time to all related taxonomies
    Called when TimeSpent is updated

    Args:
        user: User object
        content_object: The content object (exercise, lesson, exam)
        time_delta: timedelta object representing time to add
    """
    if time_delta.total_seconds() <= 0:
        return

    taxonomies_to_update = []

    # Determine content type name for breakdown
    content_type_name = content_object.__class__.__name__.lower()

    # Get content type models
    from django.apps import apps
    Subject = apps.get_model('caracteristics', 'Subject')
    Subfield = apps.get_model('caracteristics', 'Subfield')
    Chapter = apps.get_model('caracteristics', 'Chapter')
    Theorem = apps.get_model('caracteristics', 'Theorem')

    # Extract taxonomies from content object
    if hasattr(content_object, 'subject') and content_object.subject:
        taxonomies_to_update.append({
            'type': 'subject',
            'content_type': ContentType.objects.get_for_model(Subject),
            'object_id': content_object.subject.id
        })

    if hasattr(content_object, 'subfields'):
        for subfield in content_object.subfields.all():
            taxonomies_to_update.append({
                'type': 'subfield',
                'content_type': ContentType.objects.get_for_model(Subfield),
                'object_id': subfield.id
            })

    if hasattr(content_object, 'chapters'):
        for chapter in content_object.chapters.all():
            taxonomies_to_update.append({
                'type': 'chapter',
                'content_type': ContentType.objects.get_for_model(Chapter),
                'object_id': chapter.id
            })

    if hasattr(content_object, 'theorems'):
        for theorem in content_object.theorems.all():
            taxonomies_to_update.append({
                'type': 'theorem',
                'content_type': ContentType.objects.get_for_model(Theorem),
                'object_id': theorem.id
            })

    # Update or create TaxonomyTimeSpent records
    for taxonomy in taxonomies_to_update:
        taxonomy_time, created = TaxonomyTimeSpent.objects.get_or_create(
            user=user,
            taxonomy_type=taxonomy['type'],
            content_type=taxonomy['content_type'],
            object_id=taxonomy['object_id'],
            defaults={
                'total_time': timedelta(0),
                'exercise_time': timedelta(0),
                'lesson_time': timedelta(0),
                'exam_time': timedelta(0)
            }
        )
        taxonomy_time.total_time += time_delta

        # Update specific content type time
        if content_type_name == 'exercise':
            taxonomy_time.exercise_time += time_delta
        elif content_type_name == 'lesson':
            taxonomy_time.lesson_time += time_delta
        elif content_type_name == 'exam':
            taxonomy_time.exam_time += time_delta

        taxonomy_time.save()




#----------------------------SOLUTION VIEW TRACKING-------------------------------

class SolutionView(models.Model):
    """
    Tracks when a user views the solution for an exercise or exam.
    Used to calculate statistics and determine if solution was viewed before completion.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='solution_views')
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    # When was the solution viewed
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'interactions'
        unique_together = ('user', 'content_type', 'object_id')
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f"{self.user.username} viewed solution for {self.content_object}"


#----------------------------SOLUTION MATCH TRACKING-------------------------------

class SolutionMatch(models.Model):
    """
    Tracks when a user confirms that their solution matches the proposed solution.
    Used to calculate what percentage of users have matching solutions.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='solution_matches')
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    # When was the match confirmed
    matched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'interactions'
        unique_together = ('user', 'content_type', 'object_id')
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f"{self.user.username} solution matches {self.content_object}"


#----------------------------REVISION LISTS-------------------------------

class RevisionList(models.Model):
    """
    A custom list created by users to organize exercises/exams for revision.
    Users can create multiple revision lists with different names.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='revision_lists')
    name = models.CharField(max_length=200, help_text="Name of the revision list")
    description = models.TextField(blank=True, help_text="Optional description")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'interactions'
        ordering = ['-updated_at']
        unique_together = ['user', 'name']
        indexes = [
            models.Index(fields=['user', '-updated_at']),
        ]

    def __str__(self):
        return f"{self.user.username}'s list: {self.name}"

    @property
    def item_count(self):
        """Return the number of items in this revision list"""
        return self.items.count()


class RevisionListItem(models.Model):
    """
    An item (exercise or exam) in a revision list.
    Uses GenericForeignKey to support both Exercise and Exam models.
    """
    revision_list = models.ForeignKey(RevisionList, on_delete=models.CASCADE, related_name='items')
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    added_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, help_text="Optional notes about this item")

    class Meta:
        app_label = 'interactions'
        ordering = ['-added_at']
        unique_together = ['revision_list', 'content_type', 'object_id']
        indexes = [
            models.Index(fields=['revision_list', '-added_at']),
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f"{self.content_object} in {self.revision_list.name}"


