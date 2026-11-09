"""Communauté (09/11/2026) : profils publics enrichis, abonnements, badges.

- ProfilPublic : réglages du profil public (bannière, objectif, vitrine de badges, blocs masqués, abonnés à valider,
  présence dans la recherche de membres, professeur vérifié par l'équipe). Sans ligne en base, les valeurs par défaut
  dépendent du compte (services.reglages) : un élève mineur, ou dont l'âge est inconnu, valide ses abonnés.
- Abonnement : X suit Y. « en_attente » tant que Y n'a pas accepté, quand Y valide ses abonnés. Suivre ne donne aucun
  droit d'écrire à quelqu'un.
- Blocage : Y a bloqué X. X ne peut plus suivre Y ni le lui demander ; les abonnements entre eux sont retirés.
- BadgeObtenu : un palier de badge atteint (badges.py). Il reste acquis même si le chiffre redescend.
"""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

# Bannières dessinées par le site (motifs d'étoiles, couleurs de Fidni). Vide : choisie d'après le pseudo.
BANNIERES = ('zellige-vert', 'zellige-or', 'nuit', 'sable', 'menthe', 'terre')
# Blocs du profil qu'on peut masquer aux autres membres.
BLOCS = ('chiffres', 'badges', 'chapitres', 'defi', 'activite')
VITRINE_MAX = 3
OBJECTIF_MAX = 60


class ProfilPublic(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profil_public')
    banniere = models.CharField(max_length=20, blank=True, default='')
    objectif = models.CharField(max_length=OBJECTIF_MAX, blank=True, default='',
                                help_text='Ce que vise l’élève, en quelques mots (« Médecine »).')
    vitrine = models.JSONField(default=list, blank=True, help_text='Badges mis en avant (ids, 3 au plus).')
    blocs_masques = models.JSONField(default=list, blank=True)
    abonnes_a_valider = models.BooleanField(default=True)
    visible_recherche = models.BooleanField(default=True)
    verifie = models.BooleanField(default=False, help_text='Professeur vérifié par l’équipe.')
    # Premier calcul des badges : les paliers déjà atteints sont enregistrés sans notification.
    badges_init_le = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Profil public de {self.user_id}'


class Abonnement(models.Model):
    ACCEPTE, EN_ATTENTE = 'accepte', 'en_attente'
    STATUTS = [(ACCEPTE, 'Accepté'), (EN_ATTENTE, 'En attente')]

    abonne = models.ForeignKey(User, on_delete=models.CASCADE, related_name='abonnements')
    suivi = models.ForeignKey(User, on_delete=models.CASCADE, related_name='abonnes')
    statut = models.CharField(max_length=12, choices=STATUTS, default=ACCEPTE)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['abonne', 'suivi'], name='abonnement_unique'),
            models.CheckConstraint(condition=~models.Q(abonne=models.F('suivi')), name='abonnement_pas_soi_meme'),
        ]
        indexes = [models.Index(fields=['suivi', 'statut'], name='abo_suivi_statut'),
                   models.Index(fields=['abonne', 'statut'], name='abo_abonne_statut')]

    def __str__(self):
        return f'{self.abonne_id} suit {self.suivi_id} ({self.statut})'


class Blocage(models.Model):
    auteur = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocages')
    bloque = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['auteur', 'bloque'], name='blocage_unique')]

    def __str__(self):
        return f'{self.auteur_id} bloque {self.bloque_id}'


class BadgeObtenu(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='badges_obtenus')
    badge = models.CharField(max_length=20)
    palier = models.PositiveSmallIntegerField(help_text='1 bronze, 2 argent, 3 or.')
    obtenu_le = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'badge', 'palier'], name='badge_palier_unique')]
        indexes = [models.Index(fields=['-obtenu_le'], name='badge_recent')]

    def __str__(self):
        return f'{self.user_id} {self.badge} {self.palier}'
