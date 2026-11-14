"""Numéros des contenus par niveau et chapitre (things/numeros.py) : recalcule ceux qui manquent ou ne sont plus
valables (contenu changé de chapitre par un ajout en masse, sans signal). Les numéros encore valables ne bougent pas.

    python manage.py numeroter_contenus            # tous les contenus
    python manage.py numeroter_contenus --a-blanc  # dire seulement ce qui changerait
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.things.models import Content
from apps.things.numeros import numeroter, paires


class Command(BaseCommand):
    help = 'Recalcule les numéros des contenus par niveau et chapitre.'

    def add_arguments(self, parser):
        parser.add_argument('--a-blanc', action='store_true', help='Ne rien enregistrer.')

    def handle(self, *args, **o):
        a_revoir = []
        qs = Content.objects.order_by('created_at', 'id').prefetch_related('class_levels', 'chapters__class_levels', 'numeros')
        for c in qs:
            voulues = paires(c)
            actuelles = {(n.class_level_id, n.chapter_id) for n in c.numeros.all() if n.type == c.type}
            if voulues != actuelles or len(actuelles) != len(c.numeros.all()):
                a_revoir.append(c)
        self.stdout.write(f'{len(a_revoir)} contenu(s) à renuméroter.')
        if o['a_blanc']:
            for c in a_revoir[:20]:
                self.stdout.write(f'  {c.pk} {c.type} « {c.title[:60]} »')
            return
        with transaction.atomic():
            for c in a_revoir:
                numeroter(c)
        self.stdout.write(self.style.SUCCESS('Numéros à jour.'))
