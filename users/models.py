from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey


class UserProfile(models.Model):
    # Types d'utilisateurs
    USER_TYPE_CHOICES = (
        ('student', 'Student'),
        ('teacher', 'Teacher'),
    )
    # Champs de préférences avec valeurs par défaut
    _defaults = {
        'display_email': False,
        'display_stats': True,
        'email_notifications': True,
        'comment_notifications': True,
        'solution_notifications': True,
        'onboarding_completed': False,
        'user_type': 'student',
    }
    
    # Relations principales
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    class_level = models.ForeignKey('caracteristics.ClassLevel', on_delete=models.SET_NULL, 
                                   null=True, blank=True, related_name='user_profiles', default=None)
    
    # Attributs de base
    bio = models.TextField(max_length=500, blank=True)
    avatar = models.URLField(blank=True)
    location = models.CharField(max_length=100, blank=True)
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default=_defaults['user_type'])
    
    # Dates
    joined_at = models.DateTimeField(auto_now_add=True)
    last_activity_date = models.DateTimeField(null=True, blank=True)
    
    # Implémentation des préférences comme propriétés dynamiques
    display_email = models.BooleanField(default=_defaults['display_email'])
    display_stats = models.BooleanField(default=_defaults['display_stats'])
    email_notifications = models.BooleanField(default=_defaults['email_notifications'])
    comment_notifications = models.BooleanField(default=_defaults['comment_notifications'])
    solution_notifications = models.BooleanField(default=_defaults['solution_notifications'])
    onboarding_completed = models.BooleanField(default=_defaults['onboarding_completed'])

    # Target Subjects
    target_subjects = models.ManyToManyField('caracteristics.Subject', blank=True, related_name='target_users')
    
    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
    
    def __str__(self):
        return f"{self.user.username}'s profile"
    
    def update_last_activity(self):
        """Met à jour la date de dernière activité"""
        self.last_activity_date = timezone.now()
        self.save(update_fields=['last_activity_date'])
    
    def get_contribution_stats(self):
        """Obtient des statistiques sur les contributions de l'utilisateur"""
        from things.models import Exercise, Solution, Comment
        
        stats = {
            'exercises': Exercise.objects.filter(author=self.user).count(),
            'solutions': Solution.objects.filter(author=self.user).count(),
            'comments': Comment.objects.filter(author=self.user).count(),
        }
        stats['total_contributions'] = sum(stats.values())
        
        return stats
    
    def get_learning_stats(self):
        """Obtient des statistiques sur la progression d'apprentissage"""
        from things.models import Exercise
        from interactions.models import Complete
        from users.models import ViewHistory  # Utiliser le chemin d'import correct
        
        stats = {
            'exercises_completed': Complete.objects.filter(
                user=self.user, status='success').count(),
            'exercises_in_review': Complete.objects.filter(
                user=self.user, status='review').count(),
            'total_viewed': ViewHistory.objects.filter(user=self.user).count(),
        }
        
        exercise_ids = ViewHistory.objects.filter(
            user=self.user
        ).values_list('object_id', flat=True)
        
        # Assurez-vous que content_type est filtré pour Exercise
        content_type = ContentType.objects.get_for_model(Exercise)
        exercise_ids = ViewHistory.objects.filter(
            user=self.user, 
            content_type=content_type
        ).values_list('object_id', flat=True)
        
        subjects = Exercise.objects.filter(
            id__in=exercise_ids
        ).values_list('subject__name', flat=True).distinct()
        
        stats['subjects_studied'] = list(filter(None, subjects))
        
        return stats
    
    # Méthodes utilitaires, comme dans le code Reddit
    def has_completed_exercise(self, exercise):
        """Vérifie si l'utilisateur a terminé un exercice avec succès"""
        from interactions.models import Complete
        content_type = ContentType.objects.get_for_model(exercise)
        return Complete.objects.filter(
            user=self.user,
            content_type=content_type,
            object_id=exercise.id,
            status='success'
        ).exists()
    
    def is_favorite_subject(self, subject_id):
        """Vérifie si un sujet est dans les favoris de l'utilisateur"""
        return str(subject_id) in self.favorite_subjects
    
    def add_favorite_subject(self, subject_id):
        """Ajoute un sujet aux favoris"""
        subject_id = str(subject_id)  # Convertir en string pour cohérence
        if subject_id not in self.favorite_subjects:
            self.favorite_subjects.append(subject_id)
            self.save(update_fields=['favorite_subjects'])
    
    def remove_favorite_subject(self, subject_id):
        """Retire un sujet des favoris"""
        subject_id = str(subject_id)  # Convertir en string pour cohérence
        if subject_id in self.favorite_subjects:
            self.favorite_subjects.remove(subject_id)
            self.save(update_fields=['favorite_subjects'])
    
    def saved_exercises(self):
        """Récupère les exercices sauvegardés par l'utilisateur"""
        from things.models import Exercise
        from interactions.models import Save
        content_type = ContentType.objects.get_for_model(Exercise)
        return Save.objects.filter(user=self.user, content_type=content_type).values_list('object_id', flat=True)


class SubjectGrade(models.Model):
    """Gestion des notes par matière"""
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='subject_grades')
    subject = models.ForeignKey('caracteristics.Subject', on_delete=models.CASCADE, related_name='subject_grades')
    min_grade = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    max_grade = models.DecimalField(max_digits=4, decimal_places=2, default=20)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('user', 'subject')
        verbose_name = "Subject Grade"
        verbose_name_plural = "Subject Grades"
    
    def __str__(self):
        return f"{self.user.username}'s grade for {self.subject.name}"
    


class ViewHistory(models.Model):
    """Historique de consultation avec traçage du temps passé"""
    STATUS_CHOICES = [
        ('success', 'Success'),
        ('review', 'Review'),
        ('viewed', 'Viewed')
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='view_history')
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    viewed_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='viewed')
    time_spent = models.PositiveIntegerField(default=0, help_text="Time spent in seconds")
    
    class Meta:
        ordering = ['-viewed_at']
        unique_together = ['user', 'content_type', 'object_id']
        verbose_name = "View History"
        verbose_name_plural = "View Histories"
    
    @classmethod
    def record_view(cls, user, content_object, time_spent=None):
        """Enregistre une vue avec le temps passé en option"""
        content_type = ContentType.objects.get_for_model(content_object)
        
        view, created = cls.objects.get_or_create(
            user=user,
            content_type=content_type,
            object_id=content_object.id,
            defaults={'status': 'viewed'}
        )
        
        if time_spent is not None:
            view.time_spent = time_spent
            view.save(update_fields=['time_spent', 'viewed_at'])
        else:
            view.save(update_fields=['viewed_at'])
        
        return view


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