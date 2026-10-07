"""« Pour toi » : ordre par défaut des listes d'exercices, de leçons et d'examens.

Avant, la liste était triée par j'aime : les mêmes contenus en tête pour tout le monde, un élève qui
avait fini « Limites et continuité » devait filtrer pour trouver autre chose, un contenu publié la
veille restait en bas, et ce qu'il avait déjà réussi restait en haut.

Score de chaque contenu (tout en Python : quelques centaines de contenus, une dizaine de requêtes) :
  - intérêt de l'élève pour ses chapitres ×3 : ce qu'il a ouvert, réussi, raté, aimé, enregistré,
    chaque signal s'estompant avec le temps (demi-vie 14 jours) ; un chapitre presque entièrement
    réussi intéresse moins (il a « fini » ce chapitre) ;
  - nouveauté : un contenu récent remonte, d'autant plus s'il est dans un chapitre qu'il travaille ;
  - popularité (j'aime − je n'aime pas, vues) pour départager ;
  - autre niveau que le sien : loin derrière ; déjà ouvert : un peu derrière ;
  - « à revoir » (le contenu, ou une de ses questions ratée ou réussie en partie) : en pause 3 jours,
    puis remonte avec « À retravailler » — c'est ce qu'on promet à l'élève quand il clique.
Puis on varie : chaque contenu de plus d'un même chapitre perd un peu, pour que la première page ne
soit pas un seul chapitre. Ce qu'il a déjà réussi passe toujours après tout le reste.
Visiteur : nouveauté + popularité + variété.
"""
import math
from collections import defaultdict

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

HALF_LIFE_DAYS = 14   # un signal d'il y a 2 semaines compte moitié moins
FRESH_DAYS = 10       # la nouveauté s'estompe sur une dizaine de jours
REPEAT_PENALTY = 0.3  # par contenu déjà placé du même chapitre
REVIEW_DELAY_DAYS = 3  # « à revoir » : reproposé au bout de 3 jours (message affiché à l'élève)
SIGNALS = {'view': 1.0, 'review': 3.0, 'success': 1.0, 'like': 2.0, 'save': 2.0, 'dislike': -1.5,
           'assessed': 1.5}


def _days(now, when):
    return max((now - when).total_seconds() / 86400, 0) if when else 0


def _user_signals(user, ct):
    """Pour un élève connecté : {content_id: [(poids, date)]}, statut de réussite par contenu, contenus
    qu'il n'aime pas, et date à laquelle chaque contenu est passé « à revoir »."""
    from apps.interactions.models import Complete, QuestionProgress, Save, Vote
    from apps.users.models import ViewHistory
    signals, status, disliked, review_at = defaultdict(list), {}, set(), {}

    def cid(oid):
        return int(oid) if str(oid).isdigit() else None

    for oid, st, when in Complete.objects.filter(user=user, content_type=ct).values_list(
            'object_id', 'status', 'updated_at'):
        if (i := cid(oid)) is not None:
            status[i] = st
            signals[i].append((SIGNALS.get(st, 0), when))
            if st == 'review':
                review_at[i] = when
    for oid, when, spent in ViewHistory.objects.filter(user=user, content_type=ct).values_list(
            'object_id', 'viewed_at', 'time_spent'):
        # Réussi : le chapitre est fait, la lecture ne compte pas en plus (sinon un chapitre terminé
        # resterait « son » chapitre). Sinon, y passer du temps dit plus qu'un clic (×3 dès 20 min).
        if status.get(oid) != 'success':
            signals[oid].append((SIGNALS['view'] * (1 + min((spent or 0) / 600, 2)), when))
    # Auto-évaluation des questions : un vrai travail sur le contenu (un signal par contenu, le plus récent).
    # Une question ratée ou réussie en partie met le contenu « à revoir » (sauf s'il est réussi depuis).
    last_assessed = {}
    for oid, st, when in QuestionProgress.objects.filter(user=user, content_type=ct).values_list(
            'object_id', 'status', 'assessed_at'):
        last_assessed[oid] = max(when, last_assessed.get(oid, when))
        if st != 'success' and status.get(oid) != 'success':
            review_at[oid] = max(when, review_at.get(oid, when))
    for oid, when in last_assessed.items():
        if status.get(oid) != 'success':  # même raison que pour les lectures
            signals[oid].append((SIGNALS['assessed'], when))
    for oid, value, when in Vote.objects.filter(user=user, content_type=ct).exclude(value=0).values_list(
            'object_id', 'value', 'updated_at'):
        if (i := cid(oid)) is not None:
            signals[i].append((SIGNALS['like'] if value > 0 else SIGNALS['dislike'], when))
            if value < 0:
                disliked.add(i)
    for oid, when in Save.objects.filter(user=user, content_type=ct).values_list('object_id', 'saved_at'):
        if (i := cid(oid)) is not None:
            signals[i].append((SIGNALS['save'], when))
    return signals, status, disliked, review_at


