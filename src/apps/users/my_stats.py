"""Statistiques de l'élève : GET /api/stats/me/?period=30&subject=<id>&level=<id>

Une page « Comment est-ce que je progresse ? », filtrable par période, matière et niveau.
Uniquement des chiffres enregistrés :
- note d'un examen = barème des questions auto-évaluées (réussi = tous les points, partiel = la
  moitié, à revoir / échoué = 0), ramenée sur 20 et calculée sur la partie corrigée ; un examen compte
  dès que la moitié de son barème est corrigée. Sa date = la dernière auto-évaluation ;
- réussite = part des questions auto-évaluées « réussi » ;
- difficultés = notions (étiquettes des questions) les moins réussies, au moins 3 questions ;
- temps d'étude = journal jour par jour (StudyTimeDay).
"""
from collections import Counter, defaultdict
from datetime import date, timedelta

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.caracteristics.notions import notion_label
from apps.interactions.models import Complete, QuestionProgress, StudyTimeDay
from apps.things.models import Content

PERIODS = {'7': 7, '30': 30, '90': 90, '365': 365, 'all': None}
WEIGHT = {'success': 1.0, 'partial': 0.5}
TYPE_PATH = {'exercise': 'exercises', 'exam': 'exams', 'lesson': 'lessons'}
MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']
MIN_NOTION_QUESTIONS = 3
WEAK_BELOW = 70


def _pct(part, whole):
    return round(part * 100 / whole) if whole else None


def _questions(structure):
    """(chemin, points, notions) de chaque question, chemins alignés sur QuestionProgress.question_path."""
    for block in (structure or {}).get('blocks', []):
        if block.get('type') != 'question':
            continue
        subs = block.get('subQuestions') or []
        if subs:
            for sub in subs:
                yield f"{block.get('id')}.{sub.get('id')}", float(sub.get('points') or 0), (sub.get('meta') or {}).get('skills') or []
        else:
            yield str(block.get('id')), float(block.get('points') or 0), (block.get('meta') or {}).get('skills') or []


def _bucketing(days):
    """Granularité de la courbe : jour (7 j), semaine (30 j, 3 mois), mois (au-delà)."""
    if days is not None and days <= 7:
        return 'day'
    if days is not None and days <= 90:
        return 'week'
    return 'month'


def _bucket_start(d, kind):
    if kind == 'day':
        return d
    if kind == 'week':
        return d - timedelta(days=d.weekday())
    return d.replace(day=1)


def _bucket_label(d, kind):
    if kind == 'month':
        return f'{MONTHS[d.month - 1]} {d.year}'
    prefix = 'sem. du ' if kind == 'week' else ''
    return f'{prefix}{d.day} {MONTHS[d.month - 1]}'


