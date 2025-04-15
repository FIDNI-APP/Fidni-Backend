# notebooks/models.py

from django.db import models
from django.contrib.auth.models import User
from caracteristics.models import Subject, Chapter, ClassLevel
from things.models import Lesson

class Notebook(models.Model):
    """
    Un cahier représente une matière pour un niveau de classe spécifique.
    Chaque utilisateur peut avoir plusieurs cahiers, un par matière qu'il étudie.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notebooks')
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='notebooks')
    class_level = models.ForeignKey(ClassLevel, on_delete=models.PROTECT, related_name='notebooks')
    title = models.CharField(max_length=200, blank=True)  # Titre personnalisé ou généré automatiquement
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'title']
        ordering = ['subject__name']
    
    def __str__(self):
        return f"{self.title or self.subject.name} - {self.user.username}"
    
    def save(self, *args, **kwargs):
        # Générer un titre par défaut si non fourni
        if not self.title and self.subject:
            self.title = f"{self.subject.name} - {self.class_level.name}"
        super().save(*args, **kwargs)


class NotebookSection(models.Model):
    """
    Une section de cahier correspond à un chapitre du programme.
    Chaque section peut contenir une leçon.
    """
    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='sections')
    chapter = models.ForeignKey(Chapter, on_delete=models.PROTECT, related_name='notebook_sections')
    lesson = models.ForeignKey(Lesson, on_delete=models.SET_NULL, null=True, blank=True, related_name='notebook_sections')
    user_notes = models.TextField(blank=True)  # Notes personnelles de l'utilisateur
    order = models.PositiveIntegerField(default=0)
    
    class Meta:
        unique_together = ['notebook', 'chapter']
        ordering = ['order', 'chapter__name']
    
    def __str__(self):
        return f"{self.chapter.name} - {self.notebook}"
