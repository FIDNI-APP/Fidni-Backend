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
        unique_together = ('user', 'content_type', 'object_id')
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
        ]

class VotableMixin(models.Model):
    votes = GenericRelation(Vote)

    class Meta:
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
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'content_type', 'object_id']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.session_duration} on {self.content_object}"
    
    @property
    def session_duration_in_seconds(self):
        return int(self.session_duration.total_seconds()) if self.session_duration else 0
    
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
    
    def save_and_reset_session(self):
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
                session_type='study'
            )
            
            self.current_session_time = timedelta(0)
            self.last_session_start = None
            self.save()
            
            return True
        return False
    
    
class TimeSpentMixin(CompleteableMixin):
    time_spent = GenericRelation(TimeSpent)

    class Meta:
        abstract = True

    @property
    def total_time_spent(self):
        return sum([time.time_spent for time in self.time_spent.all()], timedelta())


