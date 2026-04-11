# apps/users/models.py

import os
import random
import uuid
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey


DEFAULT_AVATARS = [
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Felix",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Aneka",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Luna",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Max",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Sophie",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Oliver",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Emma",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Leo",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Mia",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Jack",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Zoe",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Noah",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Lily",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Lucas",
    "https://api.dicebear.com/7.x/avataaars/svg?seed=Ava",
]


def get_random_avatar():
    return random.choice(DEFAULT_AVATARS)


def user_avatar_path(instance, filename):
    ext = filename.split('.')[-1]
    filename = f'{uuid.uuid4()}.{ext}'
    return os.path.join('avatars', str(instance.user.id), filename)


class UserProfile(models.Model):
    # Types d'utilisateurs
    USER_TYPE_CHOICES = (
        ('student', 'Student'),
        ('teacher', 'Teacher'),
    )
    
    # Learning style choices
    LEARNING_STYLE_CHOICES = (
        ('visual', 'Visual'),
        ('practical', 'Practical'),
        ('theoretical', 'Theoretical'),
        ('mixed', 'Mixed'),
    )
    
    # Study frequency choices
    STUDY_FREQUENCY_CHOICES = (
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('occasional', 'Occasional'),
    )
    
    # Champs de préférences avec valeurs par défaut
    _defaults = {
        'display_email': False,
        'display_stats': True,
        'display_activity': True,
        'profile_public': True,
        'email_notifications': True,
        'comment_notifications': True,
        'solution_notifications': True,
        'reminder_enabled': False,
        'onboarding_completed': False,
        'user_type': 'student',
        'learning_style': 'mixed',
        'study_frequency': 'weekly',
        'daily_goal_minutes': 30,
    }
    
    # Relations principales
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    class_level = models.ForeignKey(
        'caracteristics.ClassLevel', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='user_profiles'
    )
    
    # Attributs de base
    bio = models.TextField(max_length=500, blank=True)
    location = models.CharField(max_length=100, blank=True)
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default=_defaults['user_type'])
    
    # Avatar - Support both URL (legacy) and File upload
    avatar_url = models.URLField(blank=True, null=True, help_text="Legacy URL avatar or external URL")
    avatar_file = models.ImageField(upload_to=user_avatar_path, null=True, blank=True, help_text="Uploaded avatar file")
    
    # Learning preferences
    learning_style = models.CharField(
        max_length=20, 
        choices=LEARNING_STYLE_CHOICES, 
        default=_defaults['learning_style'],
        blank=True
    )
    study_frequency = models.CharField(
        max_length=20, 
        choices=STUDY_FREQUENCY_CHOICES, 
        default=_defaults['study_frequency'],
        blank=True
    )
    daily_goal_minutes = models.PositiveIntegerField(default=_defaults['daily_goal_minutes'])
    learning_goals = models.JSONField(default=list, blank=True, help_text="List of learning goal IDs")
    
    # Dates
    joined_at = models.DateTimeField(auto_now_add=True)
    last_activity_date = models.DateTimeField(null=True, blank=True)
    
    # Privacy settings
    profile_public = models.BooleanField(default=_defaults['profile_public'])
    display_email = models.BooleanField(default=_defaults['display_email'])
    display_stats = models.BooleanField(default=_defaults['display_stats'])
    display_activity = models.BooleanField(default=_defaults['display_activity'])
    
    # Notification settings
    email_notifications = models.BooleanField(default=_defaults['email_notifications'])
    comment_notifications = models.BooleanField(default=_defaults['comment_notifications'])
    solution_notifications = models.BooleanField(default=_defaults['solution_notifications'])
    reminder_enabled = models.BooleanField(default=_defaults['reminder_enabled'])
    reminder_time = models.TimeField(null=True, blank=True)
    
    # Onboarding
    onboarding_completed = models.BooleanField(default=_defaults['onboarding_completed'])
    onboarding_step = models.PositiveIntegerField(default=0)

    # Target Subjects (favorite subjects — students)
    target_subjects = models.ManyToManyField(
        'caracteristics.Subject',
        blank=True,
        related_name='target_users'
    )

    # Teacher-specific fields
    teaching_subjects = models.ManyToManyField(
        'caracteristics.Subject',
        blank=True,
        related_name='teachers',
    )
    teaching_class_levels = models.ManyToManyField(
        'caracteristics.ClassLevel',
        blank=True,
        related_name='teachers',
    )
    teacher_code = models.CharField(max_length=12, unique=True, null=True, blank=True)

    # Student → teacher reference
    teacher = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='students',
    )
    
    class Meta:
        app_label = 'users'
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
    
    def __str__(self):
        return f"{self.user.username}'s profile"
    
    @property
    def avatar(self):
        """Returns the avatar URL - prioritizes uploaded file over URL"""
        if self.avatar_file:
            return self.avatar_file.url
        if self.avatar_url:
            return self.avatar_url
        return None
    
    @avatar.setter
    def avatar(self, value):
        """Setter for backward compatibility - sets avatar_url"""
        if isinstance(value, str):
            self.avatar_url = value
    
    def ensure_teacher_code(self):
        """Assign a unique teacher code if not already set."""
        if not self.teacher_code:
            self.teacher_code = _generate_teacher_code()
            self.save(update_fields=['teacher_code'])

    def update_last_activity(self):
        """Met à jour la date de dernière activité"""
        self.last_activity_date = timezone.now()
        self.save(update_fields=['last_activity_date'])
    
    def get_contribution_stats(self):
        """Obtient des statistiques sur les contributions de l'utilisateur"""
        from apps.things.models import Content, Solution, Comment
        from apps.interactions.models import Vote

        content_items = Content.objects.filter(author=self.user)
        content_ct = ContentType.objects.get_for_model(Content)
        upvotes_received = Vote.objects.filter(
            content_type=content_ct,
            object_id__in=content_items.values_list('id', flat=True),
            value=1
        ).count()

        view_count = content_items.aggregate(total=models.Sum('view_count'))['total'] or 0

        stats = {
            'exercises': content_items.filter(type='exercise').count(),
            'solutions': Solution.objects.filter(author=self.user).count(),
            'comments': Comment.objects.filter(author=self.user).count(),
            'upvotes_received': upvotes_received,
            'view_count': view_count,
        }
        stats['total_contributions'] = stats['exercises'] + stats['solutions'] + stats['comments']

        return stats

    def get_learning_stats(self):
        """Obtient des statistiques sur la progression d'apprentissage"""
        from apps.things.models import Content
        from apps.interactions.models import Complete, Save

        content_ct = ContentType.objects.get_for_model(Content)
        exercise_ids = Content.objects.filter(type='exercise').values_list('id', flat=True)

        # Completion stats
        exercises_completed = Complete.objects.filter(
            user=self.user,
            status='success',
            content_type=content_ct,
            object_id__in=exercise_ids,
        ).count()

        exercises_in_review = Complete.objects.filter(
            user=self.user,
            status='review',
            content_type=content_ct,
            object_id__in=exercise_ids,
        ).count()

        # Saved content
        exercises_saved = Save.objects.filter(
            user=self.user,
            content_type=content_ct,
            object_id__in=exercise_ids,
        ).count()

        # View history
        total_viewed = ViewHistory.objects.filter(
            user=self.user,
            content_type=content_ct
        ).count()

        viewed_ids = ViewHistory.objects.filter(
            user=self.user,
            content_type=content_ct
        ).values_list('object_id', flat=True)

        subjects = Content.objects.filter(
            id__in=viewed_ids
        ).values_list('subject__name', flat=True).distinct()
        
        stats = {
            'exercises_completed': exercises_completed,
            'exercises_in_review': exercises_in_review,
            'exercises_saved': exercises_saved,
            'total_viewed': total_viewed,
            'subjects_studied': list(filter(None, subjects)),
        }
        
        return stats
    
    def has_completed_exercise(self, exercise):
        """Vérifie si l'utilisateur a terminé un exercice avec succès"""
        from apps.interactions.models import Complete
        content_type = ContentType.objects.get_for_model(exercise)
        return Complete.objects.filter(
            user=self.user,
            content_type=content_type,
            object_id=exercise.id,
            status='success'
        ).exists()
    
    def get_favorite_subjects(self):
        """Returns list of favorite subject IDs"""
        return list(self.target_subjects.values_list('id', flat=True))
    
    def set_favorite_subjects(self, subject_ids):
        """Sets favorite subjects from list of IDs"""
        from apps.caracteristics.models import Subject
        self.target_subjects.clear()
        if subject_ids:
            subjects = Subject.objects.filter(id__in=subject_ids)
            self.target_subjects.add(*subjects)


