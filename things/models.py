from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from caracteristics.models import Chapter, ClassLevel, Subject, Theorem, Subfield
from interactions.models import VotableMixin, CompleteableMixin
import logging

logger = logging.getLogger('django')
    

 
#----------------------------EXERCISE-------------------------------

class Exercise(CompleteableMixin, models.Model):
    DIFFICULTY_CHOICES = [
        ('easy', 'easy'),
        ('medium', 'medium'),
        ('hard', 'hard'),
    ]
    
    title = models.CharField(max_length=200)
    content = models.TextField()
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES)
    chapters = models.ManyToManyField(Chapter, related_name='exercises')
    class_levels = models.ManyToManyField(ClassLevel, related_name='exercises')
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='exercises')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    view_count = models.PositiveIntegerField(default=0)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='exercises', null=True)
    theorems = models.ManyToManyField(Theorem, related_name='exercises' )
    subfields = models.ManyToManyField(Subfield, related_name='exercises')

    def __str__(self):
        return self.title
    
    @property
    def average_perceived_difficulty(self):
        ratings = self.difficulty_ratings.all()
        if not ratings:
            return None
        return sum(rating.rating for rating in ratings) / ratings.count()

    @property
    def success_count(self):
        return self.progress.filter(status='success').count()

    @property
    def review_count(self):
        return self.progress.filter(status='review').count()
    

#----------------------------SOLUTION-------------------------------

class Solution(VotableMixin, models.Model):
    exercise = models.OneToOneField(Exercise, on_delete=models.PROTECT, related_name='solution')
    content = models.TextField()
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='solutions')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Solution for {self.exercise.title}"

#----------------------------COMMENT-------------------------------

class Comment(VotableMixin, models.Model):
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='comments')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='replies')

    def __str__(self):
        return f"Comment by {self.author.username} on {self.exercise.title}"
    

#----------------------------LESSON-------------------------------

class Lesson(VotableMixin, models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='lessons')
    class_levels = models.ManyToManyField(ClassLevel, related_name='lessons')
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='lessons')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    view_count = models.PositiveIntegerField(default=0)
    theorems = models.ManyToManyField(Theorem, related_name='lessons')

    def __str__(self):
        return self.title
    
#----------------------------EXAM-------------------------------
class exam(VotableMixin, models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='examples')
    class_levels = models.ManyToManyField(ClassLevel, related_name='examples')
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='examples')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    view_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.title
    
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
    


