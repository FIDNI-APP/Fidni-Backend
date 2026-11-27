"""Astuces par chapitre (bêta du 27/11/2026, équipe seulement).

Une astuce = une technique de résolution pour un TYPE de question d'un chapitre (« Montrer qu'une suite tend vers une
valeur sans la calculer » → raisonnement par l'absurde). Elle dit quand y penser (les indices de l'énoncé), pourquoi
elle marche, la méthode pas à pas, un exemple corrigé, le piège, et renvoie aux questions du site qui l'utilisent.
Contenu rédigé dans `data/` (Python, chaînes brutes pour le LaTeX), chargé par `manage.py charger_astuces`.
"""
from django.db import models


class Astuce(models.Model):
    slug = models.SlugField(max_length=90, unique=True)
    niveau = models.ForeignKey('caracteristics.ClassLevel', on_delete=models.CASCADE, related_name='astuces')
    chapitre = models.ForeignKey('caracteristics.Chapter', on_delete=models.CASCADE, related_name='astuces')
    type_question = models.CharField(max_length=120, help_text='Filtre « Type de question »')
    technique = models.CharField(max_length=80, help_text='Filtre « Technique »')
    titre = models.CharField(max_length=200)
    resume = models.CharField(max_length=300, blank=True, default='')
    # Textes : HTML court avec formules $…$ (mêmes règles que les contenus)
    signaux = models.JSONField(default=list, blank=True, help_text='Indices de l’énoncé qui doivent y faire penser')
    pourquoi = models.TextField(blank=True, default='')
    methode = models.JSONField(default=list, blank=True, help_text='Étapes, dans l’ordre')
    exemple_enonce = models.TextField(blank=True, default='')
    exemple_solution = models.TextField(blank=True, default='')
    piege = models.TextField(blank=True, default='')
    # [{"cle": "<clé d'import>" ou "id": <id du contenu>, "bloc": "<id de la question>"}] : résolus à l'affichage
    sur_le_site = models.JSONField(default=list, blank=True)
    ordre = models.PositiveIntegerField(default=0)
    publie = models.BooleanField(default=True)
    # 'fichier' : chargée depuis data/ ; 'admin' : créée sur le site. `modifiee_le` : touchée par un admin sur le site —
    # `charger_astuces` ne l'écrase plus jamais (le site fait foi).
    source = models.CharField(max_length=10, default='fichier')
    modifiee_le = models.DateTimeField(null=True, blank=True)
    modifiee_par = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['chapitre_id', 'ordre', 'id']

    def __str__(self):
        return self.titre


class ReglageAstuces(models.Model):
    """Une seule ligne : la section est-elle ouverte à tous les membres (sinon l'équipe seulement) ?"""
    ouvert_a_tous = models.BooleanField(default=False)
    modifie_le = models.DateTimeField(auto_now=True)
    modifie_par = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    @classmethod
    def courant(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
