"""« Pour continuer » : contenus semblables à celui qu'on lit (sous chaque exercice, examen, leçon).

Pas de vecteurs ni d'IA : avec quelques centaines de contenus bien étiquetés, les métadonnées disent
mieux que le texte ce qu'un contenu fait travailler. Score de similarité (cosinus sur des ensembles) :
  notions des questions ×4 (le plus précis ; une notion rare pèse plus qu'une notion présente partout,
  pondération IDF), chapitres ×3, théorèmes ×2,
  sous-domaines ×0,5, difficulté voisine ±0,4, un peu de popularité pour départager.
Toujours le même niveau (un élève de TC ne reçoit pas un sujet de 2ème Bac). Pour un élève connecté,
ce qu'il a déjà réussi passe après le reste. Chaque recommandation dit pourquoi (« Mêmes notions : … »).

« Exercice suivant » après le résultat (`apres`) : après « À revoir », rien de plus difficile et le cours du
chapitre d'abord ; après « Réussi », rien de plus facile. Ce qui ne respecte pas la règle passe en dernier
(jamais de liste vide pour autant).
"""
import math

from django.core.cache import cache

INDEX_KEY = 'similar_index_v1'
INDEX_TTL = 600  # s : un contenu publié apparaît dans les recommandations au plus 10 min après
DIFF = {'easy': 1, 'medium': 2, 'hard': 3}
QUOTA_SAME_TYPE, QUOTA_OTHER_TYPE, LIMIT = 4, 2, 6


def _skills(structure):
    out = set()
    for b in (structure or {}).get('blocks') or []:
        out.update((b.get('meta') or {}).get('skills') or [])
        for sq in b.get('subQuestions') or []:
            out.update((sq.get('meta') or {}).get('skills') or [])
    return out


def _index():
    idx = cache.get(INDEX_KEY)
    if idx is not None:
        return idx
    from apps.things.models import Content
    idx = {}
    qs = Content.objects.prefetch_related('chapters', 'theorems', 'class_levels', 'subfields').only(
        'id', 'type', 'difficulty', 'json_content', 'view_count')
    for c in qs:
        idx[c.id] = {
            'type': c.type, 'diff': DIFF.get(c.difficulty), 'views': c.view_count or 0,
            'levels': {x.id for x in c.class_levels.all()},
            'chapters': {x.id: x.name for x in c.chapters.all()},
            'theorems': {x.id: x.name for x in c.theorems.all()},
            'subfields': {x.id for x in c.subfields.all()},
            'skills': _skills(c.json_content),
        }
    cache.set(INDEX_KEY, idx, INDEX_TTL)
    return idx


def _cos(a, b):
    a, b = set(a), set(b)
    return len(a & b) / math.sqrt(len(a) * len(b)) if a and b else 0.0


def _weighted_cos(a, b, w):
    common = a & b
    if not common:
        return 0.0
    return sum(w[x] ** 2 for x in common) / math.sqrt(sum(w[x] ** 2 for x in a) * sum(w[x] ** 2 for x in b))


def _reason(src, c, w, apres=None):
    from apps.caracteristics.notions import notion_label
    if apres == 'review' and c['type'] == 'lesson':
        ch = [c['chapters'][i] for i in src['chapters'] if i in c['chapters']]
        if ch:
            return 'Revois le cours : ' + ch[0]
    common = sorted(src['skills'] & c['skills'], key=lambda x: (-w[x], x))  # les plus rares d'abord
    if common:
        return 'Mêmes notions : ' + ', '.join(notion_label(s) for s in common[:2]) + (' …' if len(common) > 2 else '')
    ch = [c['chapters'][i] for i in src['chapters'] if i in c['chapters']]
    if ch:
        return 'Même chapitre : ' + ch[0]
    th = [c['theorems'][i] for i in src['theorems'] if i in c['theorems']]
    return ('Utilise aussi : ' + th[0]) if th else 'Même domaine'


def similar(content_id, user=None, apres=None):
    """[(id, score, raison)] des contenus les plus proches, dosés par type (4 du même type, 2 des autres).
    apres : 'review' ou 'success' (« Exercice suivant » après le résultat), voir plus haut."""
    idx = _index()
    src = idx.get(content_id)
    if src is None:
        return []
    done = {}
    if user is not None and user.is_authenticated:
        from django.contrib.contenttypes.models import ContentType
        from apps.interactions.models import Complete
        from apps.things.models import Content
        ct = ContentType.objects.get_for_model(Content)
        done = dict(Complete.objects.filter(user=user, content_type=ct).values_list('object_id', 'status'))
    df = {}
    for c in idx.values():
        for x in c['skills']:
            df[x] = df.get(x, 0) + 1
    w = {x: math.log((len(idx) + 1) / (n + 1)) + 1 for x, n in df.items()}
    scored = []
    for cid, c in idx.items():
        if cid == content_id:
            continue
        if src['levels'] and not (src['levels'] & c['levels']):
            continue  # autre niveau
        notions, chapters = _weighted_cos(src['skills'], c['skills'], w), _cos(src['chapters'], c['chapters'])
        theorems = _cos(src['theorems'], c['theorems'])
        if not (notions or chapters or theorems):
            continue  # rien de commun de précis : pas une recommandation
        s = 4 * notions + 3 * chapters + 2 * theorems + 0.5 * _cos(src['subfields'], c['subfields'])
        if src['diff'] and c['diff']:
            s += {0: 0.4, 1: 0.0, 2: -0.4}[abs(src['diff'] - c['diff'])]
        s += 0.3 * math.log1p(c['views']) / math.log(1000)
        off = False
        if apres == 'review':
            off = bool(src['diff'] and c['diff'] and c['diff'] > src['diff'])
            if c['type'] == 'lesson' and set(src['chapters']) & set(c['chapters']):
                s += 3  # le cours du chapitre d'abord
        elif apres == 'success':
            off = bool(src['diff'] and c['diff'] and c['diff'] < src['diff'])
        # Hors règle, puis déjà réussi : toujours après ce qui reste à faire.
        scored.append((off, done.get(str(cid)) == 'success', -s, cid))
    scored.sort()
    out, per_type = [], {}
    for _, _, s, cid in scored:
        t = idx[cid]['type']
        if per_type.get(t, 0) >= (QUOTA_SAME_TYPE if t == src['type'] else QUOTA_OTHER_TYPE):
            continue
        per_type[t] = per_type.get(t, 0) + 1
        out.append((cid, round(-s, 3), _reason(src, idx[cid], w, apres)))
        if len(out) == LIMIT:
            break
    return out
