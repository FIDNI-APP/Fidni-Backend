from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from caracteristics.models import Chapter, ClassLevel, Subject, Theorem, Subfield
from interactions.models import VotableMixin, CompleteableMixin, TimeSpentMixin
import logging

logger = logging.getLogger('django')
    

 
#----------------------------EXERCISE-------------------------------

class Exercise(TimeSpentMixin, models.Model):
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
        """Calculate the average perceived difficulty of this exercise based on user ratings.

        """
        ratings = self.difficulty_ratings.all()
        if not ratings:
            return None
        return sum(rating.rating for rating in ratings) / ratings.count()

    @property
    def success_count(self):
        """Count the number of users who have successfully completed this exercise.

        """
        return self.progress.filter(status='success').count()

    @property
    def review_count(self):
        """Count the number of users who are currently reviewing this exercise.

        """
        return self.progress.filter(status='review').count()
    
    @property
    def average_time_spent(self):
        """Calculate the average time spent on this exercise by all users.

        """
        if not self.time_spent.exists():
            return 0
        
        total_time = sum([time.time_spent for time in self.time_spent.all()])
        count = self.time_spent.count()
        if count == 0:
            return 0
        return total_time / count
    

#----------------------------SOLUTION-------------------------------

class Solution(VotableMixin, models.Model):
    exercise = models.OneToOneField(Exercise, on_delete=models.PROTECT, related_name='solution')
    content = models.TextField()
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='solutions')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Solution for {self.exercise.title}"
    
#----------------------------LESSON-------------------------------

class Lesson(CompleteableMixin):
    title = models.CharField(max_length=200)
    content = models.TextField()
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='lessons')
    class_levels = models.ManyToManyField(ClassLevel, related_name='lessons')
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='lessons')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    view_count = models.PositiveIntegerField(default=0)
    theorems = models.ManyToManyField(Theorem, related_name='lessons')
    chapters = models.ManyToManyField(Chapter, related_name='lessons')
    subfields = models.ManyToManyField(Subfield, related_name='lessons')

    def __str__(self):
        return self.title
#----------------------------EXAM-------------------------------
class Exam(TimeSpentMixin, models.Model):
    DIFFICULTY_CHOICES = [
        ('easy', 'easy'),
        ('medium', 'medium'),
        ('hard', 'hard'),
    ]
    
    title = models.CharField(max_length=200)
    content = models.TextField()
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES)
    chapters = models.ManyToManyField(Chapter, related_name='exams')
    class_levels = models.ManyToManyField(ClassLevel, related_name='exams')
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='exams')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    view_count = models.PositiveIntegerField(default=0)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='exams', null=True)
    theorems = models.ManyToManyField(Theorem, related_name='exams' )
    subfields = models.ManyToManyField(Subfield, related_name='exams')
    is_national_exam = models.BooleanField(default=False, help_text="Indicates if this exam is a national exam")
    national_date = models.DateField(null=True, blank=True, help_text="Date of the exam if it is a national exam")
    
    

    def __str__(self):
        return self.title
    
    @property
    def average_perceived_difficulty(self):
        """Calculate the average perceived difficulty of this exercise based on user ratings.

        """
        ratings = self.difficulty_ratings.all()
        if not ratings:
            return None
        return sum(rating.rating for rating in ratings) / ratings.count()

    @property
    def success_count(self):
        """Count the number of users who have successfully completed this exercise.

        """
        return self.progress.filter(status='success').count()

    @property
    def review_count(self):
        """Count the number of users who are currently reviewing this exercise.

        """
        return self.progress.filter(status='review').count()
    
    @property
    def average_time_spent(self):
        """Calculate the average time spent on this exercise by all users.

        """
        if not self.time_spent.exists():
            return 0
        
        total_time = sum([time.time_spent for time in self.time_spent.all()])
        count = self.time_spent.count()
        if count == 0:
            return 0
        return total_time / count
#----------------------------COMMENT-------------------------------
class Comment(VotableMixin, models.Model):
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name='comments', null=True, blank=True)
    lesson = models.ForeignKey(Lesson, on_delete=models.PROTECT, related_name='comments', null=True, blank=True)
    exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name='comments', null=True, blank=True)  # Add this line
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='comments')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='replies')

    def __str__(self):
        if self.exercise:
            return f"Comment by {self.author.username} on exercise {self.exercise.title}"
        elif self.lesson:
            return f"Comment by {self.author.username} on lesson {self.lesson.title}"
        elif self.exam:
            return f"Comment by {self.author.username} on exam {self.exam.title}"
        return f"Comment by {self.author.username}"
    
    def clean(self):
        # Ensure that exactly one of exercise, lesson, or exam is set
        content_objects = [self.exercise, self.lesson, self.exam]
        non_null_objects = [obj for obj in content_objects if obj is not None]
        
        if len(non_null_objects) == 0:
            raise ValidationError("Comment must be associated with either an exercise, lesson, or exam")
        if len(non_null_objects) > 1:
            raise ValidationError("Comment cannot be associated with multiple content types")
    


    

    
