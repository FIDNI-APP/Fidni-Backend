"""Journal des auto-évaluations et des aides ouvertes (13/10/2026), pour « Ma progression » (apps/users/maitrise.py).

QuestionProgress garde l'état courant d'une question ; AssessmentEvent garde chaque changement daté, avec l'aide
ouverte juste avant (indication, solution, ou aucune). Seul ce module y écrit :
- record() : appelé par les vues d'évaluation (things/views.py : assess_question, assess_many, remove_assessment),
  dans leur transaction. Un clic corrigé dans les 5 minutes est fusionné (revenir à l'état d'avant l'annule) ; le
  même statut redonné moins de 20 h après n'ajoute rien, au-delà c'est une nouvelle observation.
- record_help() : POST /api/contents/<id>/aide/ (indication ou solution ouverte), une ligne par question et par jour.

Champ `aide` d'un événement : 'solution' si l'élève a répondu sous la solution ouverte (source « apres_solution ») ou
l'avait ouverte depuis sa dernière évaluation de la question (7 jours au plus), 'indice' pour une indication, '' si
aucune aide n'est enregistrée. None (inconnue) est réservé aux évaluations reprises de l'existant (migration 0024) :
une aide inconnue n'est jamais comptée comme « sans aide ».
"""
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import F, Max
from django.utils import timezone

from .models import AssessmentEvent, QuestionHelp, SolutionView

FUSION = timedelta(minutes=5)
RECONFIRM = timedelta(hours=20)
AIDE_FENETRE = timedelta(days=7)
TOUT = '*'  # question_path d'une aide qui vaut pour tout le contenu (toutes les solutions, solution d'ensemble)
AIDES = ('indice', 'solution')


def _forget(user_id):
    from apps.users.maitrise import forget
    forget(user_id)


def _aide(path, source, helps, depuis, now):
    """Aide ouverte avant cette évaluation : 'solution' > 'indice' > ''."""
    if source == 'apres_solution':
        return 'solution'
    seuil = max(depuis, now - AIDE_FENETRE) if depuis else now - AIDE_FENETRE
    kinds = {kind for p, kind, first, last in helps if p in (path, TOUT) and first <= now and last >= seuil}
    return 'solution' if 'solution' in kinds else 'indice' if 'indice' in kinds else ''


def record(user, content_id, changes, before, source='question'):
    """changes {chemin: statut | None (retirée)}, before {chemin: statut d'avant | None}. À appeler dans la
    transaction de la vue, après l'écriture de QuestionProgress."""
    paths = [p for p in changes if isinstance(p, str) and p]
    if not paths:
        return
    now = timezone.now()
    mine = AssessmentEvent.objects.filter(user=user, object_id=content_id, question_path__in=paths)
    recent = {}
    for ev in mine.filter(at__gte=now - RECONFIRM).order_by('at', 'id'):
        recent[ev.question_path] = ev  # le dernier gagne
    last_at = dict(mine.values('question_path').annotate(m=Max('at')).values_list('question_path', 'm'))
    helps = list(QuestionHelp.objects.filter(user=user, object_id=content_id, last_at__gte=now - AIDE_FENETRE)
                 .values_list('question_path', 'kind', 'first_at', 'last_at'))
    new = []
    for path in paths:
        st = changes[path] or None
        prev = before.get(path) or None
        aide = None if st is None else _aide(path, source, helps, last_at.get(path), now)
        ev = recent.get(path)
        if st == prev:
            # Même statut redonné : rien de neuf s'il vient d'être observé, sinon une nouvelle observation.
            if st is not None and ev is None:
                new.append(AssessmentEvent(user=user, object_id=content_id, question_path=path, status=st,
                                           previous=prev, source=source, aide=aide, at=now))
            continue
        if ev is not None and not ev.reprise and now - ev.at < FUSION:
            # Clic corrigé aussitôt : on garde une seule observation (aucune si l'on revient à l'état d'avant).
            if st == (ev.previous or None):
                ev.delete()
            else:
                ev.status, ev.source, ev.aide, ev.at = st, source, aide, now
                ev.save(update_fields=['status', 'source', 'aide', 'at'])
            continue
        new.append(AssessmentEvent(user=user, object_id=content_id, question_path=path, status=st,
                                   previous=prev, source=source, aide=aide, at=now))
    if new:
        AssessmentEvent.objects.bulk_create(new)
    _forget(user.id)


def record_help(user, content, path, kind):
    """Indication ou solution ouverte (une ligne par question, type et jour). Une solution d'ensemble ou « toutes
    les solutions » : path '*'. Une solution ouverte marque aussi le contenu comme « solution vue » (SolutionView)."""
    now = timezone.now()
    row, created = QuestionHelp.objects.get_or_create(
        user=user, object_id=content.id, question_path=path, kind=kind, day=timezone.localdate(now),
        defaults={'first_at': now, 'last_at': now})
    if not created:
        QuestionHelp.objects.filter(pk=row.pk, count__lt=30000).update(last_at=now, count=F('count') + 1)
    if kind == 'solution':
        ct = ContentType.objects.get_for_model(type(content))
        SolutionView.objects.get_or_create(user=user, content_type=ct, object_id=content.id)
