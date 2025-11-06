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
    This is a simpler model for automatic page-based time tracking
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='study_time_entries')
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    # Time spent in seconds
    time_spent_seconds = models.PositiveIntegerField(default=0)

    # When this time was recorded
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'interactions'
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['user', 'content_type', 'object_id']),
            models.Index(fields=['recorded_at']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.time_spent_seconds}s on {self.content_object}"



# In TimeSpent model, add these methods to properly handle time calculations
class TimeSpent(models.Model):
    """
    Garde le temps total et le temps de la session courante pour un contenu
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='time_spent')
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Temps total cumulé de toutes les sessions
    total_time = models.DurationField(default=timedelta(0))
    
    # Temps de la session courante (peut être remis à zéro)
    current_session_time = models.DurationField(default=timedelta(0))
    
    # Remove or simplify the resume preference - it's confusing
    # resume_preference = models.CharField(...)  # REMOVE THIS
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_session_start = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'interactions'
        unique_together = ('user', 'content_type', 'object_id')
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f"{self.user.username} - Total: {self.total_time}, Session: {self.current_session_time}"
    
    @property
    def total_time_in_seconds(self):
        """Safely return total time in seconds"""
        if self.total_time:
            return int(self.total_time.total_seconds())
        return 0
    
    @property
    def current_session_in_seconds(self):
        """Safely return current session time in seconds"""
        if self.current_session_time:
            return int(self.current_session_time.total_seconds())
        return 0
    
    def update_session_time(self, seconds):
        """Update current session time"""
        self.current_session_time = timedelta(seconds=seconds)
        self.save()
    
    def save_and_reset_session(self, session_type='study', notes=''):
        """Add current session to total and reset"""
        if self.current_session_time and self.current_session_time.total_seconds() > 0:
            self.total_time += self.current_session_time
            
            # Create a session record
            TimeSession.objects.create(
                user=self.user,
                content_type=self.content_type,
                object_id=self.object_id,
                session_duration=self.current_session_time,
                started_at=self.last_session_start or (timezone.now() - self.current_session_time),
                ended_at=timezone.now(),
                session_type=session_type,
                notes=notes
            )
            
            self.current_session_time = timedelta(0)
            self.last_session_start = None
            self.save()
            
            return True
        return False
    
    
class TimeSpentMixin(CompleteableMixin):
    time_spent = GenericRelation(TimeSpent)

    class Meta:
        app_label = 'interactions'
        abstract = True

    @property
    def total_time_spent(self):
        return sum([time.time_spent for time in self.time_spent.all()], timedelta())


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


