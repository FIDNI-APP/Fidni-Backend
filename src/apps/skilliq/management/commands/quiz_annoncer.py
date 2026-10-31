"""Prévient (cloche) les élèves des quiz déjà en ligne, une fois : skilliq/annonces.py. Rejouable sans doublon.
Un quiz = (chapitre, niveau, type) : le quiz du cours et l'approfondissement s'annoncent chacun une fois."""
from django.core.management.base import BaseCommand

from apps.caracteristics.models import Chapter, ClassLevel
from apps.skilliq.annonces import annoncer
from apps.skilliq.models import APPROFONDISSEMENT, SkillQuestion


class Command(BaseCommand):
    help = "Notifie les élèves du niveau de chaque quiz en ligne (une seule notification par élève et par quiz)."

    def handle(self, **options):
        total = 0
        quiz = (SkillQuestion.objects.filter(is_active=True, a_relire=False, class_level__isnull=False)
                .values_list('chapter_id', 'class_level_id', 'type').distinct())
        chapitres = Chapter.objects.in_bulk({c for c, _, _ in quiz})
        niveaux = ClassLevel.objects.in_bulk({lv for _, lv, _ in quiz})
        for ch_id, lv_id, type_quiz in sorted(set(quiz)):
            n = annoncer(chapitres[ch_id], niveaux[lv_id], type_quiz)
            total += n
            quoi = ' — approfondissement' if type_quiz == APPROFONDISSEMENT else ''
            self.stdout.write(f'{chapitres[ch_id].name} ({niveaux[lv_id].name}){quoi} : {n} élève(s) prévenu(s)')
        self.stdout.write(f'{total} notification(s) créée(s).')
