"""python manage.py exporter_donnees <nom ou e-mail> [--sortie fichier.json]

Droit d'accès et de portabilité (RGPD, art. 15 et 20) : copie de toutes les données d'un compte, à envoyer à la
personne qui la demande par e-mail (contact@fidni.fr, réponse sous un mois). Plus de téléchargement en libre service
depuis le 15/10/2026 (Natsu : l'export brut montrait la structure de l'application).
"""
import json

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q

from apps.users.legal import export_user_data


class Command(BaseCommand):
    help = "Exporte toutes les données d'un compte (demande d'accès RGPD) en JSON."

    def add_arguments(self, parser):
        parser.add_argument('compte', help="Nom d'utilisateur ou e-mail")
        parser.add_argument('--sortie', help='Fichier à écrire (sinon : sortie standard)')

    def handle(self, compte, sortie=None, **options):
        users = list(User.objects.filter(Q(username__iexact=compte) | Q(email__iexact=compte))[:2])
        if not users:
            raise CommandError(f'Compte introuvable : {compte}')
        if len(users) > 1:
            raise CommandError(f'Plusieurs comptes pour « {compte} » : donner le nom d’utilisateur.')
        body = json.dumps(export_user_data(users[0]), cls=DjangoJSONEncoder, ensure_ascii=False, indent=2)
        if sortie:
            with open(sortie, 'w', encoding='utf-8') as f:
                f.write(body)
            self.stdout.write(self.style.SUCCESS(f'Données de {users[0].username} écrites dans {sortie}'))
        else:
            self.stdout.write(body)
