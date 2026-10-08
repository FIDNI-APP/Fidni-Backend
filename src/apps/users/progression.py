"""Ma progression : GET /api/stats/progression/  (remplace la page Statistiques, 07/10/2026)

Tout ce que l'élève a fait depuis ses débuts, rapporté au programme de son niveau. Uniquement des
chiffres enregistrés :
- maîtrise d'un chapitre = questions auto-évaluées des contenus du chapitre (réussi = 1, en partie
  = ½), à partir de 3 questions ; avec un quiz Skill IQ du chapitre : 60 % auto-évaluation, 40 %
  quiz (le quiz seul s'il n'y a pas assez de questions). État : maîtrisé (≥ 80 %), en bonne voie
  (≥ 60 %), à renforcer (< 60 %), commencé (pas encore assez de données), pas commencé ;
- points forts / à renforcer = notions des questions (≥ 3 évaluées) et chapitres du Skill IQ ;
- évolution = questions réussies et exercices réussis cumulés depuis le début, notes d'examen ;
- temps d'étude = journal jour par jour (StudyTimeDay) et objectif quotidien du profil.
"""
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, timedelta
from types import SimpleNamespace

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.caracteristics.models import Chapter
from apps.caracteristics.notions import NOTIONS, TRANSVERSAL, notion_label
from apps.interactions.models import Complete, QuestionProgress, StudyTimeDay
from apps.skilliq.models import SkillAssessment, SkillQuestion
from apps.things.models import Content
from apps.users.my_stats import MONTHS, WEIGHT, _questions
from apps.users.overview_views import _streaks

TYPE_PATH = {'exercise': 'exercises', 'exam': 'exams', 'lesson': 'lessons'}
MIN_QUESTIONS = 3          # en dessous, pas encore de pourcentage de maîtrise (trop peu de données)
MASTERED, GOOD = 80, 60    # seuils des états
SELF_WEIGHT = 0.6          # auto-évaluation face au quiz Skill IQ
TIME_DAYS = 28             # barres « jour par jour » (4 semaines)
# Chapitre de chaque notion (référentiel rangé par chapitre) : une question d'un examen à plusieurs
# chapitres compte pour celui de sa notion, pas pour tous.
NOTION_CHAPTER = {slug: name for name, items in NOTIONS.items() if name != TRANSVERSAL for slug in items}


def _same_chapter(a, b):
    # « Dérivation » (1ère Bac) et « Dérivation et étude des fonctions » (2ème Bac) : même chapitre.
    a, b = a.lower(), b.lower()
    return a == b or a.startswith(b) or b.startswith(a)


def _question_chapters(content_chapters, skills):
    """Chapitres (ids) d'une question : ceux de ses notions parmi ceux du contenu, sinon tous."""
    named = {NOTION_CHAPTER[s] for s in skills if s in NOTION_CHAPTER}
    hit = [cid for cid, name in content_chapters if any(_same_chapter(name, n) for n in named)]
    return hit or [cid for cid, _ in content_chapters]


def _pct(score, n):
    return round(score * 100 / n) if n else None


def _status(mastery, touched):
    if mastery is None:
        return 'started' if touched else 'todo'
    return 'mastered' if mastery >= MASTERED else 'good' if mastery >= GOOD else 'weak'


def _month_label(d):
    return f'{MONTHS[d.month - 1]} {d.year}'


def _local(dt):
    return timezone.localtime(dt).date()


def _collect(user):
    """Ce que l'élève a fait : questions évaluées, contenus réussis / à revoir, temps, quiz Skill IQ."""
    ct = ContentType.objects.get_for_model(Content)
    qp = list(QuestionProgress.objects.filter(user=user, content_type=ct)
              .values('object_id', 'question_path', 'status', 'created_at', 'assessed_at'))
    completes = [r for r in Complete.objects.filter(user=user, content_type=ct).values('object_id', 'status', 'updated_at')
                 if str(r['object_id']).isdigit()]
    for r in completes:
        r['object_id'] = int(r['object_id'])  # Complete.object_id : CharField
    time_rows = list(StudyTimeDay.objects.filter(user=user).values('object_id', 'date', 'seconds'))
    quizzes = {q.chapter_id: q for q in SkillAssessment.objects.filter(user=user)}

    ids = {r['object_id'] for r in qp} | {r['object_id'] for r in completes} | {r['object_id'] for r in time_rows}
    contents = {c.id: c for c in Content.objects.filter(id__in=ids).prefetch_related('chapters')}
    return SimpleNamespace(
        qp=qp, completes=completes, time_rows=time_rows, quizzes=quizzes, contents=contents,
        chapters_of={cid: [(ch.id, ch.name) for ch in c.chapters.all()] for cid, c in contents.items()},
        skills_of={cid: {path: skills for path, _, skills in _questions(c.json_content)} for cid, c in contents.items()},
    )


