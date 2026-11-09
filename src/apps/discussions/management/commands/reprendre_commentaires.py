"""Rejoue la reprise des commentaires en discussions (migration 0002) : les commentaires et réponses écrits sous les
contenus depuis la dernière reprise rejoignent l'espace Discussions. Sans doublon (legacy_comment_id).

    python manage.py reprendre_commentaires

À lancer une fois le nouveau site en ligne (la discussion a quitté le bas des pages) : l'ancien site a pu recevoir
des commentaires entre la mise en ligne du serveur et celle du site.
"""
import importlib

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.discussions.models import COMMENTAIRE, FORUM, Discussion, Reply


class Command(BaseCommand):
    help = 'Reprend en discussions les commentaires écrits depuis la dernière reprise.'

    def handle(self, *args, **options):
        before = (Discussion.objects.count(), Reply.objects.count())
        migration = importlib.import_module('apps.discussions.migrations.0002_reprise_commentaires')
        with transaction.atomic():
            migration.reprendre(apps, None)
            # La reprise crée des discussions du forum : un commentaire repris reste un commentaire, sans titre.
            Discussion.objects.filter(genre=FORUM, legacy_comment_id__isnull=False, contents__isnull=False) \
                .update(genre=COMMENTAIRE, title='')
        self.stdout.write(f'{Discussion.objects.count() - before[0]} discussion(s) et '
                          f'{Reply.objects.count() - before[1]} réponse(s) reprises.')