def _next_bucket(d, kind):
    if kind == 'day':
        return d + timedelta(days=1)
    if kind == 'week':
        return d + timedelta(days=7)
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_stats(request):
    user = request.user
    today = timezone.localdate()
    period_key = request.query_params.get('period', '30')
    days = PERIODS.get(period_key, 30)
    subject_id = request.query_params.get('subject') or None
    level_id = request.query_params.get('level') or None
    ct = ContentType.objects.get_for_model(Content)

    # ── Tout ce que l'élève a touché, une fois
    qp = list(QuestionProgress.objects.filter(user=user, content_type=ct)
              .values('object_id', 'question_path', 'status', 'assessed_at'))
    time_rows = list(StudyTimeDay.objects.filter(user=user).values('object_id', 'date', 'seconds'))
    completes = [r for r in Complete.objects.filter(user=user, content_type=ct).values('object_id', 'status', 'updated_at')
                 if str(r['object_id']).isdigit()]
    ids = {r['object_id'] for r in qp} | {r['object_id'] for r in time_rows} | {int(r['object_id']) for r in completes}
    all_contents = {c.id: c for c in Content.objects.filter(id__in=ids).select_related('subject')
                    .prefetch_related('class_levels', 'chapters', 'subfields', 'theorems')}

    # Choix des filtres : seulement les matières et niveaux réellement travaillés.
    subjects, levels = {}, {}
    for c in all_contents.values():
        if c.subject:
            subjects[c.subject.id] = c.subject.name
        for lv in c.class_levels.all():
            levels[lv.id] = lv.name

    def keep(c):
        if c is None:
            return False
        if subject_id and str(c.subject_id) != str(subject_id):
            return False
        if level_id and not any(str(lv.id) == str(level_id) for lv in c.class_levels.all()):
            return False
        return True

    contents = {cid: c for cid, c in all_contents.items() if keep(c)}
    qp = [r for r in qp if r['object_id'] in contents]
    time_rows = [r for r in time_rows if r['object_id'] in contents]
    completes = [r for r in completes if int(r['object_id']) in contents]

    # ── Période (et période précédente, de même durée, pour comparer)
    first_activity = min([timezone.localtime(r['assessed_at']).date() for r in qp] + [r['date'] for r in time_rows] or [today])
    start = today - timedelta(days=days - 1) if days else first_activity
    prev_start = start - timedelta(days=days) if days else None
    in_period = lambda d: start <= d <= today  # noqa: E731
    in_prev = lambda d: prev_start is not None and prev_start <= d < start  # noqa: E731
    local = lambda dt: timezone.localtime(dt).date()  # noqa: E731

    # ── Examens : une note par sujet, datée de la dernière auto-évaluation
    status_of = defaultdict(dict)
    last_at = defaultdict(lambda: None)
    for r in qp:
        status_of[r['object_id']][r['question_path']] = r['status']
        d = local(r['assessed_at'])
        last_at[r['object_id']] = max(d, last_at[r['object_id']]) if last_at[r['object_id']] else d
    exam_results = []
    for cid, c in contents.items():
        if c.type != 'exam' or cid not in status_of:
            continue
        qs = [(path, pts) for path, pts, _ in _questions(c.json_content)]
        total = sum(p for _, p in qs)
        corrected = sum(p for path, p in qs if path in status_of[cid])
        if not total or corrected < total / 2:
            continue
        got = sum(p * WEIGHT.get(status_of[cid][path], 0) for path, p in qs if path in status_of[cid])
        exam_results.append({'id': c.id, 'title': c.title, 'url': f'/exams/{c.id}', 'date': last_at[cid],
                             'note': round(got / corrected * 20, 1), 'complete': corrected >= total})

    def summary(rows):
        notes = [r['note'] for r in rows]
        return {'count': len(notes), 'average': round(sum(notes) / len(notes), 1) if notes else None,
                'best': max(notes) if notes else None, 'worst': min(notes) if notes else None}

    exams_now = sorted((r for r in exam_results if in_period(r['date'])), key=lambda r: r['date'], reverse=True)
    exams_prev = [r for r in exam_results if in_prev(r['date'])]

    # ── Questions auto-évaluées (réussite)
    q_now = [r for r in qp if in_period(local(r['assessed_at']))]
    q_prev = [r for r in qp if in_prev(local(r['assessed_at']))]
    success_rate = _pct(sum(r['status'] == 'success' for r in q_now), len(q_now))
    prev_success_rate = _pct(sum(r['status'] == 'success' for r in q_prev), len(q_prev))

    # ── Temps d'étude
    t_now = [r for r in time_rows if in_period(r['date'])]
    seconds_now = sum(r['seconds'] for r in t_now)
    seconds_prev = sum(r['seconds'] for r in time_rows if in_prev(r['date']))

    # ── Courbes : notes d'examen, réussite aux questions, temps (même découpage)
    kind = _bucketing(days if days else (today - start).days + 1)
    buckets = []
    b = _bucket_start(start, kind)
    while b <= today:
        buckets.append(b)
        b = _next_bucket(b, kind)
    by_bucket = defaultdict(lambda: {'notes': [], 'questions': 0, 'success': 0, 'seconds': 0})
    for r in exams_now:
        by_bucket[_bucket_start(r['date'], kind)]['notes'].append(r['note'])
    for r in q_now:
        k = by_bucket[_bucket_start(local(r['assessed_at']), kind)]
        k['questions'] += 1
        k['success'] += r['status'] == 'success'
    for r in t_now:
        by_bucket[_bucket_start(r['date'], kind)]['seconds'] += r['seconds']
    series = []
    for bk in buckets:
        v = by_bucket[bk]
        series.append({'start': bk.isoformat(), 'label': _bucket_label(bk, kind),
                       'exam_average': round(sum(v['notes']) / len(v['notes']), 1) if v['notes'] else None,
                       'exams': len(v['notes']), 'questions': v['questions'],
                       'success_rate': _pct(v['success'], v['questions']), 'minutes': round(v['seconds'] / 60)})

    # ── Difficultés : notions les moins réussies sur la période
    skills_of = {cid: {path: skills for path, _, skills in _questions(c.json_content)} for cid, c in contents.items()}
    notion_rows = defaultdict(lambda: {'n': 0, 'ok': 0, 'chapters': Counter()})
    for r in q_now:
        c = contents[r['object_id']]
        for slug in skills_of.get(r['object_id'], {}).get(r['question_path'], []):
            row = notion_rows[slug]
            row['n'] += 1
            row['ok'] += r['status'] == 'success'
            for ch in c.chapters.all():
                row['chapters'][(ch.id, ch.name)] += 1
    weak = []
    for slug, row in notion_rows.items():
        rate = _pct(row['ok'], row['n'])
        if row['n'] >= MIN_NOTION_QUESTIONS and rate < WEAK_BELOW:
            chapter = row['chapters'].most_common(1)[0][0] if row['chapters'] else None
            weak.append({'slug': slug, 'label': notion_label(slug), 'questions': row['n'], 'success_rate': rate,
                         'chapter': chapter[1] if chapter else None,
                         'url': f'/exercises?chapters={chapter[0]}' if chapter else '/exercises'})
    weak.sort(key=lambda x: (x['success_rate'], -x['questions']))

    # ── Temps par thème sur la période
    themes = {'chapter': Counter(), 'subfield': Counter(), 'theorem': Counter()}
    for r in t_now:
        c = contents[r['object_id']]
        for ch in c.chapters.all():
            themes['chapter'][ch.name] += r['seconds']
        for sf in c.subfields.all():
            themes['subfield'][sf.name] += r['seconds']
        for th in c.theorems.all():
            themes['theorem'][th.name] += r['seconds']
    time_by_theme = {k: [{'name': n, 'seconds': s} for n, s in v.most_common(12)] for k, v in themes.items()}

    # ── Activité
    validated = sum(1 for r in completes if r['status'] == 'success' and in_period(local(r['updated_at']))
                    and contents[int(r['object_id'])].type == 'exercise')
    active_days = ({local(r['assessed_at']) for r in q_now} | {r['date'] for r in t_now}
                   | {local(r['updated_at']) for r in completes if in_period(local(r['updated_at']))})

    for r in exams_now:
        r['date'] = r['date'].isoformat()

    return Response({
        'period': {'key': period_key if period_key in PERIODS else '30', 'start': start.isoformat(), 'end': today.isoformat(),
                   'days': (today - start).days + 1, 'granularity': kind, 'comparable': prev_start is not None},
        'filters': {
            'subjects': [{'id': k, 'name': v} for k, v in sorted(subjects.items(), key=lambda x: x[1])],
            'levels': [{'id': k, 'name': v} for k, v in sorted(levels.items())],
        },
        'results': {**summary(exams_now), 'previous': summary(exams_prev) if prev_start else None, 'exams': exams_now[:20]},
        'questions': {'count': len(q_now), 'success_rate': success_rate,
                      'previous_success_rate': prev_success_rate if prev_start else None},
        'time': {'seconds': seconds_now, 'previous_seconds': seconds_prev if prev_start else None, 'by_theme': time_by_theme},
        'series': series,
        'difficulties': weak[:5],
        'activity': {'active_days': len(active_days), 'exercises_validated': validated},
    })
