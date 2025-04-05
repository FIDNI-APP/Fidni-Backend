from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from caracteristics.models import Chapter, ClassLevel, Subject, Theorem, Subfield
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
    


class SaveableMixin(models.Model):
    saved = GenericRelation('Save')

    class Meta:
        abstract = True

    @property
    def is_saved(self):
        return self.saved.exists()
    
class CompleteableMixin(SaveableMixin,VotableMixin,models.Model):
    completed = GenericRelation('Complete')

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
    
#----------------------------COMPLETE-------------------------------

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
    


