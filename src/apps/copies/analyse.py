"""Points faibles d'une copie et bilan de la classe pour une évaluation."""
import statistics
from collections import defaultdict

from apps.caracteristics import theoremes as TH

from .bareme import notes_finales, questions, total

SEUIL_FAIBLE = 0.5  # réussite d'un théorème sous laquelle il devient un point faible
POINTS_FAIBLES_MAX = 6


def _niveau(evaluation):
    lvl = evaluation.classroom.class_level
    if lvl is None and evaluation.content_id:
        lvl = evaluation.content.class_levels.order_by('id').first() if evaluation.content else None
    return lvl


def _chapitre(nom, niveau):
    """Chapitre du théorème (dans le niveau de la classe si possible) et lien vers ses exercices."""
    from apps.caracteristics.hubs import hub_url
    from apps.caracteristics.models import Chapter
    th = TH.index().get(TH.cle(nom))
    if not th or not th['chapters']:
        return None
    chs = list(Chapter.objects.filter(id__in=th['chapters']))
    if niveau is not None:
        chs.sort(key=lambda c: 0 if c.class_levels.filter(id=niveau.id).exists() else 1)
    ch = chs[0] if chs else None
    if ch is None:
        return None
    return {'id': ch.id, 'nom': ch.name, 'url': hub_url('exercises', niveau, ch) if niveau is not None else None}


def par_theoreme(qs, notes):
    """{théorème: [points, max, [labels des questions]]} sur les questions notées."""
    acc = defaultdict(lambda: [0.0, 0.0, []])
    for q in qs:
        n = notes.get(q['chemin']) or {}
        if n.get('points') is None or not q['max']:
            continue
        for nom in q['theoremes']:
            a = acc[nom]
            a[0] += n['points']
            a[1] += q['max']
            if n['points'] < q['max']:
                a[2].append(q['label'])
    return acc


def points_faibles(evaluation, copie, qs=None):
    """Théorèmes de l'évaluation réussis à moins de 50 %, les moins réussis d'abord, avec leur chapitre."""
    qs = qs if qs is not None else questions(evaluation.sujet, evaluation.maxima)
    acc = par_theoreme(qs, notes_finales(evaluation, copie, qs))
    rows = sorted(((pts / mx, nom, labels) for nom, (pts, mx, labels) in acc.items()
                   if mx and pts / mx < SEUIL_FAIBLE), key=lambda r: (r[0], r[1]))
    niveau = _niveau(evaluation)
    return [{'theoreme': nom, 'taux': round(taux * 100), 'questions': labels, 'chapitre': _chapitre(nom, niveau)}
            for taux, nom, labels in rows[:POINTS_FAIBLES_MAX]]


def rapport(evaluation):
    """Bilan de la classe sur les copies validées : notes, répartition, réussite par question et par théorème."""
    qs = questions(evaluation.sujet, evaluation.maxima)
    copies = list(evaluation.copies.filter(statut='validee'))
    sur = evaluation.note_sur or 20
    notes, par_q, th = [], defaultdict(list), defaultdict(lambda: [0.0, 0.0])
    for c in copies:
        _pts, _maxi, note = total(evaluation, c, qs)
        if note is None:
            continue
        notes.append(note)
        fin = notes_finales(evaluation, c, qs)
        for q in qs:
            n = fin[q['chemin']]
            if n['points'] is not None and q['max']:
                par_q[q['chemin']].append(n['points'] / q['max'])
        for nom, (pts, mx, _l) in par_theoreme(qs, fin).items():
            th[nom][0] += pts
            th[nom][1] += mx
    # Répartition des notes par tranches de 2 points (sur 20 : 0-2, 2-4… 18-20).
    largeur = sur / 10
    tranches = [0] * 10
    for n in notes:
        tranches[min(9, int(n // largeur))] += 1
    resume = None
    if notes:
        resume = {
            'moyenne': round(statistics.mean(notes), 2), 'mediane': round(statistics.median(notes), 2),
            'min': min(notes), 'max': max(notes),
            'ecart_type': round(statistics.pstdev(notes), 2) if len(notes) > 1 else 0,
            'au_dessus_moyenne': sum(1 for n in notes if n >= sur / 2),
        }
    faibles = sorted(((pts / mx, nom) for nom, (pts, mx) in th.items() if mx), key=lambda r: (r[0], r[1]))[:5]
    niveau = _niveau(evaluation)
    return {
        'copies_validees': len(notes),
        'copies_total': evaluation.copies.exclude(statut='vide').count(),
        'note_sur': sur,
        'resume': resume,
        'repartition': [{'de': round(i * largeur, 2), 'a': round((i + 1) * largeur, 2), 'n': k}
                        for i, k in enumerate(tranches)],
        'questions': [{'chemin': q['chemin'], 'label': q['label'], 'max': q['max'],
                       'reussite': round(100 * statistics.mean(par_q[q['chemin']])) if par_q[q['chemin']] else None}
                      for q in qs],
        'theoremes_faibles': [{'theoreme': nom, 'taux': round(t * 100), 'chapitre': _chapitre(nom, niveau)}
                              for t, nom in faibles],
    }
