from django.db import models
from django.contrib.auth.models import User
from caracteristics.models import Subject, Chapter, ClassLevel
from things.models import Lesson
import json

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


class NotebookAnnotation(models.Model):
    """
    Annotations (surlignages, notes, dessins) sur les leçons dans les cahiers.
    """
    ANNOTATION_TYPES = [
        ('highlight', 'Surlignage'),
        ('note', 'Note'),
        ('pen', 'Dessin'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notebook_annotations')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='annotations')
    annotation_id = models.CharField(max_length=100)  # ID unique de l'annotation côté frontend
    annotation_type = models.CharField(max_length=20, choices=ANNOTATION_TYPES)
    position_x = models.FloatField()  # Position X de l'annotation
    position_y = models.FloatField()  # Position Y de l'annotation
    width = models.FloatField(null=True, blank=True)  # Largeur (pour les surlignages)
    height = models.FloatField(null=True, blank=True)  # Hauteur (pour les surlignages)
    color = models.CharField(max_length=7, default='#ffeb3b')  # Couleur en format hex
    content = models.TextField(blank=True)  # Contenu textuel (pour les notes)
    path_data = models.TextField(blank=True)  # Données du chemin SVG (pour les dessins)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'lesson', 'annotation_id']
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.annotation_type} - {self.lesson.title} - {self.user.username}"
    
    def to_frontend_format(self):
        """Convertit l'annotation au format attendu par le frontend"""
        return {
            'id': self.annotation_id,
            'type': self.annotation_type,
            'position': {
                'x': self.position_x,
                'y': self.position_y,
                'width': self.width,
                'height': self.height
            },
            'color': self.color,
            'content': self.content,
            'path': self.path_data
        }
    
    @classmethod
    def from_frontend_format(cls, user, lesson, annotation_data):
        """Crée une annotation à partir des données du frontend"""
        position = annotation_data.get('position', {})
        return cls(
            user=user,
            lesson=lesson,
            annotation_id=annotation_data['id'],
            annotation_type=annotation_data['type'],
            position_x=position.get('x', 0),
            position_y=position.get('y', 0),
            width=position.get('width'),
            height=position.get('height'),
            color=annotation_data.get('color', '#ffeb3b'),
            content=annotation_data.get('content', ''),
            path_data=annotation_data.get('path', '')
        )
