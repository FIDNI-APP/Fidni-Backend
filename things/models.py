from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
import logging

logger = logging.getLogger('django')
#----------------------------CLASSLEVEL-------------------------------

class ClassLevel(models.Model):
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(unique=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.name


#----------------------------SUBJECT-------------------------------

class Subject(models.Model):
    name = models.CharField(max_length=100)
    class_levels = models.ManyToManyField(ClassLevel, related_name='subjects')

    def __str__(self):
        return self.name
    
    
#----------------------------SUBFIELD-------------------------------

class Subfield(models.Model):
    name = models.CharField(max_length=100)
    class_levels = models.ManyToManyField(ClassLevel, related_name='subfields')
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='subfields')

    def __str__(self):
        return self.name



#----------------------------CHAPTER-------------------------------

class Chapter(models.Model):
    name = models.CharField(max_length=100)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='chapters', null = True)
    class_levels = models.ManyToManyField(ClassLevel, related_name = 'chapters')
    subfield = models.ForeignKey(Subfield, on_delete=models.PROTECT, related_name='chapters', null = True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name}_{self.class_levels.name}"
    


#----------------------------THEOREME-------------------------------

class Theorem(models.Model):
    name = models.CharField(max_length=100)
    chapters = models.ManyToManyField(Chapter, related_name='theorems')
    class_levels = models.ManyToManyField(ClassLevel, related_name='theorems')
    subject = models.ForeignKey(Subject, related_name='theorems', on_delete= models.PROTECT, null= True)
    subfield = models.ForeignKey(Subfield,related_name='theorems', on_delete=models.PROTECT, null= True)

    def __str__(self):
        return self.name
    
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
    def upvote(self, user):
        """Toggle upvote from this user"""
        existing_vote = self.votes.filter(user=user).first()
        print('existing_vote', existing_vote)
        if not existing_vote:
            # No vote exists yet, create an upvote
            return self.votes.create(user=user, value=Vote.UP)
        elif existing_vote.value == Vote.UP:
            # Already upvoted, so remove the vote (toggle off)
            existing_vote.delete()
            return None
        else:
            # Currently downvoted, change to upvote
            existing_vote.value = Vote.UP
            existing_vote.save()
            return existing_vote

    def downvote(self, user):
        """Toggle downvote from this user"""
        existing_vote = self.votes.filter(user=user).first()
        
        if not existing_vote:
            # No vote exists yet, create a downvote
            return self.votes.create(user=user, value=Vote.DOWN)
        elif existing_vote.value == Vote.DOWN:
            # Already downvoted, so remove the vote (toggle off)
            existing_vote.delete()
            return None
        else:
            # Currently upvoted, change to downvote
            existing_vote.value = Vote.DOWN
            existing_vote.save()
            return existing_vote

    
#----------------------------EXERCISE-------------------------------

class Exercise(VotableMixin, models.Model):
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


#----------------------------PROGRESS-------------------------------
class Complete(models.Model):
    PROGRESS_CHOICES = [
        ('success', 'Réussi'),
        ('review', 'À revoir'),
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