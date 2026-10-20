"""Une copie corrigée par l'IA remplit l'auto-évaluation de l'élève (20/10/2026).

Quand un élève fait corriger sa propre copie d'un devoir (solo.py), chaque question prend le statut que l'IA lui a
donné — « réussi » (tous les points), « partiel » (une partie) ou « à revoir » (aucun point) — exactement comme s'il
avait cliqué lui-même sous la question : QuestionProgress, journal de « Ma progression », statistiques du devoir. Si
toutes les questions sont notées, le résultat du devoir (« Où en es-tu ? ») suit : réussi si tout l'est, à revoir sinon.
"""
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from .bareme import notes_finales, questions


def statuts(evaluation, copie, qs=None):
    """{chemin: 'success' | 'partial' | 'review'} pour les questions notées."""
    qs = qs if qs is not None else questions(evaluation.sujet, evaluation.maxima)
    notes = notes_finales(evaluation, copie, qs)
    out = {}
    for q in qs:
        pts = notes[q['chemin']]['points']
        if pts is None or not q['max']:
            continue
        out[q['chemin']] = 'success' if pts >= q['max'] else 'review' if pts <= 0 else 'partial'
    return out


def appliquer(copie):
    """Écrit les statuts de la copie dans l'auto-évaluation de son élève ; sans effet pour une copie de classe."""
    e = copie.evaluation
    if e.classroom_id is not None or not e.content_id or not copie.eleve_id:
        return
    from apps.interactions import journal
    from apps.interactions.models import Complete, QuestionProgress
    from apps.things.models import Content
    from apps.things.views import _forget_stats

    qs = questions(e.sujet, e.maxima)
    changes = statuts(e, copie, qs)
    if not changes:
        return
    ct = ContentType.objects.get_for_model(Content)
    mine = dict(user=copie.eleve, content_type=ct, object_id=e.content_id)
    with transaction.atomic():
        before = dict(QuestionProgress.objects.filter(question_path__in=list(changes), **mine)
                      .values_list('question_path', 'status'))
        for path, st in changes.items():
            defaults = {'status': st} if before.get(path) == st else {'status': st, 'source': 'question'}
            QuestionProgress.objects.update_or_create(question_path=path, defaults=defaults, **mine)
        if len(changes) == len(qs):
            Complete.objects.update_or_create(
                defaults={'status': 'success' if all(s == 'success' for s in changes.values()) else 'review'}, **mine)
        journal.record(copie.eleve, e.content_id, changes, before, 'question')
    _forget_stats(e.content_id, copie.eleve_id)
