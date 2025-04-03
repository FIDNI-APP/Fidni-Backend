# users/models.py - Ajoutons les champs nécessaires au modèle UserProfile

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from things.models import Exercise
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from things.models import Complete

class UserProfile(models.Model):
    USER_TYPE_CHOICES = (
        ('student', 'Student'),
        ('teacher', 'Teacher'),
    )
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bio = models.TextField(max_length=500, blank=True)
    avatar = models.URLField(blank=True)
    favorite_subjects = models.JSONField(default=list, blank=True)
    location = models.CharField(max_length=100, blank=True)
    last_activity_date = models.DateField(null=True, blank=True, auto_now=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    
    # Nouveaux champs pour l'onboarding
    class_level = models.ForeignKey('things.ClassLevel', on_delete=models.SET_NULL, null=True, blank=True, related_name='user_profiles')
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='student')
    onboarding_completed = models.BooleanField(default=False)
    
    # Profile settings
    display_email = models.BooleanField(default=False)
    display_stats = models.BooleanField(default=True)
    
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
        
        # Calculate total contributions
        stats['total_contributions'] = stats['exercises'] + stats['solutions'] + stats['comments']
        
        return stats
    
    def get_learning_stats(self):
        """Get statistics about learning progress"""
        stats = {
            'exercises_completed': 0,
            'exercises_in_review': 0,
            'subjects_studied': set(),
            'total_viewed': 0,
        }
        
        # Get completed exercises
        completed = Complete.objects.filter(user=self.user)
        stats['exercises_completed'] = completed.filter(status='success').count()
        stats['exercises_in_review'] = completed.filter(status='review').count()
        
        # Get total viewed
        stats['total_viewed'] = ViewHistory.objects.filter(user=self.user).count()
        
        # Get unique subjects studied
        exercise_ids = ViewHistory.objects.filter(user=self.user).values_list('content_id', flat=True)
        subjects = Exercise.objects.filter(id__in=exercise_ids).values_list('subject__name', flat=True).distinct()
        stats['subjects_studied'] = list(filter(None, subjects))
        
        return stats


# Nouveau modèle pour les notes par matière
class SubjectGrade(models.Model):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='subject_grades')
    subject = models.ForeignKey('things.Subject', on_delete=models.CASCADE)
    min_grade = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    max_grade = models.DecimalField(max_digits=4, decimal_places=2, default=20)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('user_profile', 'subject')
        verbose_name = "Subject Grade"
        verbose_name_plural = "Subject Grades"
    
    def __str__(self):
        return f"{self.user_profile.user.username}'s grade for {self.subject.name}"


# Signal pour créer le profil quand un utilisateur est créé
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        UserProfile.objects.create(user=instance)
    instance.profile.save()

class ViewHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='view_history')
    content = models.ForeignKey(Exercise, on_delete=models.CASCADE)
    viewed_at = models.DateTimeField(auto_now=True)
    completed = models.CharField(max_length=10, choices=[('success', 'success'), ('review', 'review')], default='review')
    # This field is used to track the time spent on the content
    time_spent = models.PositiveIntegerField(default=0, help_text="Time spent in seconds")
    
    class Meta:
        ordering = ['-viewed_at']
        unique_together = ['user', 'content']
        verbose_name = "View History"
        verbose_name_plural = "View Histories"