def _per_chapter(d):
    """Par chapitre (réussite des questions, notions, temps, contenus réussis / à revoir) et par notion."""
    chap = defaultdict(lambda: {'n': 0, 'score': 0.0, 'seconds': 0, 'last': None,
                                'notions': defaultdict(lambda: [0, 0.0]), 'done': set(), 'review': []})
    notions = defaultdict(lambda: {'n': 0, 'score': 0.0, 'chapters': Counter()})
    for r in d.qp:
        score = WEIGHT.get(r['status'], 0)
        day = _local(r['assessed_at'])
        skills = d.skills_of.get(r['object_id'], {}).get(r['question_path'], [])
        mine = _question_chapters(d.chapters_of.get(r['object_id'], []), skills)
        for ch in mine:
            row = chap[ch]
            row['n'] += 1
            row['score'] += score
            row['last'] = max(day, row['last']) if row['last'] else day
        for slug in skills:
            nrow = notions[slug]
            nrow['n'] += 1
            nrow['score'] += score
            for ch in mine:
                nrow['chapters'][ch] += 1
                chap[ch]['notions'][slug][0] += 1
                chap[ch]['notions'][slug][1] += score
    for r in d.time_rows:
        for ch, _ in d.chapters_of.get(r['object_id'], []):
            chap[ch]['seconds'] += r['seconds']
            chap[ch]['last'] = max(r['date'], chap[ch]['last']) if chap[ch]['last'] else r['date']
    for r in sorted(d.completes, key=lambda x: x['updated_at'], reverse=True):
        c = d.contents.get(r['object_id'])
        if not c:
            continue
        for ch, _ in d.chapters_of.get(c.id, []):
            if r['status'] == 'success' and c.type in ('exercise', 'exam'):
                chap[ch]['done'].add(c.id)
            elif r['status'] == 'review' and len(chap[ch]['review']) < 3:
                chap[ch]['review'].append({'id': c.id, 'title': c.title, 'url': f'/{TYPE_PATH.get(c.type, "exercises")}/{c.id}'})
    return chap, notions


def _chapter_entries(chapter_list, chap, quizzes, level):
    """Une entrée par chapitre : état, maîtrise, notions les mieux / moins réussies, quiz, contenus."""
    counts = Counter(Content.chapters.through.objects.filter(
        chapter_id__in=[c.id for c in chapter_list], content__type__in=('exercise', 'exam'),
        **({'content__class_levels': level} if level else {})).values_list('chapter_id', flat=True))
    quiz_ready = set(SkillQuestion.objects.filter(is_active=True).values('chapter_id').annotate(n=Count('id'))
                     .filter(n__gt=0).values_list('chapter_id', flat=True))
    chapters = []
    for ch in chapter_list:
        row = chap.get(ch.id)
        quiz = quizzes.get(ch.id)
        self_pct = _pct(row['score'], row['n']) if row and row['n'] >= MIN_QUESTIONS else None
        quiz_pct = _pct(quiz.score, quiz.max_score) if quiz and quiz.max_score else None
        if self_pct is not None and quiz_pct is not None:
            mastery = round(SELF_WEIGHT * self_pct + (1 - SELF_WEIGHT) * quiz_pct)
        else:
            mastery = self_pct if self_pct is not None else quiz_pct
        touched = bool(row and (row['n'] or row['seconds'] or row['done'])) or quiz is not None
        ranked = sorted(((slug, n, _pct(s, n)) for slug, (n, s) in (row['notions'].items() if row else []) if n >= 2),
                        key=lambda x: (-x[2], -x[1]))
        best = [{'label': notion_label(s), 'pct': p, 'questions': n} for s, n, p in ranked if p >= GOOD][:3]
        worst = [{'label': notion_label(s), 'pct': p, 'questions': n} for s, n, p in reversed(ranked) if p < GOOD][:3]
        chapters.append({
            'id': ch.id, 'name': ch.name, 'subfield': ch.subfield.name if ch.subfield else 'Autres',
            'status': _status(mastery, touched), 'mastery': mastery, 'self_pct': self_pct,
            'questions': row['n'] if row else 0,
            'skilliq': {'pct': quiz_pct, 'level': quiz.level, 'date': _local(quiz.completed_at).isoformat()} if quiz else None,
            'quiz_ready': ch.id in quiz_ready,
            'seconds': row['seconds'] if row else 0,
            'contents': counts.get(ch.id, 0), 'done': len(row['done']) if row else 0,
            'review': row['review'] if row else [],
            'notions': {'best': best, 'worst': worst},
            'last_at': row['last'].isoformat() if row and row['last'] else None,
        })
    return chapters


