"""Supprime des contenus publiés (doublons…) comme le bouton « Supprimer » du site : le contenu, ses figures, les
photos de ses commentaires et des solutions proposées. Une copie JSON de chaque contenu (champs, structure,
chapitres, niveaux, théorèmes) est d'abord écrite dans MEDIA_ROOT/prive/corbeille_contenus/ pour pouvoir le refaire.
Usage : manage.py supprimer_contenus 233 234 --motif "doublon de 217" [--essai]"""
import json
import os

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from django.utils import timezone

from apps.things.models import Comment, Content, ProposedSolution


class Command(BaseCommand):
    help = 'Supprime des contenus (avec une copie JSON dans la corbeille).'

    def add_arguments(self, parser):
        parser.add_argument('ids', nargs='+', type=int)
        parser.add_argument('--motif', default='')
        parser.add_argument('--essai', action='store_true', help='affiche seulement ce qui serait supprimé')

    def handle(self, ids, motif, essai, **options):
        from apps.uploads.models import FileAttachment

        dossier = os.path.join(settings.MEDIA_ROOT, 'prive', 'corbeille_contenus')
        if not essai:
            os.makedirs(dossier, exist_ok=True)
        for pk in ids:
            c = Content.objects.filter(pk=pk).first()
            if c is None:
                self.stdout.write(f'{pk} : introuvable')
                continue
            if essai:
                self.stdout.write(f'{pk} : serait supprimé — « {c.title} » ({c.type}, clé {(c.json_content or {}).get("import", {}).get("cle")})')
                continue
            copie = {
                'motif': motif, 'supprime_le': timezone.now().isoformat(), 'id': c.pk, 'type': c.type,
                'title': c.title, 'json_content': c.json_content, 'difficulty': c.difficulty,
                'chapters': list(c.chapters.values_list('name', flat=True)),
                'class_levels': list(c.class_levels.values_list('name', flat=True)),
                'theorems': list(c.theorems.values_list('name', flat=True)),
                'school_id': c.school_id, 'author_id': c.author_id,
            }
            with open(os.path.join(dossier, f'{pk}.json'), 'w', encoding='utf-8') as fh:
                json.dump(copie, fh, ensure_ascii=False, indent=1, default=str)
            owners = [
                (Content, [c.pk]),
                (Comment, list(Comment.objects.filter(content_item=c).values_list('id', flat=True))),
                (ProposedSolution, list(ProposedSolution.objects.filter(content_item=c).values_list('id', flat=True))),
            ]
            for model, oids in owners:
                if oids:
                    ct = ContentType.objects.get_for_model(model)
                    for att in FileAttachment.objects.filter(content_type=ct, object_id__in=oids):
                        att.file.delete(save=False)
                        att.delete()
            titre = c.title
            c.delete()
            self.stdout.write(f'{pk} : supprimé — « {titre} » ({motif})')
