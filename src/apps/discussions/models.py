"""Espace Discussions (08/11/2026) : un forum par salons, à part des contenus.

Constat du 08/11/2026 : 8 commentaires pour 5 747 vues sous les contenus, presque aucun avec une réponse. La
discussion quitte le bas des pages : chaque discussion a un titre, un salon, et peut taguer des leçons, des exercices
et des examens (`contents`), affichés en cartes. La page d'un contenu montre les discussions qui le taguent (onglet
« Discussions »). Les commentaires existants sont repris en discussions (migration 0002, `legacy_comment_id`).

Votes « utile » : les votes (interactions.Vote, valeur 1) des discussions et des réponses.
"""
import html
import re

from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.utils import timezone

from apps.interactions.models import VotableMixin

SALONS = [
    ('entraide', 'Entraide'),
    ('methodes', 'Méthodes'),
    ('bac', 'Bac & concours'),
    ('orientation', 'Orientation'),
]
SALON_KEYS = {k for k, _ in SALONS}


def plain_text(body):
    """Texte d'un message écrit avec l'éditeur (HTML, maths en $…$) : sans balises, espaces simples."""
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', body or '')).split())


class Discussion(VotableMixin, models.Model):
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True, default='')
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='discussions')
    salon = models.CharField(max_length=20, choices=SALONS, default='entraide')
    # Niveau visé : celui de l'auteur par défaut ; vide = tous les niveaux (orientation, méthodes générales…).
    class_level = models.ForeignKey('caracteristics.ClassLevel', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='discussions')
    contents = models.ManyToManyField('things.Content', related_name='discussions', blank=True)
    attachments = GenericRelation('uploads.FileAttachment')
    created_at = models.DateTimeField(default=timezone.now)
    edited_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(default=timezone.now)
    reply_count = models.PositiveIntegerField(default=0)
    # Recherche : titre + texte, sans accents ni balises, en minuscules (things/search_text.normalize).
    search_text = models.TextField(blank=True, default='')
    # Commentaire repris lors du passage au forum (migration 0002) : une seule reprise par commentaire.
    legacy_comment_id = models.PositiveIntegerField(null=True, blank=True, unique=True)

    class Meta:
        ordering = ['-last_activity_at', '-id']
        indexes = [
            models.Index(fields=['salon', '-last_activity_at'], name='disc_salon_activite'),
            models.Index(fields=['class_level', '-last_activity_at'], name='disc_niveau_activite'),
            models.Index(fields=['-last_activity_at'], name='disc_activite'),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        from apps.things.search_text import normalize
        self.search_text = normalize(f'{self.title} {plain_text(self.body)}')
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and ('title' in update_fields or 'body' in update_fields):
            kwargs['update_fields'] = list({*update_fields, 'search_text'})
        super().save(*args, **kwargs)


class Reply(VotableMixin, models.Model):
    discussion = models.ForeignKey(Discussion, on_delete=models.CASCADE, related_name='replies')
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='discussion_replies')
    body = models.TextField()
    # « En réponse à @x » : une réponse d'une même discussion (fil d'un seul niveau, comme sur téléphone).
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    attachments = GenericRelation('uploads.FileAttachment')
    created_at = models.DateTimeField(default=timezone.now)
    edited_at = models.DateTimeField(null=True, blank=True)
    legacy_comment_id = models.PositiveIntegerField(null=True, blank=True, unique=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [models.Index(fields=['discussion', 'created_at'], name='disc_reponse_ordre')]

    def __str__(self):
        return f'Réponse de {self.author_id} à {self.discussion_id}'


class Follow(models.Model):
    """Discussion suivie : prévenu de chaque nouvelle réponse. L'auteur et ceux qui répondent suivent d'office."""
    discussion = models.ForeignKey(Discussion, on_delete=models.CASCADE, related_name='follows')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='discussion_follows')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('discussion', 'user')
