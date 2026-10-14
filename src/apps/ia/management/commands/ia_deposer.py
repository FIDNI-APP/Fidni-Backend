"""Dépose des fiches préparées par Claude en brouillon dans Pilotage › À valider (ia/depot.py), sans rien publier."""
from django.core.management.base import BaseCommand, CommandError

from apps.ia.depot import DepotErreur, deposer


class Command(BaseCommand):
    help = "Dépose une ou plusieurs fiches (dossiers avec fiche.json, figures/, commentaires.json, document/) " \
           "en brouillon « prêt à relire » dans Pilotage › À valider."

    def add_arguments(self, parser):
        parser.add_argument('dossiers', nargs='+')

    def handle(self, dossiers, **options):
        for dossier in dossiers:
            try:
                job, cree = deposer(dossier)
            except (DepotErreur, OSError, ValueError) as exc:
                raise CommandError(f'{dossier} : {exc}')
            r = job.result
            erreurs = sum(len(c.get('erreurs') or []) for c in r.get('controles') or [])
            titre = (r.get('fiches') or [{}])[0].get('titre', '')
            maj = job.options.get('contenu')
            self.stdout.write(
                f"{'Déposé' if cree else 'Remplacé'} : « {titre} » → https://fidni.fr/pilotage?onglet=validation&brouillon={job.id}"
                + (f" (met à jour le contenu #{maj['id']})" if maj else '')
                + (f' — {erreurs} erreur(s) à corriger avant publication' if erreurs else ''))
