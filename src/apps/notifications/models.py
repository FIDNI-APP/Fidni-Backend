from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    """Notification d'un membre (élève, enseignant ou admin), affichée sous la cloche de la barre du haut.

    - « comment » : nouveau commentaire sur un contenu avec lequel il a interagi (voir services.py) ;
    - « reply » : réponse à l'un de ses commentaires.
    Tant qu'il ne l'a pas lue, les nouveaux commentaires du même contenu s'ajoutent à la même notification
    (`count`) au lieu d'en créer une par commentaire.
    """
    KIND_COMMENT = 'comment'
    KIND_REPLY = 'reply'
    KIND_CHOICES = [(KIND_COMMENT, 'Nouveau commentaire'), (KIND_REPLY, 'Réponse à son commentaire')]

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    # Contenu commenté, pour regrouper : « content:12 », « concours-exam:3 », « concours-tip:5 ».
    target = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    link = models.CharField(max_length=200, help_text='Adresse de la page sur le site')
    comment_id = models.PositiveIntegerField(null=True, blank=True, help_text='Dernier commentaire regroupé')
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    excerpt = models.CharField(max_length=200, blank=True)
    count = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'notifications'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['recipient', 'read_at'], name='notif_recipient_read'),
            models.Index(fields=['recipient', '-updated_at'], name='notif_recipient_recent'),
            models.Index(fields=['target'], name='notif_target'),
        ]

    def __str__(self):
        return f'{self.recipient_id} · {self.kind} · {self.target} ×{self.count}'
