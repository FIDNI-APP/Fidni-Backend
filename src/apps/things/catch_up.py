"""« Tu as ouvert N exercices sans dire si tu les as réussis » : bandeau en haut de la liste « Pour toi ».

Contenus (exercices ou examens) qu'un élève a ouverts ces 30 derniers jours ET sur lesquels il a vraiment
travaillé (au moins 2 minutes, solution regardée ou une question déjà évaluée), sans avoir dit s'il les a
réussis (ni « Réussi » ni « À revoir »). Les plus récemment ouverts d'abord.

« Pas encore fait » (ou bandeau fermé) : CatchUpSkip. Le contenu n'est plus demandé, sauf si l'élève y
retravaille APRÈS (temps d'étude un jour suivant, question évaluée, solution regardée) : là, il peut juger.
"""
from collections import Counter
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django.utils import timezone

DAYS = 30
MIN_SECONDS = 120
LIMIT = 5


def pending(user, kind, exclude=()):
    """(nombre total, [cartes]) des contenus de ce type à évaluer, `LIMIT` cartes au plus.
    `exclude` : ids à écarter en plus (ancienne version du bandeau, qui les gardait dans le navigateur)."""
    from apps.interactions.models import Complete, QuestionProgress, SolutionView, StudyTimeDay
    from apps.things.models import CatchUpSkip, Content
    from apps.users.models import ViewHistory
    from apps.users.my_stats import _questions

    ct = ContentType.objects.get_for_model(Content)
    seen = dict(ViewHistory.objects.filter(user=user, content_type=ct, viewed_at__gte=timezone.now() - timedelta(days=DAYS))
                .values_list('object_id', 'viewed_at'))
    # Complete.object_id est un CharField : ids en chaîne (CLAUDE.md).
    decided = {int(o) for o in Complete.objects.filter(user=user, content_type=ct).values_list('object_id', flat=True)
               if str(o).isdigit()}
    ids = set(seen) - decided - set(exclude)
    if not ids:
        return 0, []
    worked = set(StudyTimeDay.objects.filter(user=user, object_id__in=ids).values('object_id')
                 .annotate(s=Sum('seconds')).filter(s__gte=MIN_SECONDS).values_list('object_id', flat=True))
    worked |= set(SolutionView.objects.filter(user=user, content_type=ct, object_id__in=ids).values_list('object_id', flat=True))
    assessed = Counter(QuestionProgress.objects.filter(user=user, content_type=ct, object_id__in=ids)
                       .values_list('object_id', flat=True))
    worked |= set(assessed)

    # « Pas encore fait » : redemandé seulement s'il y a retravaillé depuis.
    skipped = dict(CatchUpSkip.objects.filter(user=user, content_id__in=worked).values_list('content_id', 'created_at'))
    if skipped:
        again = set()
        for cid, when in QuestionProgress.objects.filter(user=user, content_type=ct, object_id__in=skipped).values_list(
                'object_id', 'assessed_at'):
            if when > skipped[cid]:
                again.add(cid)
        for cid, when in SolutionView.objects.filter(user=user, content_type=ct, object_id__in=skipped).values_list(
                'object_id', 'viewed_at'):
            if when > skipped[cid]:
                again.add(cid)
        for cid, day in StudyTimeDay.objects.filter(user=user, object_id__in=skipped).values_list('object_id', 'date'):
            if day > timezone.localtime(skipped[cid]).date():
                again.add(cid)
        worked -= set(skipped) - again
    contents = sorted(Content.objects.filter(id__in=worked, type=kind).exclude(author=user).prefetch_related('chapters'),
                      key=lambda c: seen[c.id], reverse=True)
    cards = []
    for c in contents[:LIMIT]:
        chapter = next(iter(c.chapters.all()), None)
        cards.append({
            'id': c.id, 'title': c.title, 'type': c.type, 'difficulty': c.difficulty,
            'chapter': chapter.name if chapter else None, 'seen_at': seen[c.id],
            # Questions à cocher « réussies » d'un coup, comme « Tout réussi » sur la page du contenu.
            'paths': [path for path, _, _ in _questions(c.json_content)],
            'assessed': assessed.get(c.id, 0),
        })
    return len(contents), cards
