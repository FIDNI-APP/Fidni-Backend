"""Ressenti des élèves sur la difficulté (10/10/2026) : « Moyen · ressenti Difficile ».

La difficulté annoncée (Content.difficulty) ne change jamais toute seule : on affiche EN PLUS ce que les
élèves ont vécu, d'après leurs résultats et leurs avis. Comptes maison et auteur du contenu exclus.

Réussite R d'un contenu (exercice ou examen) :
- par élève, (réussies + ½ « en partie ») / évaluées, s'il a évalué au moins la moitié des questions finales
  (my_stats._questions) ; sinon son « Réussi » (1) ou « À revoir » (0,25) ;
- poids ½ si toutes ses évaluations viennent de « Tout réussi » en un clic (QuestionProgress.source='tout') ;
- R = moyenne pondérée ; n = nombre d'élèves retenus.
Bandes : facile R ≥ 0,70 · moyen 0,40–0,70 · difficile R < 0,40.

Ressenti, dans cet ordre :
1. au moins 5 avis (DifficultyFeedback, donnés sur la difficulté affichée aujourd'hui) et
   |(plus dur − plus facile) / avis| ≥ 0,4 → un niveau au-dessus ou au-dessous de l'annonce (basis 'avis') ;
   s'il n'y a pas de niveau au-delà (« plus dur » sur un Difficile), on passe à la règle 2 ;
2. au moins 8 élèves et l'intervalle de Wilson à 80 % de R entièrement hors de la bande annoncée → la bande
   de R (basis 'reussite') ;
3. sinon « comme annoncé » (basis 'annonce').
Pas assez de données (n < 8 et moins de 5 avis) → None. Le temps n'entre pas en compte (chrono facultatif).

Calcul en lot, gardé 6 h par contenu (aucune tâche planifiée) ; un avis donné vide le cache du contenu.
"""
import math
from collections import defaultdict

from django.core.cache import cache

LEVELS = ['easy', 'medium', 'hard']
KINDS = ('exercise', 'exam')
SCORE = {'success': 1.0, 'partial': 0.5, 'review': 0.0, 'failed': 0.0}
COMPLETE_SCORE = {'success': 1.0, 'review': 0.25}
EASY_FROM, HARD_BELOW = 0.70, 0.40
BANDS = {'easy': (EASY_FROM, math.inf), 'medium': (HARD_BELOW, EASY_FROM), 'hard': (-math.inf, HARD_BELOW)}
Z80 = 1.2816  # intervalle de confiance à 80 %
MIN_STUDENTS, MIN_VOTES, VOTE_SHIFT = 8, 5, 0.4
TTL = 6 * 3600


def band(r):
    return 'easy' if r >= EASY_FROM else 'medium' if r >= HARD_BELOW else 'hard'


def wilson(p, n, z=Z80):
    """Intervalle de Wilson (bas, haut) d'une proportion p observée sur n (n peut être pondéré)."""
    if n <= 0:
        return 0.0, 1.0
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def _outside(lo, hi, declared):
    start, end = BANDS[declared]
    return hi < start or lo >= end


def _key(content_id, declared):
    # La difficulté annoncée fait partie de la clé : corrigée par un administrateur, le ressenti est recalculé.
    return f'felt:v1:{content_id}:{declared or "-"}'


def forget(content):
    """Après un avis : le ressenti de ce contenu sera recalculé à la prochaine lecture."""
    cache.delete(_key(content.id, content.difficulty))


def _finals(contents, store=True):
    """{id: {chemins des questions finales}} ; l'énoncé déjà chargé sert tel quel, sinon l'index en cache
    (things/question_index.py), ou l'énoncé relu quand rien ne doit être écrit en cache (store=False)."""
    from apps.things.models import Content
    from apps.things.question_index import question_index
    from apps.users.my_stats import _questions
    out, deferred = {}, []
    for c in contents:
        if 'json_content' in c.get_deferred_fields():
            deferred.append(c)
        else:
            out[c.id] = {path for path, _, _ in _questions(c.json_content)}
    if deferred:
        if store and not any('updated_at' in c.get_deferred_fields() for c in deferred):
            rows = question_index(deferred).items()
        else:
            rows = ((cid, _questions(js)) for cid, js in
                    Content.objects.filter(id__in=[c.id for c in deferred]).values_list('id', 'json_content'))
        for cid, questions in rows:
            out[cid] = {path for path, _, _ in questions}
    return out


