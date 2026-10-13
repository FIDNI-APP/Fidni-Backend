"""Quiz de chapitre côté élève (13/10/2026) : un quiz par (chapitre, niveau), tirage qui couvre les théorèmes,
bilan « maîtrisé / à revoir » par théorème.

- Niveau du quiz : celui que l'élève a choisi (?niveau=, barre de niveaux de la page), sinon le sien. Les quiz ne sont
  jamais partagés entre deux niveaux : « Limites et continuité » 2ème Bac SM (avec arc tangente) et 2ème Bac PC/SVT
  (sans) sont deux quiz distincts (SkillQuestion.class_level).
- Disponible : question active, validée (a_relire=False), du niveau du quiz.
- Tirage (QUESTIONS_PAR_QUIZ, 30 : en pratique toutes les questions du quiz) : d'abord une question par théorème
  (dans un ordre au hasard), puis le reste ; ordre final mélangé. Chaque théorème est donc évalué à chaque passage.
- Bilan : par théorème, justes / total et pourcentage (100 % = toutes ses questions justes) ; « non évalués » =
  théorèmes ayant des questions disponibles mais absents de ce tirage (plus de 30 théorèmes) ;
  chapitre maîtrisé = tous les théorèmes évalués à 100 % et aucun non évalué.
"""
import random
from collections import defaultdict

from .models import SkillQuestion

QUESTIONS_PAR_QUIZ = 30  # 13/10/2026 : toutes les questions du quiz (30 au plus), au lieu de 10 au hasard


def niveau_de(user):
    return getattr(getattr(user, 'profile', None), 'class_level', None)


def niveau_demande(request):
    """Niveau du quiz : ?niveau= (ou « niveau » dans le corps), sinon celui de l'élève ; None s'il n'en a pas."""
    from apps.caracteristics.models import ClassLevel
    brut = request.query_params.get('niveau') or (request.data.get('niveau') if hasattr(request, 'data') else None)
    if str(brut or '').isdigit():
        lv = ClassLevel.objects.filter(pk=int(brut)).first()
        if lv is not None:
            return lv
    return niveau_de(request.user)


def disponibles(niveau, chapter_id=None):
    """Questions servables du quiz de ce niveau (avec leurs théorèmes préchargés) ; aucun niveau : aucune."""
    if niveau is None:
        return []
    qs = (SkillQuestion.objects.filter(is_active=True, a_relire=False, class_level=niveau)
          .prefetch_related('theorems'))
    if chapter_id is not None:
        qs = qs.filter(chapter_id=chapter_id)
    return list(qs)


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
    'a_revoir': [noms], 'complet': bool} pour les questions corrigées ; `pool` = questions disponibles du quiz."""
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
