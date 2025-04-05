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
    
