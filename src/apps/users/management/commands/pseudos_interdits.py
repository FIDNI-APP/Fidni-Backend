"""Comptes existants dont le pseudo serait refusé aujourd'hui (authentication/pseudos.py). Lecture seule :
à traiter à la main (renommer le compte, ou le supprimer et le bannir depuis son profil)."""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from apps.authentication.pseudos import pseudo_interdit


class Command(BaseCommand):
    help = 'Liste les comptes au pseudo insultant (lecture seule).'

    def handle(self, *args, **options):
        found = [(u.id, u.username, u.email, u.date_joined) for u in User.objects.only('id', 'username', 'email', 'date_joined')
                 .order_by('id').iterator() if pseudo_interdit(u.username)]
        if not found:
            self.stdout.write('Aucun pseudo refusé parmi les comptes existants.')
            return
        for pk, username, email, joined in found:
            self.stdout.write(f'{pk}\t{username}\t{email}\tinscrit le {joined:%d/%m/%Y}')
        self.stdout.write(f'{len(found)} compte(s) au pseudo refusé.')
