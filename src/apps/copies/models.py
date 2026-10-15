"""Copies des élèves (15/10/2026) : le professeur d'une classe dépose les copies d'une évaluation, l'IA (un modèle bon
marché, settings.COPIES_MODEL) les transcrit et propose une note par question ; le professeur vérifie, corrige, valide
puis publie. Chaque élève voit alors sa copie corrigée (points par question, commentaires, corrigé, points faibles).

Données personnelles d'élèves (souvent mineurs) : les scans sont dans un stockage privé (jamais servi par /media/,
nginx le refuse), lus seulement par le professeur de la classe et par l'élève concerné (liens signés de 10 min), et
supprimés au bout de COPIES_CONSERVATION_MOIS (commande purger_copies). Rien n'est montré à l'élève avant que le
professeur ait validé et publié sa copie.
"""
import os
import uuid

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver


def stockage():
    """Stockage privé des scans (MEDIA_ROOT/prive par défaut : sauvegardé avec le reste, refusé par nginx)."""
    return FileSystemStorage(location=settings.COPIES_ROOT, base_url=None)


def _chemin(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:8] or '.bin'
    return f'{uuid.uuid4().hex}{ext}'


class Evaluation(models.Model):
    FIDNI, PRIVE = 'fidni', 'prive'
    SOURCES = [(FIDNI, 'Contenu Fidni'), (PRIVE, 'Sujet privé de la classe')]
    PRET, EN_COURS, A_VERIFIER, ERREUR = 'pret', 'en_cours', 'a_verifier', 'erreur'
    SUJET_STATUTS = [(PRET, 'Prêt'), (EN_COURS, 'Import en cours'), (A_VERIFIER, 'À vérifier'), (ERREUR, 'Erreur')]

    classroom = models.ForeignKey('classrooms.Classroom', on_delete=models.CASCADE, related_name='evaluations')
    titre = models.CharField(max_length=200)
    date = models.DateField(null=True, blank=True)
    note_sur = models.PositiveSmallIntegerField(default=20)
    # Arrondi des points de chaque question : 0,25, 0,5 ou 1.
    pas = models.FloatField(default=0.5)
    # Contenu d'origine (lien vers la page) ; le sujet utilisé est la copie figée `sujet`, pour que les questions
    # gardent leurs identifiants même si le contenu est modifié ensuite.
    content = models.ForeignKey('things.Content', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    source = models.CharField(max_length=10, choices=SOURCES, default=FIDNI)
    sujet = models.JSONField(default=dict, blank=True)
    # Barème du professeur : {chemin de la question: points}, à la place des points du sujet.
    maxima = models.JSONField(default=dict, blank=True)
    sujet_statut = models.CharField(max_length=12, choices=SUJET_STATUTS, default=PRET)
    # Consignes de correction du professeur (« la rédaction compte », « −0,5 par oubli d'unité »…), lues par l'IA.
    consignes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Import du sujet privé par l'IA (même suivi que les copies).
    etape = models.CharField(max_length=160, blank=True, default='')
    heartbeat = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default='')
    usage = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'copies_evaluation'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f'{self.titre} ({self.classroom_id})'


class Copie(models.Model):
    VIDE, DEPOSEE, EN_ATTENTE, EN_COURS = 'vide', 'deposee', 'en_attente', 'en_cours'
    CORRIGEE, VALIDEE, ERREUR = 'corrigee', 'validee', 'erreur'
    STATUTS = [(VIDE, 'Pas de copie'), (DEPOSEE, 'Déposée'), (EN_ATTENTE, 'En attente de correction'),
               (EN_COURS, 'Correction en cours'), (CORRIGEE, 'Corrigée par l’IA, à vérifier'),
               (VALIDEE, 'Validée par le professeur'), (ERREUR, 'Erreur')]

    evaluation = models.ForeignKey(Evaluation, on_delete=models.CASCADE, related_name='copies')
    # Suppression du compte de l'élève : sa copie disparaît avec lui.
    eleve = models.ForeignKey(User, on_delete=models.CASCADE, related_name='copies_evaluees')
    statut = models.CharField(max_length=12, choices=STATUTS, default=VIDE, db_index=True)
    # Transcription par l'IA : {chemin: {texte, illisible, page}} ; "_hors_question" : texte hors des questions.
    transcription = models.JSONField(default=dict, blank=True)
    # Proposition de l'IA : {chemin: {points, commentaire, confiance, illisible}}.
    ia = models.JSONField(default=dict, blank=True)
    ia_global = models.TextField(blank=True, default='')
    # Points à vérifier en priorité par le professeur : [{chemin, raison}].
    drapeaux = models.JSONField(default=list, blank=True)
    # Notes du professeur (elles remplacent celles de l'IA) : {chemin: {points, commentaire}}.
    notes = models.JSONField(default=dict, blank=True)
    commentaire_prof = models.TextField(blank=True, default='')
    total = models.FloatField(null=True, blank=True)
    validee_le = models.DateTimeField(null=True, blank=True)
    publiee_le = models.DateTimeField(null=True, blank=True, db_index=True)
    etape = models.CharField(max_length=160, blank=True, default='')
    heartbeat = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default='')
    essais = models.PositiveSmallIntegerField(default=0)
    # Questions à renoter seulement (transcription corrigée par le professeur) ; vide : toute la copie.
    a_renoter = models.JSONField(default=list, blank=True)
    usage = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'copies_copie'
        constraints = [models.UniqueConstraint(fields=['evaluation', 'eleve'], name='copie_unique_par_eleve')]

    def __str__(self):
        return f'Copie {self.eleve_id} / {self.evaluation_id} ({self.statut})'


