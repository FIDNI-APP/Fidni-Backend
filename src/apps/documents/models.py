"""Documents de l'éditeur « façon Word » (12/10/2026) : une feuille A4 par document, privée à son auteur.

Le HTML suit le format des contenus : formules en texte `$…$` / `$$…$$` (rendues par KaTeX côté front),
images par leur URL stable `/api/files/<uuid>/download/`. Seul son auteur lit et modifie un document.
"""
from django.contrib.auth.models import User
from django.db import models


class Document(models.Model):
    ORIENTATIONS = [('portrait', 'Portrait'), ('paysage', 'Paysage')]
    MARGES = [('normale', 'Normales'), ('etroite', 'Étroites'), ('large', 'Larges')]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=200, default='Document sans titre')
    html = models.TextField(blank=True, default='')
    # Mise en page (onglet « Mise en page » de l'éditeur).
    orientation = models.CharField(max_length=10, choices=ORIENTATIONS, default='portrait')
    marges = models.CharField(max_length=10, choices=MARGES, default='normale')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'documents'
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['user', '-updated_at'])]

    def __str__(self):
        return f'{self.title} ({self.user.username})'
