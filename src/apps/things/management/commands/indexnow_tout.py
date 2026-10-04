"""Envoie à IndexNow (Bing…) toutes les pages publiques du site : accueil, listes et chaque contenu.
À lancer une fois après la mise en place, ou après un gros import :
    docker exec fidni-backend python manage.py indexnow_tout
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.things.models import Content
from config import indexnow


class Command(BaseCommand):
    help = 'Annonce toutes les pages publiques du site à IndexNow.'

    def handle(self, *args, **options):
        if not indexnow.enabled():
            self.stdout.write('IndexNow désactivé (INDEXNOW_ENABLED) : rien envoyé.')
            return
        site = settings.FRONTEND_URL.rstrip('/')
        urls = [site, f'{site}/exercises', f'{site}/lessons', f'{site}/exams']
        urls += [indexnow.content_url(c) for c in Content.objects.only('id', 'type')]
        status = indexnow.submit(urls)
        self.stdout.write(f'{len(urls)} adresse(s) envoyée(s) à IndexNow, réponse : {status}')
