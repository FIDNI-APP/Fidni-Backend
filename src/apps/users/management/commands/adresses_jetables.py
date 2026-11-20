"""Adresses e-mail jetables (authentication/jetables.py, 20/11/2026).

Sans option : comptes existants dont l'adresse serait refusée aujourd'hui (lecture seule ; à traiter à la main).
--mettre-a-jour : télécharge la dernière liste communautaire dans authentication/data/adresses_jetables.txt
(à committer ensuite : le fichier fait partie du code).
"""
import urllib.request

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from apps.authentication import jetables


class Command(BaseCommand):
    help = 'Liste les comptes à adresse e-mail jetable (lecture seule), ou met la liste à jour.'

    def add_arguments(self, parser):
        parser.add_argument('--mettre-a-jour', action='store_true', help='Télécharger la dernière liste.')

    def handle(self, *args, **options):
        if options['mettre_a_jour']:
            try:
                with urllib.request.urlopen(jetables.SOURCE, timeout=30) as r:
                    texte = r.read().decode('utf-8')
            except OSError as e:
                raise CommandError(f'Téléchargement impossible : {e}')
            lignes = sorted({l.strip().lower() for l in texte.splitlines() if l.strip() and not l.startswith('#')})
            if len(lignes) < 1000:
                raise CommandError(f'Liste suspecte ({len(lignes)} domaines) : rien n’est remplacé.')
            with open(jetables.FICHIER, 'w', encoding='utf-8') as fh:
                fh.write('\n'.join(lignes) + '\n')
            jetables.domaines.cache_clear()
            self.stdout.write(f'{len(lignes)} domaines jetables enregistrés dans {jetables.FICHIER}.')
            return
        found = [(u.id, u.username, u.email, u.date_joined) for u in User.objects.only('id', 'username', 'email', 'date_joined')
                 .order_by('id').iterator() if jetables.adresse_jetable(u.email)]
        if not found:
            self.stdout.write('Aucun compte avec une adresse jetable.')
            return
        for pk, username, email, joined in found:
            self.stdout.write(f'{pk}\t{username}\t{email}\tinscrit le {joined:%d/%m/%Y}')
        self.stdout.write(f'{len(found)} compte(s) avec une adresse jetable.')
