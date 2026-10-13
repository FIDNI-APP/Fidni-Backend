"""Quiz de chapitre côté élève (13/10/2026) : questions disponibles à son niveau, tirage qui couvre les théorèmes,
bilan « maîtrisé / à revoir » par théorème.

- Disponible : question active, validée (a_relire=False), et, si le chapitre est au programme du niveau de l’élève,
  dont chaque théorème est au programme de ce niveau
  (Theorem.class_levels ; un théorème sans niveau vaut pour tous ; élève sans niveau : tout).
  « Limites et continuité » sert la SM et la PC/SVT : une question sur arc tangente n'est servie qu'en SM.
- Tirage (QUESTIONS_PAR_QUIZ) : d'abord une question par théorème du chapitre (dans un ordre au hasard), puis le
  reste au hasard ; ordre final mélangé. Un chapitre de 10 théorèmes au plus est donc évalué en entier à chaque
  passage.
- Bilan : par théorème, justes / total et pourcentage (100 % = toutes ses questions justes) ; « non évalués » =
  théorèmes ayant des questions disponibles mais absents de ce tirage (chapitre de plus de 10 théorèmes) ;
  chapitre maîtrisé = tous les théorèmes évalués à 100 % et aucun non évalué.
"""
import random
from collections import defaultdict

from .models import SkillQuestion

QUESTIONS_PAR_QUIZ = 10


def niveau_de(user):
    return getattr(getattr(user, 'profile', None), 'class_level', None)


def disponibles(niveau, chapter_id=None):
    """Questions servables à un élève de ce niveau (avec leurs théorèmes préchargés).

    Le filtre des théorèmes ne joue que si le chapitre est au programme de l'élève (chapitre partagé SM et PC/SVT) :
    un élève de 2ème Bac qui ouvre le quiz de Logique (1ère Bac SM) voit toutes ses questions, même si De Morgan
    n'est rattaché qu'à la 1ère Bac SM."""
    qs = (SkillQuestion.objects.filter(is_active=True, a_relire=False)
          .prefetch_related('theorems__class_levels', 'chapter__class_levels'))
    if chapter_id is not None:
        qs = qs.filter(chapter_id=chapter_id)
    out = []
    for q in qs:
        if (niveau is not None and niveau.id in {lv.id for lv in q.chapter.class_levels.all()} and any(
                th.class_levels.all() and niveau.id not in {lv.id for lv in th.class_levels.all()}
                for th in q.theorems.all())):
            continue
        out.append(q)
    return out


def tirer(questions, n=QUESTIONS_PAR_QUIZ):
    """Une question par théorème d'abord, puis au hasard ; au plus n, ordre mélangé."""
    pool = list(questions)
    random.shuffle(pool)
    par_theoreme = defaultdict(list)
    for q in pool:
        for th in q.theorems.all():
            par_theoreme[th.id].append(q)
    theoremes = list(par_theoreme)
    random.shuffle(theoremes)
    choisies, couverts = [], set()
    for th in theoremes:
        if len(choisies) >= n or th in couverts:
            continue
        q = next((x for x in par_theoreme[th] if x not in choisies), None)
        if q is not None:
            choisies.append(q)
            couverts |= {t.id for t in q.theorems.all()}
    choisies += [q for q in pool if q not in choisies][:n - len(choisies)]
    random.shuffle(choisies)
    return choisies


def bilan(questions, answers, pool=()):
    """{'theoremes': [{id, name, justes, total, pct}] du moins au mieux maîtrisé, 'non_evalues': [{id, name}],
    'a_revoir': [noms], 'complet': bool} pour les questions corrigées ; `pool` = questions disponibles du chapitre."""
    stats = {}
    for q in questions:
        juste = answers.get(str(q.id)) == q.correct_answer
        for th in q.theorems.all():
            s = stats.setdefault(th.id, {'id': th.id, 'name': th.name, 'justes': 0, 'total': 0})
            s['total'] += 1
            s['justes'] += juste
    lignes = [dict(s, pct=round(100 * s['justes'] / s['total'])) for s in stats.values()]
    lignes.sort(key=lambda s: (s['pct'], s['name']))
    absents = {}
    for q in pool:
        for th in q.theorems.all():
            if th.id not in stats:
                absents[th.id] = {'id': th.id, 'name': th.name}
    non_evalues = sorted(absents.values(), key=lambda t: t['name'])
    return {'theoremes': lignes, 'non_evalues': non_evalues,
            'a_revoir': [s['name'] for s in lignes if s['pct'] < 100],
            'complet': bool(lignes) and all(s['pct'] == 100 for s in lignes) and not non_evalues}