def chapter_progress(user, chapters, level=None):
    """Maîtrise de quelques chapitres, même calcul que la carte du programme (plan d'un DS)."""
    d = _collect(user)
    chap, _ = _per_chapter(d)
    return _chapter_entries(chapters, chap, d.quizzes, level)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def progression(request):
    user = request.user
    today = timezone.localdate()
    local = _local
    profile = getattr(user, 'profile', None)
    level = getattr(profile, 'class_level', None)

    d = _collect(user)
    qp, completes, time_rows, quizzes, contents = d.qp, d.completes, d.time_rows, d.quizzes, d.contents
    chap, notions = _per_chapter(d)

    # Le programme : chapitres du niveau (sinon ceux qu'il a travaillés), et combien de contenus chacun.
    chapter_qs = Chapter.objects.filter(class_levels=level) if level else Chapter.objects.filter(
        id__in=set(chap) | set(quizzes))
    chapter_list = list(chapter_qs.select_related('subfield').distinct().order_by('subfield__name', 'name'))
    chapters = _chapter_entries(chapter_list, chap, quizzes, level)
    by_id = {c['id']: c for c in chapters}

    # ── Points forts / à renforcer : notions (≥ 3 questions), puis chapitres du Skill IQ sans notions.
    def item(label, pct, chapter_id, source, questions=None):
        ch = by_id.get(chapter_id)
        return {'label': label, 'pct': pct, 'chapter_id': chapter_id if ch else None,
                'chapter': ch['name'] if ch else None, 'source': source, 'questions': questions,
                'url': f'/exercises?chapters={chapter_id}' if chapter_id else '/exercises'}
    rated = []
    for slug, row in notions.items():
        if row['n'] >= MIN_QUESTIONS:
            main = row['chapters'].most_common(1)[0][0] if row['chapters'] else None
            rated.append(item(notion_label(slug), _pct(row['score'], row['n']), main, 'notion', row['n']))
    for ch_id, quiz in quizzes.items():
        if ch_id in by_id and by_id[ch_id]['self_pct'] is None and quiz.max_score:
            rated.append(item(by_id[ch_id]['name'], _pct(quiz.score, quiz.max_score), ch_id, 'skilliq'))
    strengths = sorted((x for x in rated if x['pct'] >= MASTERED), key=lambda x: (-x['pct'], -(x['questions'] or 0)))[:3]
    weaknesses = sorted((x for x in rated if x['pct'] < GOOD), key=lambda x: (x['pct'], -(x['questions'] or 0)))[:3]

    # ── Examens corrigés (même règle que l'onglet « Ta copie » : la moitié du barème au moins)
    status_of, last_at = defaultdict(dict), {}
    for r in qp:
        status_of[r['object_id']][r['question_path']] = r['status']
        d = local(r['assessed_at'])
        last_at[r['object_id']] = max(d, last_at.get(r['object_id'], d))
    exams = []
    for cid, c in contents.items():
        if c.type != 'exam' or cid not in status_of:
            continue
        qs = [(path, pts) for path, pts, _ in _questions(c.json_content)]
        total = sum(p for _, p in qs)
        corrected = sum(p for path, p in qs if path in status_of[cid])
        if not total or corrected < total / 2:
            continue
        got = sum(p * WEIGHT.get(status_of[cid][path], 0) for path, p in qs if path in status_of[cid])
        exams.append({'id': c.id, 'title': c.title, 'url': f'/exams/{c.id}', 'date': last_at[cid],
                      'note': round(got / corrected * 20, 1)})
    exams.sort(key=lambda x: x['date'])

    # ── Évolution depuis le début : cumuls (questions réussies, exercices réussis), notes d'examen
    days = ([local(r['created_at']) for r in qp] + [local(r['updated_at']) for r in completes]
            + [r['date'] for r in time_rows] + [local(q.completed_at) for q in quizzes.values()])
    since = min(days) if days else None
    evolution = {'granularity': 'week', 'points': []}
    if since:
        monthly = (today - since).days > 120
        start = since.replace(day=1) if monthly else since - timedelta(days=since.weekday())
        buckets = []
        b = start
        while b <= today:
            buckets.append(b)
            b = date(b.year + (b.month == 12), b.month % 12 + 1, 1) if monthly else b + timedelta(days=7)
        ok_days = sorted(local(r['assessed_at']) for r in qp if r['status'] == 'success')
        ex_days = sorted(local(r['updated_at']) for r in completes
                         if r['status'] == 'success' and contents.get(r['object_id']) and contents[r['object_id']].type == 'exercise')
        points = []
        for i, b in enumerate(buckets):
            end = buckets[i + 1] if i + 1 < len(buckets) else today + timedelta(days=1)
            notes = [e['note'] for e in exams if b <= e['date'] < end]
            points.append({
                'start': b.isoformat(),
                'label': _month_label(b) if monthly else f'{b.day} {MONTHS[b.month - 1]}',
                'questions_ok': bisect_left(ok_days, end),
                'exercises': bisect_left(ex_days, end),
                'exam_avg': round(sum(notes) / len(notes), 1) if notes else None,
            })
        evolution = {'granularity': 'month' if monthly else 'week', 'points': points}

    # ── Temps d'étude
    per_day = Counter()
    for r in time_rows:
        per_day[r['date']] += r['seconds']
    week = sum(per_day[today - timedelta(days=i)] for i in range(7))
    prev_week = sum(per_day[today - timedelta(days=i)] for i in range(7, 14))
    per_month = Counter()
    for d, s in per_day.items():
        per_month[d.replace(day=1)] += s
    months = []
    if since:
        m = since.replace(day=1)
        while m <= today:
            months.append({'start': m.isoformat(), 'label': _month_label(m), 'seconds': per_month.get(m, 0)})
            m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    by_chapter = sorted(({'id': c['id'], 'name': c['name'], 'seconds': c['seconds']} for c in chapters if c['seconds']),
                        key=lambda x: -x['seconds'])[:8]

    active = set(days)
    current_streak, best_streak = _streaks(active, today)
    status_count = Counter(c['status'] for c in chapters)
    week_start = today - timedelta(days=6)
    return Response({
        'level': {'id': level.id, 'name': level.name} if level else None,
        'since': since.isoformat() if since else None,
        'summary': {
            'chapters': {'total': len(chapters), **{k: status_count.get(k, 0) for k in ('mastered', 'good', 'weak', 'started', 'todo')}},
            'questions': len(qp),
            'questions_ok': sum(1 for r in qp if r['status'] == 'success'),
            'questions_ok_week': sum(1 for r in qp if r['status'] == 'success' and local(r['assessed_at']) >= week_start),
            'exercises_done': sum(1 for r in completes if r['status'] == 'success' and contents.get(r['object_id'])
                                  and contents[r['object_id']].type == 'exercise'),
            'streak': {'current': current_streak, 'best': best_streak},
        },
        'chapters': chapters,
        'strengths': strengths,
        'weaknesses': weaknesses,
        'evolution': evolution,
        'exams': {
            'count': len(exams),
            'average': round(sum(e['note'] for e in exams) / len(exams), 1) if exams else None,
            'best': max((e['note'] for e in exams), default=None),
            'list': [{**e, 'date': e['date'].isoformat()} for e in reversed(exams[-10:])],
        },
        'time': {
            'goal_minutes': getattr(profile, 'daily_goal_minutes', 30) or 30,
            'total_seconds': sum(per_day.values()),
            'today': per_day[today], 'week': week, 'previous_week': prev_week,
            'days': [{'date': (today - timedelta(days=i)).isoformat(), 'seconds': per_day[today - timedelta(days=i)]}
                     for i in range(TIME_DAYS - 1, -1, -1)],
            'months': months,
            'by_chapter': by_chapter,
        },
    })
