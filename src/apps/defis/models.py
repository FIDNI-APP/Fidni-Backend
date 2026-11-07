"""Défi du jour (07/11/2026) : un même problème par jour pour tous les niveaux, à la manière de chess.com.

Le problème n'exige que les outils du Tronc commun ; les indices expliquent l'outil à utiliser. La réponse est un nombre,
vérifié par le serveur : ni la réponse ni la solution ne quittent le serveur avant la fin de la tentative.
Un défi rédigé par Claude reste invisible tant que Natsu ne l'a pas validé (Pilotage › Défis).
"""
from django.conf import settings
from django.db import models

DIFFICULTES = [('easy', 'Facile'), ('medium', 'Moyen'), ('hard', 'Difficile'), ('very_hard', 'Très difficile')]
THEMES = [('algebre', 'Algèbre'), ('arithmetique', 'Arithmétique'), ('logique', 'Logique'),
          ('geometrie', 'Géométrie'), ('denombrement', 'Dénombrement')]


class Defi(models.Model):
    cle = models.SlugField(max_length=80, unique=True, help_text='Identifiant stable du lot importé.')
    date = models.DateField(unique=True, help_text='Jour du défi, heure du Maroc.')
    titre = models.CharField(max_length=120)
    theme = models.CharField(max_length=20, choices=THEMES)
    difficulte = models.CharField(max_length=10, choices=DIFFICULTES)
    enonce = models.TextField(help_text='Texte avec formules $…$ ; une ligne vide sépare deux paragraphes.')
    consigne = models.CharField(max_length=120, help_text='Forme de la réponse : « Donne un nombre entier. »')
    reponse = models.CharField(max_length=40, help_text='Un entier, un décimal ou une fraction : 12, -3, 0,5, 3/4.')
    indices = models.JSONField(default=list, help_text='Du plus léger au plus précis : [{"titre": …, "texte": …}].')
    solution = models.TextField()
    source = models.CharField(max_length=200, blank=True, help_text='Origine, pour le Pilotage seulement.')
    valide = models.BooleanField(default=False, help_text='Invisible des élèves tant qu’il n’est pas validé.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f'{self.date} {self.titre}'


class TentativeDefi(models.Model):
    EN_COURS, TROUVE, RATE = 'en_cours', 'trouve', 'rate'
    STATUTS = [(EN_COURS, 'En cours'), (TROUVE, 'Trouvé'), (RATE, 'Solution vue')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tentatives_defi')
    defi = models.ForeignKey(Defi, on_delete=models.CASCADE, related_name='tentatives')
    statut = models.CharField(max_length=10, choices=STATUTS, default=EN_COURS)
    essais = models.PositiveSmallIntegerField(default=0)
    indices_vus = models.PositiveSmallIntegerField(default=0)
    le_jour_meme = models.BooleanField(default=False, help_text='Trouvé le jour du défi : compte dans la série.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'defi'], name='une_tentative_par_defi')]
        indexes = [models.Index(fields=['user', 'statut'])]
