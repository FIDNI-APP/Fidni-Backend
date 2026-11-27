"""Charge les astuces rédigées dans apps/astuces/data/ (une liste ASTUCES par module).

    python manage.py charger_astuces                 # tous les modules de data/
    python manage.py charger_astuces --a-blanc       # vérifie sans rien écrire

Même slug = mise à jour. Une astuce du même niveau absente du fichier est dépubliée (jamais supprimée).
"""
import importlib
import pkgutil

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.astuces import data as paquet
from apps.astuces.models import Astuce
from apps.caracteristics.models import Chapter, ClassLevel

CHAMPS = ('type_question', 'technique', 'titre', 'resume', 'signaux', 'pourquoi', 'methode', 'exemple_enonce',
          'exemple_solution', 'piege', 'sur_le_site')


class Command(BaseCommand):
    help = 'Charge les astuces (bêta) depuis apps/astuces/data/'

    def add_arguments(self, parser):
        parser.add_argument('--a-blanc', action='store_true')

    def handle(self, *args, **opts):
        modules = [importlib.import_module(f'{paquet.__name__}.{m.name}') for m in pkgutil.iter_modules(paquet.__path__)]
        with transaction.atomic():
            for module in modules:
                self._charger(module)
            if opts['a_blanc']:
                transaction.set_rollback(True)
                self.stdout.write('À blanc : rien n’est écrit.')

    def _charger(self, module):
        niveau = ClassLevel.objects.filter(name=module.NIVEAU).order_by('id').first()
        if niveau is None:
            raise CommandError(f'Niveau introuvable : {module.NIVEAU}')
        vus, crees, gardees = set(), 0, 0
        for ordre, a in enumerate(module.ASTUCES, 1):
            chapitre = Chapter.objects.filter(name=a['chapitre'], class_levels=niveau).order_by('id').first()
            if chapitre is None:
                raise CommandError(f"Chapitre introuvable en {niveau.name} : {a['chapitre']} ({a['slug']})")
            if a['slug'] in vus:
                raise CommandError(f"Slug en double : {a['slug']}")
            vus.add(a['slug'])
            valeurs = {k: a.get(k, [] if k in ('signaux', 'methode', 'sur_le_site') else '') for k in CHAMPS}
            existante = Astuce.objects.filter(slug=a['slug']).first()
            if existante and (existante.modifiee_le or existante.source != 'fichier'):
                gardees += 1  # modifiée sur le site par un admin : le site fait foi
                continue
            _, cree = Astuce.objects.update_or_create(slug=a['slug'], defaults={
                **valeurs, 'niveau': niveau, 'chapitre': chapitre, 'ordre': ordre, 'publie': True, 'source': 'fichier'})
            crees += cree
        # Retirée du fichier : dépubliée, sauf si un admin l'a créée ou modifiée sur le site.
        retirees = (Astuce.objects.filter(niveau=niveau, publie=True, source='fichier', modifiee_le__isnull=True)
                    .exclude(slug__in=vus).update(publie=False))
        self.stdout.write(f'{niveau.name} : {len(vus)} astuces ({crees} nouvelles, {gardees} modifiées sur le site '
                          f'et gardées telles quelles, {retirees} dépubliées)')