def rank(queryset, user=None):
    """[(id, raison ou None)] : tous les contenus du queryset, du plus recommandé au moins."""
    from apps.caracteristics.models import Chapter
    from apps.things.models import Content

    rows = list(queryset.order_by().values_list(
        'id', 'created_at', 'like_count_annotation', 'dislike_count_annotation', 'view_count'))
    if not rows:
        return []
    ids = [r[0] for r in rows]
    now = timezone.now()
    ct = ContentType.objects.get_for_model(Content)
    authed = user is not None and getattr(user, 'is_authenticated', False)

    signals, status, disliked, review_at, level = {}, {}, set(), {}, None
    if authed:
        signals, status, disliked, review_at = _user_signals(user, ct)
        profile = getattr(user, 'profile', None)
        level = getattr(profile, 'class_level_id', None)

    # Chapitres des contenus listés ET de ceux avec lesquels il a interagi (une leçon lue compte
    # pour la liste des exercices du même chapitre).
    chapters_of = defaultdict(list)
    for c, ch in Content.chapters.through.objects.filter(
            content_id__in=set(ids) | set(signals)).values_list('content_id', 'chapter_id'):
        chapters_of[c].append(ch)
    levels_of = defaultdict(set)
    if level:
        for c, lv in Content.class_levels.through.objects.filter(content_id__in=ids).values_list(
                'content_id', 'classlevel_id'):
            levels_of[c].add(lv)

    # Intérêt par chapitre, chaque signal s'estompant avec le temps.
    interest = defaultdict(float)
    for c, sigs in signals.items():
        chs = chapters_of.get(c)
        if not chs:
            continue
        for weight, when in sigs:
            w = weight * 0.5 ** (_days(now, when) / HALF_LIFE_DAYS) / len(chs)
            for ch in chs:
                interest[ch] += w
    # Chapitre presque fini (la plupart de ses contenus de cette liste réussis) : il passe à autre chose.
    total, done = defaultdict(int), defaultdict(int)
    for c in ids:
        for ch in chapters_of.get(c, ()):
            total[ch] += 1
            done[ch] += status.get(c) == 'success'
    for ch in interest:
        if total[ch]:
            interest[ch] *= 0.3 + 0.7 * (1 - done[ch] / total[ch])
    top = max([v for v in interest.values() if v > 0], default=0)
    affinity = {ch: max(v / top if top else v, -0.5) for ch, v in interest.items()}

    scored = []
    for cid, created, likes, dislikes, views in rows:
        chs = chapters_of.get(cid, [])
        aff = max((affinity.get(ch, 0) for ch in chs), default=0)
        age = _days(now, created)
        fresh = math.exp(-age / FRESH_DAYS)
        s = 3 * aff
        s += fresh * (1 + 2 * max(aff, 0))
        s += 0.8 * math.log1p(max((likes or 0) - (dislikes or 0), 0)) / math.log(30)
        s += 0.2 * math.log1p(views or 0) / math.log(1000)
        other_level = bool(level and levels_of.get(cid) and level not in levels_of[cid])
        if other_level:
            s -= 4
        st = status.get(cid)
        # À revoir : en pause pendant 3 jours (il vient d'y travailler), puis il remonte.
        due = cid in review_at and _days(now, review_at[cid]) >= REVIEW_DELAY_DAYS
        if cid in review_at:
            s += 1.5 if due else -1.5
        elif cid in signals:
            s -= 0.3  # déjà ouvert
        if cid in disliked:
            s -= 2
        best = max(chs, key=lambda ch: affinity.get(ch, 0)) if chs else None
        if other_level:
            reason = None
        elif due:
            reason = 'review'
        elif cid in review_at:
            reason = None  # en pause
        elif aff >= 0.25 and best is not None:
            reason = 'chapter'
        elif (likes or 0) - (dislikes or 0) >= 3:
            reason = 'popular'
        else:
            reason = None
        scored.append([st == 'success', -s, -created.timestamp() if created else 0, cid, chs, best, reason])

    # Variété : chaque contenu de plus d'un même chapitre perd un peu.
    scored.sort()
    seen = defaultdict(int)
    for row in scored:
        if row[0]:
            continue
        n = max((seen[ch] for ch in row[4]), default=0)
        row[1] += REPEAT_PENALTY * n
        for ch in row[4]:
            seen[ch] += 1
    scored.sort(key=lambda r: (r[0], r[1], r[2], r[3]))

    wanted = {r[5] for r in scored if r[6] == 'chapter'}
    names = {}
    if wanted:
        names = dict(Chapter.objects.filter(id__in=wanted).values_list('id', 'name'))
    out = []
    for done_, _, _, cid, _, best, reason in scored:
        if done_:
            label = None
        elif reason == 'review':
            label = 'À retravailler'
        elif reason == 'chapter':
            label = f'Suite de ton travail · {names[best]}' if best in names else None
        elif reason == 'popular':
            label = 'Apprécié des élèves'
        else:
            label = None
        out.append((cid, label))
    return out
