"""Messages, appels et travail à plusieurs (13/11/2026).

Règle de Natsu : on n'écrit, n'appelle et n'invite que ses **abonnés mutuels** (chacun suit l'autre, abonnements
acceptés), jamais quelqu'un qui a bloqué ou qu'on a bloqué (regles.py). Beaucoup d'élèves sont mineurs.

- Conversation : « directe » (deux membres, une seule par paire : `cle_directe`) ou « groupe » (6 au plus : la visio
  est en maillage pair-à-pair). Un groupe lié à un contenu (`contenu`) est une **salle de travail** : on fait le même
  sujet ensemble, avec la discussion et l'appel à côté.
- Participant : membre d'une conversation, jusqu'où il a lu, s'il est parti.
- Message : texte (2000 caractères au plus), invitation à travailler, compte rendu d'appel, ou message du site.
  Supprimé par son auteur : le texte disparaît, la ligne reste (« message supprimé »). Gardé 12 mois (purger_messages).
- SignalementMessage : un message signalé à l'équipe (Pilotage).
- Appel / PresenceAppel : appel en cours dans une conversation et qui y est connecté (un appareil = une présence,
  identifiée par son canal WebSocket). Rien de l'audio ni de la vidéo ne passe par le serveur ni n'est enregistré.
"""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

TEXTE_MAX = 2000
TITRE_MAX = 80
MEMBRES_MAX = 6


class Conversation(models.Model):
    DIRECTE, GROUPE = 'directe', 'groupe'
    TYPES = [(DIRECTE, 'Directe'), (GROUPE, 'Groupe')]

    type = models.CharField(max_length=8, choices=TYPES)
    titre = models.CharField(max_length=TITRE_MAX, blank=True, default='')
    createur = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    contenu = models.ForeignKey('things.Content', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    # « petit_id:grand_id » : une seule conversation directe par paire de membres.
    cle_directe = models.CharField(max_length=40, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    dernier_message_at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return f'Conversation {self.pk} ({self.type})'


class Participant(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='participations_messagerie')
    lu_jusqu_a = models.DateTimeField(null=True, blank=True)
    rejoint_le = models.DateTimeField(default=timezone.now)
    parti_le = models.DateTimeField(null=True, blank=True)
    # Question du sujet où il en est (salle de travail), montrée aux autres.
    question = models.CharField(max_length=40, blank=True, default='')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['conversation', 'user'], name='participant_unique')]
        indexes = [models.Index(fields=['user', 'parti_le'], name='participant_user_actif')]

    def __str__(self):
        return f'{self.user_id} dans {self.conversation_id}'


class Message(models.Model):
    TEXTE, INVITATION, APPEL, SYSTEME = 'texte', 'invitation', 'appel', 'systeme'
    TYPES = [(TEXTE, 'Texte'), (INVITATION, 'Invitation à travailler'), (APPEL, 'Appel'), (SYSTEME, 'Message du site')]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    auteur = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name='messages_envoyes')
    type = models.CharField(max_length=10, choices=TYPES, default=TEXTE)
    texte = models.TextField(blank=True, default='')
    # Invitation : {contenu: {...}} ; appel : {video, duree} ; système : {code, ...}.
    donnees = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    supprime_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['conversation', '-created_at'], name='message_conv_date'),
                   models.Index(fields=['created_at'], name='message_date')]

    def __str__(self):
        return f'Message {self.pk} de {self.auteur_id}'


class SignalementMessage(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='signalements')
    auteur = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    motif = models.CharField(max_length=300, blank=True, default='')
    # Copie du texte au moment du signalement : l'auteur du message peut l'effacer ensuite.
    texte = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)
    traite_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['message', 'auteur'], name='signalement_message_unique')]

    def __str__(self):
        return f'Signalement du message {self.message_id}'


class Appel(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='appels')
    lance_par = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    video = models.BooleanField(default=False)
    debut = models.DateTimeField(default=timezone.now)
    fin = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['conversation', 'fin'], name='appel_conv_fin')]

    def __str__(self):
        return f'Appel {self.pk} ({self.conversation_id})'


class PresenceAppel(models.Model):
    appel = models.ForeignKey(Appel, on_delete=models.CASCADE, related_name='presences')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    canal = models.CharField(max_length=200, db_index=True)
    # Onglet du navigateur (identifiant tiré au hasard par la page) : une reconnexion du même onglet remplace sa
    # présence au lieu d'en ajouter une (13/11/2026 : un participant apparaissait jusqu'à 5 fois).
    appareil = models.CharField(max_length=40, blank=True, default='')
    # Dernier signe de vie (ping du navigateur toutes les 20 s) : une présence muette depuis 75 s est retirée.
    vu_le = models.DateTimeField(default=timezone.now)
    rejoint_le = models.DateTimeField(default=timezone.now)
    parti_le = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.user_id} dans l’appel {self.appel_id}'