class Page(models.Model):
    """Une page scannée d'une copie (image JPEG normalisée : orientation, taille)."""
    copie = models.ForeignKey(Copie, on_delete=models.CASCADE, related_name='pages')
    numero = models.PositiveSmallIntegerField(default=1)
    fichier = models.FileField(storage=stockage, upload_to=_chemin)
    largeur = models.PositiveIntegerField(default=0)
    hauteur = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'copies_page'
        ordering = ['numero', 'id']


class Lot(models.Model):
    """PDF de toutes les copies de la classe, à découper par élève (proposition de l'IA, confirmée par le prof)."""
    EN_ATTENTE, EN_COURS, PRET, ERREUR, CONFIRME = 'en_attente', 'en_cours', 'pret', 'erreur', 'confirme'
    STATUTS = [(EN_ATTENTE, 'En attente'), (EN_COURS, 'Lecture des noms'), (PRET, 'À confirmer'),
               (ERREUR, 'Erreur'), (CONFIRME, 'Confirmé')]

    evaluation = models.ForeignKey(Evaluation, on_delete=models.CASCADE, related_name='lots')
    fichier = models.FileField(storage=stockage, upload_to=_chemin, blank=True)
    nom = models.CharField(max_length=255, blank=True, default='')
    nb_pages = models.PositiveIntegerField(default=0)
    # Découpage sans IA : toutes les copies ont le même nombre de pages.
    pages_par_copie = models.PositiveSmallIntegerField(null=True, blank=True)
    statut = models.CharField(max_length=12, choices=STATUTS, default=EN_ATTENTE)
    # [{pages: [1, 2], nom_lu, eleve_id, score}]
    proposition = models.JSONField(default=list, blank=True)
    etape = models.CharField(max_length=160, blank=True, default='')
    heartbeat = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default='')
    usage = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'copies_lot'
        ordering = ['-created_at']


class FichierSujet(models.Model):
    """Sujet (et corrigé) envoyés pour un sujet privé, le temps que l'IA les lise ; effacés ensuite."""
    evaluation = models.ForeignKey(Evaluation, on_delete=models.CASCADE, related_name='fichiers_sujet')
    nom = models.CharField(max_length=255)
    fichier = models.FileField(storage=stockage, upload_to=_chemin)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'copies_fichier_sujet'
        ordering = ['id']


class UsageCopies(models.Model):
    """Copies corrigées par l'IA, par professeur et par mois (quota COPIES_QUOTA_MOIS ; le site paie l'IA)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    mois = models.CharField(max_length=7)  # « 2026-10 »
    copies = models.PositiveIntegerField(default=0)
    cout_usd = models.FloatField(default=0)

    class Meta:
        db_table = 'copies_usage'
        constraints = [models.UniqueConstraint(fields=['user', 'mois'], name='usage_copies_unique')]


# Les fichiers ne partent pas avec les lignes (suppression d'une classe, d'une évaluation, d'un compte) : on les efface.
@receiver(post_delete, sender=Page)
@receiver(post_delete, sender=Lot)
@receiver(post_delete, sender=FichierSujet)
def _effacer_fichier(sender, instance, **kwargs):
    f = instance.fichier
    if f and f.name:
        try:
            f.storage.delete(f.name)
        except OSError:
            pass
