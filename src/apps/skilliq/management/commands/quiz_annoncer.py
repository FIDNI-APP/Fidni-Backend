"""Prévient (cloche) les élèves des quiz déjà en ligne, une fois : skilliq/annonces.py. Rejouable sans doublon."""
from django.core.management.base import BaseCommand

from apps.caracteristics.models import Chapter, ClassLevel
from apps.skilliq.annonces import annoncer
from apps.skilliq.models import SkillQuestion


class Command(BaseCommand):
    help = "Notifie les élèves du niveau de chaque quiz en ligne (une seule notification par élève et par quiz)."

    def handle(self, **options):
        total = 0
        quiz = (SkillQuestion.objects.filter(is_active=True, a_relire=False, class_level__isnull=False)
                .values_list('chapter_id', 'class_level_id').distinct())
        chapitres = Chapter.objects.in_bulk({c for c, _ in quiz})
        niveaux = ClassLevel.objects.in_bulk({lv for _, lv in quiz})
        for ch_id, lv_id in sorted(set(quiz)):
            n = annoncer(chapitres[ch_id], niveaux[lv_id])
            total += n
            self.stdout.write(f'{chapitres[ch_id].name} ({niveaux[lv_id].name}) : {n} élève(s) prévenu(s)')
        self.stdout.write(f'{total} notification(s) créée(s).')
