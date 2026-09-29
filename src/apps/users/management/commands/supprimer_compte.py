"""python manage.py supprimer_compte <nom> [--avec-contenu]

Sans option : comme une suppression demandée par l'utilisateur (contributions gardées
sous « Compte supprimé »). Avec --avec-contenu : modération, tout est effacé.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from apps.users.account_deletion import delete_account


class Command(BaseCommand):
    help = "Supprime un compte ; --avec-contenu efface aussi ses contributions (modération)."

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--avec-contenu', action='store_true', help='Supprimer aussi ses contributions.')

    def handle(self, username, avec_contenu, **options):
        user = User.objects.filter(username=username).first()
        if user is None:
            raise CommandError(f'Compte introuvable : {username}')
        summary = delete_account(user, keep_contributions=not avec_contenu)
        verb = 'supprimées' if avec_contenu else 'conservées sous « Compte supprimé »'
        self.stdout.write(self.style.SUCCESS(f'Compte {username} supprimé ; contributions {verb} : {summary}'))
