"""Faire savoir aux élèves qu'un quiz est sorti (13/10/2026). Un quiz = (chapitre, niveau).

- Notification (cloche, kind « quiz ») aux membres réels de ce niveau, au moment où le quiz (chapitre, niveau) passe en
  ligne (il ne l'était pas) ; une seule par membre et par quiz (`target` « quiz:<chapitre>:<niveau> »), même si le quiz
  est retiré puis remis.
- « Nouveau » sur la page des quiz : quiz dont la première mise en ligne (SkillQuestion.en_ligne_le) date de moins de
  NOUVEAU_JOURS jours (GET /api/skill-assessments/nouveaux/).
"""
from datetime import timedelta

from django.db.models import Min
from django.utils import timezone

from .models import SkillQuestion

NOUVEAU_JOURS = 14


def marquer_en_ligne(qs):
    """Date de première mise en ligne des questions qui n'en ont pas encore."""
    return qs.filter(en_ligne_le__isnull=True).update(en_ligne_le=timezone.now())


def annoncer(chapitre, niveau):
    """Notifie les élèves de ce niveau que le quiz (chapitre, niveau) est en ligne ; renvoie le nombre de notifications."""
    from django.contrib.auth.models import User
    from apps.notifications.models import Notification
    from apps.users.admin_dashboard import _house_filter

    if niveau is None:
        return 0
    cible = f'quiz:{chapitre.id}:{niveau.id}'
    deja = set(Notification.objects.filter(target=cible).values_list('recipient_id', flat=True))
    eleves = list(User.objects.filter(is_active=True, profile__class_level=niveau)
                  .exclude(_house_filter()).exclude(id__in=deja).values_list('id', flat=True).distinct())
    n = SkillQuestion.objects.filter(chapter=chapitre, class_level=niveau, is_active=True, a_relire=False).count()
    Notification.objects.bulk_create([
        Notification(recipient_id=uid, kind=Notification.KIND_QUIZ, target=cible, title=chapitre.name[:200],
                     link=f'/skill-iq?chapitre={chapitre.id}&niveau={niveau.id}',
                     excerpt=f'{n} question{"s" if n > 1 else ""}')
        for uid in eleves
    ], batch_size=500)
    return len(eleves)


def nouveaux():
    """{(chapitre, niveau): date de première mise en ligne} des quiz sortis il y a moins de NOUVEAU_JOURS jours."""
    depuis = timezone.now() - timedelta(days=NOUVEAU_JOURS)
    rows = (SkillQuestion.objects.filter(is_active=True, a_relire=False, en_ligne_le__isnull=False,
                                         class_level__isnull=False)
            .values('chapter_id', 'class_level_id').annotate(debut=Min('en_ligne_le')).filter(debut__gte=depuis))
    return {(r['chapter_id'], r['class_level_id']): r['debut'] for r in rows}
