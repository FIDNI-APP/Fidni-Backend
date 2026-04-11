# apps/skilliq/models.py
from django.db import models
from django.contrib.auth.models import User


class SkillQuestion(models.Model):
    """Quiz question for skill assessment"""
    DIFFICULTY_CHOICES = [
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard'),
    ]

    chapter = models.ForeignKey(
        'caracteristics.Chapter',
        on_delete=models.CASCADE,
        related_name='skill_questions'
    )
    question = models.TextField()
    options = models.JSONField(help_text="List of answer options")
    correct_answer = models.PositiveSmallIntegerField(help_text="Index of correct answer (0-based)")
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='medium')
    explanation = models.TextField(blank=True, help_text="Explanation shown after answering")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = 'skilliq'
        ordering = ['difficulty', 'id']

    def __str__(self):
        return f"{self.chapter.name}: {self.question[:50]}..."


class SkillAssessment(models.Model):
    """User's skill assessment result for a chapter"""
    LEVEL_CHOICES = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('expert', 'Expert'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='skill_assessments')
    chapter = models.ForeignKey(
        'caracteristics.Chapter',
        on_delete=models.CASCADE,
        related_name='assessments'
    )

    score = models.PositiveSmallIntegerField(default=0)
    max_score = models.PositiveSmallIntegerField(default=0)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='beginner')

    # Detailed results
    answers = models.JSONField(default=dict, help_text="Question ID -> user's answer index")
    time_spent = models.PositiveIntegerField(default=0, help_text="Time spent in seconds")

    completed_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'skilliq'
        unique_together = ('user', 'chapter')
        ordering = ['-completed_at']

    def __str__(self):
        return f"{self.user.username} - {self.chapter.name}: {self.level}"

    def calculate_level(self):
        """Calculate skill level based on score percentage"""
        if self.max_score == 0:
            return 'beginner'

        percentage = (self.score / self.max_score) * 100

        if percentage >= 90:
            return 'expert'
        elif percentage >= 70:
            return 'advanced'
        elif percentage >= 50:
            return 'intermediate'
        else:
            return 'beginner'

    def save(self, *args, **kwargs):
        self.level = self.calculate_level()
        super().save(*args, **kwargs)
