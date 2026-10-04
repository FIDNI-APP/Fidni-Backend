"""python manage.py notifier_admins --sujet "…" --fichier rapport.md

Envoie un message texte à tous les administrateurs (superusers actifs) : rapports de l'agent
d'import de contenus, alertes d'exploitation.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Envoie un message (fichier texte) aux administrateurs."

    def add_arguments(self, parser):
        parser.add_argument('--sujet', required=True)
        parser.add_argument('--fichier', required=True, help='Contenu du message (texte ou Markdown).')

    def handle(self, sujet, fichier, **options):
        try:
            with open(fichier, encoding='utf-8') as fh:
                body = fh.read()
        except OSError as exc:
            raise CommandError(f'Lecture impossible : {exc}')
        to = list(User.objects.filter(is_superuser=True, is_active=True).exclude(email='').values_list('email', flat=True))
        if not to:
            raise CommandError('Aucun administrateur avec une adresse e-mail.')
        n = send_mail(f'[Fidni] {sujet}', body, settings.DEFAULT_FROM_EMAIL, to)
        self.stdout.write(self.style.SUCCESS(f'{n} message envoyé à {len(to)} administrateur(s).'))