class SubjectGrade(models.Model):
    """Gestion des notes par matière - current grade and target"""
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='subject_grades')
    subject = models.ForeignKey('caracteristics.Subject', on_delete=models.CASCADE, related_name='subject_grades')
    current_grade = models.DecimalField(max_digits=4, decimal_places=2, default=10)
    target_grade = models.DecimalField(max_digits=4, decimal_places=2, default=15)
    # Keep legacy fields for backward compatibility
    min_grade = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    max_grade = models.DecimalField(max_digits=4, decimal_places=2, default=20)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        app_label = 'users'
        unique_together = ('user', 'subject')
        verbose_name = "Subject Grade"
        verbose_name_plural = "Subject Grades"
    
    def __str__(self):
        return f"{self.user.user.username}'s grade for {self.subject.name}: {self.current_grade} -> {self.target_grade}"
    
    def save(self, *args, **kwargs):
        # Sync legacy fields with new fields
        self.min_grade = self.current_grade
        self.max_grade = self.target_grade
        super().save(*args, **kwargs)


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
        app_label = 'users'
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


class TeacherInvitation(models.Model):
    """Invitation envoyée par un prof à un élève."""
    STATUS_CHOICES = [
        ('pending',  'En attente'),
        ('accepted', 'Acceptée'),
        ('declined', 'Refusée'),
    ]

    teacher  = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='sent_invitations')
    student  = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='received_invitations')
    status   = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'users'
        unique_together = ('teacher', 'student')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.teacher.user.username} → {self.student.user.username} ({self.status})"


def _generate_teacher_code():
    """Generate a unique PROF-XXXX code."""
    import random
    import string
    while True:
        code = 'PROF-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not UserProfile.objects.filter(teacher_code=code).exists():
            return code


# Signal pour créer le profil quand un utilisateur est créé
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(
            user=instance,
            avatar_url=get_random_avatar()
        )


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        UserProfile.objects.create(
            user=instance,
            avatar_url=get_random_avatar()
        )
    else:
        instance.profile.save()