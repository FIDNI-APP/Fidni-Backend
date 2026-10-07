"""Travaux de l'IA réservés aux administrateurs (Pilotage › IA) : import d'un document, correction d'un signalement.

Rien n'est publié par l'IA : chaque travail aboutit à un brouillon que l'administrateur relit, fait corriger,
publie ou rejette.
"""
from django.contrib.auth.models import User
from django.db import models


class IAJob(models.Model):
    IMPORT = 'import'
    SIGNALEMENT = 'signalement'
    KINDS = [(IMPORT, 'Import d’un document'), (SIGNALEMENT, 'Correction d’un signalement')]

    EN_ATTENTE, EN_COURS, PRET, ERREUR = 'en_attente', 'en_cours', 'pret', 'erreur'
    PUBLIE, APPLIQUE, REJETE = 'publie', 'applique', 'rejete'
    STATUTS = [(EN_ATTENTE, 'En attente'), (EN_COURS, 'En cours'), (PRET, 'Prêt à relire'), (ERREUR, 'Erreur'),
               (PUBLIE, 'Publié'), (APPLIQUE, 'Appliqué'), (REJETE, 'Rejeté')]

    kind = models.CharField(max_length=20, choices=KINDS)
    status = models.CharField(max_length=20, choices=STATUTS, default=EN_ATTENTE, db_index=True)
    etape = models.CharField(max_length=160, blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    heartbeat = models.DateTimeField(null=True, blank=True)
    # Options de l'administrateur (niveau, type, droits, crédit, consignes) ; instruction de correction en attente.
    options = models.JSONField(default=dict, blank=True)
    # Brouillon : fiches, figures (PNG en base64), contrôles, problèmes, doutes / proposition de correction.
    result = models.JSONField(default=dict, blank=True)
    # Échanges avec l'IA (pour les corrections demandées par l'administrateur).
    history = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True, default='')
    report = models.ForeignKey('things.ContentReport', on_delete=models.SET_NULL, null=True, blank=True, related_name='ia_jobs')
    usage = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'ia_job'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.kind} #{self.pk} ({self.status})'


class IAFile(models.Model):
    """Document envoyé (gardé en base : privé, jamais servi par le site)."""
    job = models.ForeignKey(IAJob, on_delete=models.CASCADE, related_name='files')
    name = models.CharField(max_length=255)
    mime = models.CharField(max_length=120)
    data = models.BinaryField()

    class Meta:
        db_table = 'ia_file'