def _compute(contents, store=True):
    """Ressenti de contenus (exercices / examens) absents du cache : 5 requêtes pour tout le lot."""
    from django.contrib.auth.models import User
    from django.contrib.contenttypes.models import ContentType
    from apps.interactions.models import Complete, QuestionProgress
    from apps.things.models import Content, DifficultyFeedback
    from apps.users.admin_dashboard import _house_filter

    ct = ContentType.objects.get_for_model(Content)
    ids = [c.id for c in contents]
    house = set(User.objects.filter(_house_filter()).values_list('id', flat=True))
    authors = dict(Content.objects.filter(id__in=ids).values_list('id', 'author_id'))  # objets parfois partiels
    declared = {c.id: c.difficulty for c in contents}
    finals = _finals(contents, store)

    def counted(cid, uid):
        return uid not in house and uid != authors.get(cid)

    rows = defaultdict(lambda: defaultdict(list))  # contenu → élève → [(statut, source)]
    for cid, uid, path, st, src in (QuestionProgress.objects.filter(content_type=ct, object_id__in=ids)
                                    .values_list('object_id', 'user_id', 'question_path', 'status', 'source')):
        if st in SCORE and path in finals.get(cid, ()) and counted(cid, uid):
            rows[cid][uid].append((st, src))
    # Complete.object_id est un CharField : ids en chaîne (CLAUDE.md).
    done = defaultdict(dict)
    for oid, uid, st in (Complete.objects.filter(content_type=ct, object_id__in=[str(i) for i in ids])
                         .values_list('object_id', 'user_id', 'status')):
        if str(oid).isdigit() and counted(int(oid), uid) and st in COMPLETE_SCORE:
            done[int(oid)][uid] = st
    votes = {cid: {'easier': 0, 'as_said': 0, 'harder': 0} for cid in ids}
    for cid, uid, felt, decl in (DifficultyFeedback.objects.filter(content_id__in=ids)
                                 .values_list('content_id', 'user_id', 'felt', 'declared')):
        # Un avis donné sur une autre difficulté affichée (corrigée depuis) ne compte plus.
        if counted(cid, uid) and decl == declared[cid] and felt in votes[cid]:
            votes[cid][felt] += 1

    out = {}
    for cid in ids:
        need = max(1, math.ceil(len(finals.get(cid, ())) / 2))
        n, weights, weighted = 0, 0.0, 0.0
        for uid in set(rows[cid]) | set(done[cid]):
            mine = rows[cid].get(uid, [])
            if finals.get(cid) and len(mine) >= need:
                score = sum(SCORE[st] for st, _ in mine) / len(mine)
                weight = 0.5 if all(src == 'tout' for _, src in mine) else 1.0
            elif uid in done[cid]:
                score, weight = COMPLETE_SCORE[done[cid][uid]], 1.0
            else:
                continue
            n += 1
            weights += weight
            weighted += weight * score
        out[cid] = _verdict(declared[cid], n, weights, weighted / weights if weights else None, votes[cid])
    return out


def _verdict(declared, n, weights, r, votes):
    n_votes = sum(votes.values())
    if n < MIN_STUDENTS and n_votes < MIN_VOTES:
        return None
    level, basis = declared, 'annonce'
    shifted = None
    if declared in LEVELS and n_votes >= MIN_VOTES and abs(votes['harder'] - votes['easier']) / n_votes >= VOTE_SHIFT:
        step = 1 if votes['harder'] > votes['easier'] else -1
        shifted = LEVELS[min(2, max(0, LEVELS.index(declared) + step))]
    if shifted and shifted != declared:
        level, basis = shifted, 'avis'
    # « Plus dur » sur un Difficile (ou « plus facile » sur un Facile) ne décale rien : les résultats décident.
    elif n >= MIN_STUDENTS and r is not None:
        lo, hi = wilson(r, weights)  # « Tout réussi » pèse moitié, dans la moyenne comme dans la confiance
        if declared not in LEVELS or _outside(lo, hi, declared):
            level, basis = band(r), 'reussite'
    if level not in LEVELS:
        return None  # sans difficulté annoncée, seuls les résultats peuvent la dire
    return {
        'level': level,
        'declared': declared if declared in LEVELS else None,
        'differs': declared in LEVELS and level != declared,
        'n': n,
        'success_pct': round(r * 100) if r is not None else None,
        'votes': dict(votes),
        'basis': basis,
    }


def felt_for(contents, store=True):
    """{id: ressenti | None} pour des contenus (objets Content avec type et difficulty, ou ids). Leçons : None.
    store=False : rien n'est écrit en cache (commande d'audit en lecture seule)."""
    from apps.things.models import Content
    items = list(contents)
    ids = [c for c in items if isinstance(c, int)]
    objs = [c for c in items if not isinstance(c, int)]
    if ids:
        objs += list(Content.objects.filter(id__in=ids).defer('json_content', 'search_text'))
    keys = {c.id: _key(c.id, c.difficulty) for c in objs if c.type in KINDS}
    found = cache.get_many(list(keys.values())) if keys else {}
    out, missing = {}, []
    for c in objs:
        if c.id not in keys:
            out[c.id] = None
        elif keys[c.id] in found:
            out[c.id] = found[keys[c.id]]['v']
        else:
            missing.append(c)
    if missing:
        fresh = _compute(missing, store)
        out.update(fresh)
        if store:
            cache.set_many({keys[cid]: {'v': value} for cid, value in fresh.items()}, TTL)
    return out


def difficulty_gaps(limit=60):
    """Contenus dont le ressenti diffère de l'annonce (Pilotage › À traiter), le plus gros écart d'abord,
    puis le plus d'élèves : [{content, declared, felt, n, success_pct, votes, basis}]."""
    from django.contrib.contenttypes.models import ContentType
    from apps.interactions.models import Complete, QuestionProgress
    from apps.things.models import Content, DifficultyFeedback

    ct = ContentType.objects.get_for_model(Content)
    touched = set(DifficultyFeedback.objects.values_list('content_id', flat=True).distinct())
    touched |= set(QuestionProgress.objects.filter(content_type=ct).values_list('object_id', flat=True).distinct())
    touched |= {int(o) for o in Complete.objects.filter(content_type=ct).values_list('object_id', flat=True).distinct()
                if str(o).isdigit()}
    contents = list(Content.objects.filter(id__in=touched, type__in=KINDS, difficulty__in=LEVELS)
                    .defer('json_content', 'search_text'))
    felt = {}
    for i in range(0, len(contents), 200):
        felt.update(felt_for(contents[i:i + 200]))
    gaps = []
    for c in contents:
        f = felt.get(c.id)
        if f and f['differs']:
            gaps.append({'content': c, 'declared': f['declared'], 'felt': f['level'], 'n': f['n'],
                         'success_pct': f['success_pct'], 'votes': f['votes'], 'basis': f['basis']})
    gaps.sort(key=lambda g: (-abs(LEVELS.index(g['felt']) - LEVELS.index(g['declared'])), -g['n'], g['content'].id))
    return gaps[:limit]
