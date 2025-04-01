# users/models.py
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from things.models import Exercise
from django.contrib.contenttypes.models import ContentType
from things.models import Complete, Save, Vote

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bio = models.TextField(max_length=500, blank=True)
    avatar = models.URLField(blank=True)
    favorite_subjects = models.JSONField(default=list, blank=True)
    github_username = models.CharField(max_length=39, blank=True)
    website = models.URLField(blank=True)
    location = models.CharField(max_length=100, blank=True)
    last_activity_date = models.DateField(null=True, blank=True, auto_now=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    
    # Profile settings
    display_email = models.BooleanField(default=False)
    display_stats = models.BooleanField(default=True)
    
    # Theme and display preferences
    theme_preference = models.CharField(max_length=10, choices=[
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('system', 'System Default')
    ], default='system')
    math_notation = models.CharField(max_length=10, choices=[
        ('latex', 'LaTeX'),
        ('ascii', 'ASCII')
    ], default='latex')
    
    # Notification preferences
    email_notifications = models.BooleanField(default=True)
    comment_notifications = models.BooleanField(default=True)
    solution_notifications = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"{self.user.username}'s profile"
    
    def get_contribution_stats(self):
        """Get comprehensive statistics about user contributions"""
        stats = {
            'exercises': self.user.exercises.count(),
            'solutions': self.user.solutions.count(),
            'comments': self.user.comments.count(),
            'total_contributions': 0,
            'upvotes_received': 0,
            'view_count': 0
        }
        
        # Calculate total upvotes received on contributions
        exercise_type = ContentType.objects.get_for_model(Exercise)
        exercises = self.user.exercises.all()
        
        stats['upvotes_received'] = Vote.objects.filter(
            content_type=exercise_type,
            object_id__in=exercises.values_list('id', flat=True),
            value=1
        ).count()
        
        # Calculate total views on exercises
        stats['view_count'] = sum(ex.view_count for ex in exercises)
        
        # Calculate total contributions
        stats['total_contributions'] = stats['exercises'] + stats['solutions'] + stats['comments']
        
        return stats
    
    def get_learning_stats(self):
        """Get statistics about learning progress"""
        stats = {
            'exercises_completed': 0,
            'exercises_in_review': 0,
            'exercises_saved': 0,
            'subjects_studied': set(),
            'total_viewed': 0
        }
        
        # Get completed exercises
        completed = Complete.objects.filter(user=self.user)
        stats['exercises_completed'] = completed.filter(status='success').count()
        stats['exercises_in_review'] = completed.filter(status='review').count()
        
        # Get saved exercises
        stats['exercises_saved'] = Save.objects.filter(user=self.user).count()
        
        # Get total viewed
        stats['total_viewed'] = ViewHistory.objects.filter(user=self.user).count()
        
        # Get unique subjects studied
        exercise_ids = ViewHistory.objects.filter(user=self.user).values_list('content_id', flat=True)
        subjects = Exercise.objects.filter(id__in=exercise_ids).values_list('subject__name', flat=True).distinct()
        stats['subjects_studied'] = list(filter(None, subjects))
        
        return stats
    
    @property
    def reputation(self):
        """Calculate reputation based on contributions and votes"""
        stats = self.get_contribution_stats()
        
        # Simple reputation formula: upvotes + (contributions * 5)
        reputation = stats['upvotes_received'] + (stats['total_contributions'] * 5)
        return reputation

class ViewHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='view_history')
    content = models.ForeignKey(Exercise, on_delete=models.CASCADE)
    viewed_at = models.DateTimeField(auto_now=True)
    completed = models.BooleanField(default=False)
    time_spent = models.PositiveIntegerField(default=0, help_text="Time spent in seconds")
    
    class Meta:
        ordering = ['-viewed_at']
        unique_together = ['user', 'content']
        verbose_name = "View History"
        verbose_name_plural = "View Histories"

# Signal to create profile when user is created
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        UserProfile.objects.create(user=instance)
    instance.profile.save()