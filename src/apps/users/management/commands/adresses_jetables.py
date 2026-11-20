"""Adresses e-mail jetables (authentication/jetables.py, 20/11/2026).

Sans option : comptes existants dont l'adresse serait refusée aujourd'hui (lecture seule ; à traiter à la main).
--mettre-a-jour : actualise les deux sources dans FIDNI_JETABLES_FICHIER (fichier embarqué par défaut).
"""
import os
import tempfile
import urllib.request
from http.client import HTTPException
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from apps.authentication import jetables


def telecharger(url):
    limite = 12 * 1024 * 1024
    with urllib.request.urlopen(url, timeout=20) as reponse:
        brut = reponse.read(limite + 1)
    if len(brut) > limite:
        raise CommandError('Liste trop volumineuse.')
    lignes = {l.strip().lower() for l in brut.decode('utf-8-sig').splitlines() if l.strip() and not l.lstrip().startswith('#')}
    domaines = {d for d in lignes if jetables.NOM_DOMAINE.fullmatch(d)}
    if len(domaines) < 1000 or len(domaines) < 0.95 * len(lignes):
        raise CommandError(f'Liste de domaines invalide ({len(domaines)} entrées reconnues).')
    return domaines


class Command(BaseCommand):
    help = 'Liste les comptes à adresse e-mail jetable (lecture seule), ou met la liste à jour.'

    def add_arguments(self, parser):
        parser.add_argument('--mettre-a-jour', action='store_true', help='Télécharger la dernière liste.')

    def handle(self, *args, **options):
        if options['mettre_a_jour']:
            cible = jetables.fichier_liste()
            try:
                domaines = telecharger(jetables.SOURCE) | telecharger(jetables.SOURCE_QUOTIDIENNE)
            except (OSError, HTTPException, UnicodeError) as exc:
                raise CommandError(f'Actualisation impossible : {exc}') from exc
            cible.parent.mkdir(parents=True, exist_ok=True)
            fh = tempfile.NamedTemporaryFile(dir=cible.parent, delete=False, mode='w', encoding='utf-8')
            temporaire = Path(fh.name)
            try:
                with fh:
                    fh.write('\n'.join(sorted(domaines)) + '\n')
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(temporaire, cible)
            finally:
                temporaire.unlink(missing_ok=True)
            self.stdout.write(f'{len(domaines)} domaines jetables enregistrés dans {cible}.')
            return
        found = [(u.id, u.username, u.email, u.date_joined) for u in User.objects.only('id', 'username', 'email', 'date_joined')
                 .order_by('id').iterator() if jetables.adresse_jetable(u.email)]
        if not found:
            self.stdout.write('Aucun compte avec une adresse jetable.')
            return
        for pk, username, email, joined in found:
            self.stdout.write(f'{pk}\t{username}\t{email}\tinscrit le {joined:%d/%m/%Y}')
        self.stdout.write(f'{len(found)} compte(s) avec une adresse jetable.')
