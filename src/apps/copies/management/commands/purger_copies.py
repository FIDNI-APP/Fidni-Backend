"""RGPD : efface les scans des copies (et les PDF de classe) plus anciens que COPIES_CONSERVATION_MOIS.

Les notes et les commentaires restent (l'élève garde sa copie corrigée) ; seule l'image disparaît. Tâche planifiée
chaque nuit (installer-serveur.sh)."""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.copies.models import FichierSujet, Lot, Page


class Command(BaseCommand):
    help = 'Efface les scans de copies trop anciens (données personnelles des élèves).'

    def add_arguments(self, parser):
        parser.add_argument('--essai', action='store_true', help='Compter sans rien effacer.')

    def handle(self, essai=False, **options):
        limite = timezone.now() - timedelta(days=30 * settings.COPIES_CONSERVATION_MOIS)
        jour = limite.date()
        pages = Page.objects.filter(Q(copie__evaluation__date__lt=jour)
                                    | Q(copie__evaluation__date__isnull=True, created_at__lt=limite))
        lots = Lot.objects.filter(created_at__lt=timezone.now() - timedelta(days=30))  # un lot oublié : 30 jours
        sujets = FichierSujet.objects.filter(created_at__lt=timezone.now() - timedelta(days=30))
        n = (pages.count(), lots.count(), sujets.count())
        if not essai:
            for qs in (pages, lots, sujets):
                for obj in qs.iterator():
                    obj.delete()  # le fichier part avec (signal post_delete)
        self.stdout.write(f"{'À effacer' if essai else 'Effacés'} : {n[0]} pages, {n[1]} PDF de classe, "
                          f"{n[2]} sujets envoyés.")
