"""Tableau de bord de l'accueil : GET /api/dashboard/overview/

Uniquement des chiffres enregistrés (aucune estimation) :
- activité datée = auto-évaluations de questions (1re fois), contenus terminés, sessions de chrono
  enregistrées, quiz Skill IQ. Le temps d'étude automatique n'a pas d'historique par jour (une ligne
  cumulée par contenu) : il n'entre donc pas dans le calendrier ;
- maîtrise = part des questions auto-évaluées « réussi » ;
- notions = étiquettes des questions (référentiel apps/caracteristics/notions.py).
"""
from collections import Counter, defaultdict
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.caracteristics.models import Chapter
from apps.caracteristics.notions import notion_label
from apps.interactions.models import Complete, QuestionProgress, TimeSession
from apps.skilliq.models import SkillAssessment
from apps.things.models import Content
from apps.things.views import _walk_questions_meta

CALENDAR_DAYS = 7 * 52   # une année scolaire, en semaines entières
TYPE_PATH = {'exercise': 'exercises', 'exam': 'exams', 'lesson': 'lessons'}


def _pct(part, whole):
    return round(part * 100 / whole) if whole else None


def _streaks(active_days, today):
    """Série en cours (aujourd'hui ou hier compris) et meilleure série."""
    best = run = 0
    prev = None
    for d in sorted(active_days):
        run = run + 1 if prev and (d - prev).days == 1 else 1
        best = max(best, run)
        prev = d
    current = 0
    d = today if today in active_days else today - timedelta(days=1)
    while d in active_days:
        current += 1
        d -= timedelta(days=1)
    return current, best


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_overview(request):
    user = request.user
    now = timezone.now()
    today = timezone.localdate()
    ct = ContentType.objects.get_for_model(Content)
    profile = getattr(user, 'profile', None)
    level = getattr(profile, 'class_level', None)

    qp = list(QuestionProgress.objects.filter(user=user, content_type=ct)
              .values('object_id', 'question_path', 'status', 'created_at', 'assessed_at'))
    completes = list(Complete.objects.filter(user=user, content_type=ct).values('object_id', 'status', 'created_at', 'updated_at'))
    sessions = list(TimeSession.objects.filter(user=user, content_type=ct).values('object_id', 'session_duration', 'created_at'))
    quizzes = list(SkillAssessment.objects.filter(user=user).values('chapter_id', 'score', 'max_score', 'completed_at'))

    # ── Calendrier d'activité et séries
    events = Counter()
    for row in qp:
        events[timezone.localtime(row['created_at']).date()] += 1
    for row in completes:
        events[timezone.localtime(row['created_at']).date()] += 1
    for row in sessions:
        events[timezone.localtime(row['created_at']).date()] += 1
    for row in quizzes:
        events[timezone.localtime(row['completed_at']).date()] += 1
    start = today - timedelta(days=CALENDAR_DAYS - 1)
    calendar = [{'date': (start + timedelta(days=i)).isoformat(), 'count': events.get(start + timedelta(days=i), 0)}
                for i in range(CALENDAR_DAYS)]
    current_streak, best_streak = _streaks(set(events), today)

    # ── Cette semaine (7 derniers jours) contre la précédente
    week_start, prev_start = now - timedelta(days=7), now - timedelta(days=14)

    def in_week(dt, a, b):
        return a <= dt < b

    def week_stats(a, b):
        rows = [r for r in qp if in_week(r['created_at'], a, b)]
        mins = sum(r['session_duration'].total_seconds() for r in sessions if in_week(r['created_at'], a, b)) / 60
        return {
            'questions': len(rows),
            'success_rate': _pct(sum(r['status'] == 'success' for r in rows), len(rows)),
            'completed': sum(1 for r in completes if r['status'] == 'success' and in_week(r['created_at'], a, b)),
            'chrono_minutes': round(mins),
            'active_days': len({timezone.localtime(r['created_at']).date() for r in rows}
                               | {timezone.localtime(r['created_at']).date() for r in completes if in_week(r['created_at'], a, b)}),
        }

    # ── Contenus concernés (une seule requête) et chemin → notions
    content_ids = {r['object_id'] for r in qp} | {int(r['object_id']) for r in completes if str(r['object_id']).isdigit()}
    contents = {c.id: c for c in Content.objects.filter(id__in=content_ids).prefetch_related('chapters')}
    questions_of, skills_of = {}, {}
    for cid, c in contents.items():
        metas = list(_walk_questions_meta(c.json_content or {}))
        questions_of[cid] = len(metas)
        skills_of[cid] = {path: (meta.get('skills') or []) for path, _, meta in metas}

    def brief(c, **extra):
        chapter = next(iter(c.chapters.all()), None)
        return {'id': c.id, 'type': c.type, 'title': c.title, 'url': f'/{TYPE_PATH.get(c.type, "exercises")}/{c.id}',
                'chapter': chapter.name if chapter else None, **extra}

    # ── Reprendre : commencés (au moins une question évaluée), pas encore réussis
    done = {int(r['object_id']) for r in completes if r['status'] == 'success' and str(r['object_id']).isdigit()}
    by_content = defaultdict(list)
    for r in qp:
        by_content[r['object_id']].append(r)
    resume = []
    for cid, rows in by_content.items():
        c = contents.get(cid)
        if not c or cid in done:
            continue
        total = questions_of.get(cid) or 0
        if total and len(rows) >= total:
            continue  # tout évalué : rien à « reprendre »
        resume.append(brief(c, assessed=len(rows), total=total,
                            last_at=max(r['assessed_at'] for r in rows).isoformat()))
    resume.sort(key=lambda x: x['last_at'], reverse=True)

    # ── À revoir : contenus marqués « échoué / à revoir »
    review = []
    for r in sorted(completes, key=lambda x: x['updated_at'], reverse=True):
        cid = int(r['object_id']) if str(r['object_id']).isdigit() else None
        if r['status'] == 'review' and cid in contents:
            review.append(brief(contents[cid]))

    # ── Maîtrise par chapitre (auto-évaluations) + Skill IQ
    chap_rows = defaultdict(list)
    for r in qp:
        c = contents.get(r['object_id'])
        for ch in (c.chapters.all() if c else []):
            chap_rows[ch.id].append(r['status'])
    quiz_by_chapter = {q['chapter_id']: _pct(q['score'], q['max_score']) for q in quizzes}
    chapters_qs = Chapter.objects.filter(class_levels=level) if level else Chapter.objects.filter(id__in=chap_rows)
    chapters = []
    for ch in chapters_qs.select_related('subfield').order_by('subfield__name', 'name'):
        rows = chap_rows.get(ch.id, [])
        chapters.append({
            'id': ch.id, 'name': ch.name, 'subfield': ch.subfield.name if ch.subfield else None,
            'assessed': len(rows), 'success_pct': _pct(sum(s == 'success' for s in rows), len(rows)),
            'skilliq_pct': quiz_by_chapter.get(ch.id),
            'contents': Content.objects.filter(chapters=ch, **({'class_levels': level} if level else {})).count(),
        })

    # ── Notions à retravailler (au moins 2 questions évaluées, moins de 60 % réussies)
    notion_stats = defaultdict(lambda: [0, 0])
    for r in qp:
        for slug in skills_of.get(r['object_id'], {}).get(r['question_path'], []):
            notion_stats[slug][0] += 1
            notion_stats[slug][1] += r['status'] == 'success'
    weak = sorted(({'slug': s, 'label': notion_label(s), 'assessed': n, 'mastery_pct': _pct(ok, n)}
                   for s, (n, ok) in notion_stats.items() if n >= 2 and _pct(ok, n) < 60),
                  key=lambda x: (x['mastery_pct'], -x['assessed']))

    return Response({
        'level': {'id': level.id, 'name': level.name} if level else None,
        'streak': {'current': current_streak, 'best': best_streak},
        'calendar': calendar,
        'week': week_stats(week_start, now),
        'previous_week': week_stats(prev_start, week_start),
        'totals': {
            'questions': len(qp),
            'success_rate': _pct(sum(r['status'] == 'success' for r in qp), len(qp)),
            'exercises_done': sum(1 for cid in done if contents.get(cid) and contents[cid].type == 'exercise'),
            'exams_done': sum(1 for cid in done if contents.get(cid) and contents[cid].type == 'exam'),
            'chrono_minutes': round(sum(r['session_duration'].total_seconds() for r in sessions) / 60),
        },
        'resume': resume[:3],
        'review': review[:4],
        'chapters': chapters,
        'coverage': {'total': len(chapters), 'touched': sum(1 for c in chapters if c['assessed'])},
        'weak_notions': weak[:4],
    })
