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

    # Questions importées (13/10/2026, commande quiz_importer) : brouillon « à relire », jamais montré aux
    # élèves tant que l'administrateur ne l'a pas validé ; `motif` dit pourquoi elle a été écrite (admin seulement).
    SOURCE_CHOICES = [('', 'Administrateur'), ('claude', 'Rédigée par Claude')]
    source = models.CharField(max_length=8, choices=SOURCE_CHOICES, blank=True, default='')
    a_relire = models.BooleanField(default=False)
    motif = models.TextField(blank=True, default='')
    # Théorèmes (ou propriétés) qu'évalue la question (13/10/2026) : bilan « maîtrisé / à revoir » par théorème à
    # la fin du quiz, et tirage qui couvre chaque théorème.
    theorems = models.ManyToManyField('caracteristics.Theorem', blank=True, related_name='skill_questions')
    # Niveau du quiz (13/10/2026) : un quiz = (chapitre, niveau), jamais partagé entre deux niveaux. « Limites et
    # continuité » a un quiz 2ème Bac SM (avec arc tangente) et un quiz 2ème Bac PC/SVT (sans) : des questions
    # distinctes, mises en ligne séparément. Vide : question d'avant ce découpage, jamais servie.
    class_level = models.ForeignKey('caracteristics.ClassLevel', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='skill_questions')
    # Première mise en ligne (13/10/2026) : un quiz de chapitre est « Nouveau » 14 jours (skilliq/annonces.py).
    en_ligne_le = models.DateTimeField(null=True, blank=True)

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

    # Score de la tentative précédente (10/10/2026) : « 40 % → 80 % » après un nouveau passage.
    previous_score = models.PositiveSmallIntegerField(null=True, blank=True)
    previous_max = models.PositiveSmallIntegerField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=1)
    # Bilan du dernier passage par théorème (13/10/2026) : [{id, name, justes, total, pct}], du moins maîtrisé
    # au mieux maîtrisé ; « non_evalues » à part. Vide pour les passages plus anciens.
    par_theoreme = models.JSONField(default=dict, blank=True)
    # Niveau du quiz passé (13/10/2026) : un résultat par (élève, chapitre, niveau). Vide : passage d'avant le
    # découpage par niveau, repris au prochain passage du quiz de son niveau.
    class_level = models.ForeignKey('caracteristics.ClassLevel', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')

    completed_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'skilliq'
        unique_together = ('user', 'chapter', 'class_level')
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
