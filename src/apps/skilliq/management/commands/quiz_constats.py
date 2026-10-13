"""Fiches des chapitres en ligne (résultats des élèves, programme, cours) pour écrire les quiz : skilliq/constats.py."""
from django.core.management.base import BaseCommand, CommandError

from apps.caracteristics.models import ClassLevel
from apps.caracteristics.programme import nom_niveau_actuel
from apps.skilliq.constats import constats_niveau


class Command(BaseCommand):
    help = "Affiche, par niveau, la fiche de chaque chapitre en ligne (aucune donnée personnelle : des taux)."

    def add_arguments(self, parser):
        parser.add_argument('niveaux', nargs='*', help='Noms des niveaux (par défaut : tous)')

    def handle(self, niveaux, **options):
        qs = ClassLevel.objects.order_by('order', 'id')
        if niveaux:
            qs = qs.filter(name__in=[nom_niveau_actuel(n) for n in niveaux])
            if not qs:
                raise CommandError('Aucun niveau trouvé.')
        for niveau in qs:
            fiches = constats_niveau(niveau)
            if fiches:
                self.stdout.write(f'\n\n######## {niveau.name}\n\n{fiches}')
