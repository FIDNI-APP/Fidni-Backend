"""
Dashboard views for user statistics and learning path tracking
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q, Sum
from django.utils import timezone
from datetime import timedelta
import logging

from apps.things.models import Content
from apps.interactions.models import Complete, StudyTimeTracker
from apps.caracteristics.models import Chapter

logger = logging.getLogger('django')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_dashboard_stats(request):
    """
    Get user dashboard statistics for the Quick Stats Dashboard component.
    Returns weekly stats including:
    - Exercises started
    - Study time
    - Perfect completions
    - Streak days
    """
    user = request.user

    # Calculate date range (last 7 days)
    now = timezone.now()
    week_ago = now - timedelta(days=7)

    # Get content type (single for unified Content model)
    content_ct = ContentType.objects.get_for_model(Content)

    # Scoped content types via subquery for type-based filtering
    exercise_ids = Content.objects.filter(type='exercise').values_list('id', flat=True)
    lesson_ids = Content.objects.filter(type='lesson').values_list('id', flat=True)
    exam_ids = Content.objects.filter(type='exam').values_list('id', flat=True)
    # Complete.object_id is a CharField (StudyTimeTracker's is int) — string ids for PostgreSQL
    exercise_id_strs = [str(i) for i in exercise_ids]

    # 1. Exercises started this week
    exercises_started = Complete.objects.filter(
        user=user,
        content_type=content_ct,
        object_id__in=exercise_id_strs,
        created_at__gte=week_ago
    ).values('object_id').distinct().count()

    # 2. Study time breakdown by content type
    def format_time(seconds):
        """Format seconds to 'Xh Ym' or 'Ym' or 'Xs'"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            return f"{minutes}m"
        else:
            return f"{secs}s"

    # Calculate time per content type from StudyTimeTracker (automatic tracking)
    exercises_time = StudyTimeTracker.objects.filter(
        user=user,
        content_type=content_ct,
        object_id__in=exercise_ids,
        recorded_at__gte=week_ago
    ).aggregate(total=Sum('time_spent_seconds'))['total'] or 0

    lessons_time = StudyTimeTracker.objects.filter(
        user=user,
        content_type=content_ct,
        object_id__in=lesson_ids,
        recorded_at__gte=week_ago
    ).aggregate(total=Sum('time_spent_seconds'))['total'] or 0

    exams_time = StudyTimeTracker.objects.filter(
        user=user,
        content_type=content_ct,
        object_id__in=exam_ids,
        recorded_at__gte=week_ago
    ).aggregate(total=Sum('time_spent_seconds'))['total'] or 0

    # Total study time (only from automatic StudyTimeTracker)
    total_seconds = exercises_time + lessons_time + exams_time

    # Calculate percentages
    exercises_percentage = (exercises_time / total_seconds * 100) if total_seconds > 0 else 0
    lessons_percentage = (lessons_time / total_seconds * 100) if total_seconds > 0 else 0
    exams_percentage = (exams_time / total_seconds * 100) if total_seconds > 0 else 0

    # Count number of study entries (tracking entries, not sessions)
    exercises_entries = StudyTimeTracker.objects.filter(
        user=user,
        content_type=content_ct,
        object_id__in=exercise_ids,
        recorded_at__gte=week_ago
    ).count()

    lessons_entries = StudyTimeTracker.objects.filter(
        user=user,
        content_type=content_ct,
        object_id__in=lesson_ids,
        recorded_at__gte=week_ago
    ).count()

    exams_entries = StudyTimeTracker.objects.filter(
        user=user,
        content_type=content_ct,
        object_id__in=exam_ids,
        recorded_at__gte=week_ago
    ).count()

    # Format overall study time
    study_time = format_time(total_seconds)

    # 3. Perfect completions (marked as 'success') this week
    perfect_completions = Complete.objects.filter(
        user=user,
        content_type=content_ct,
        object_id__in=exercise_id_strs,
        status='success',
        created_at__gte=week_ago
    ).count()

    # Total exercises this week
    total_exercises_week = exercises_started

    # 4. Calculate streak (consecutive days with activity)
    streak_days = calculate_user_streak(user)

    # Calculate average time per entry for each content type
    avg_time_per_exercise = (exercises_time / exercises_entries) if exercises_entries > 0 else 0
    avg_time_per_lesson = (lessons_time / lessons_entries) if lessons_entries > 0 else 0
    avg_time_per_exam = (exams_time / exams_entries) if exams_entries > 0 else 0

    return Response({
        'exercises_started': exercises_started,
        'study_time': study_time,
        'perfect_completions': perfect_completions,
        'total_exercises': total_exercises_week,
        'streak_days': streak_days,
        'period': 'week',

        # Detailed time breakdown by content type
        'time_breakdown': {
            'exercises': {
                'total_seconds': int(exercises_time),
                'formatted': format_time(exercises_time),
                'percentage': round(exercises_percentage, 1),
                'entries_count': exercises_entries,
                'average_per_entry': int(avg_time_per_exercise),
                'average_formatted': format_time(avg_time_per_exercise)
            },
            'lessons': {
                'total_seconds': int(lessons_time),
                'formatted': format_time(lessons_time),
                'percentage': round(lessons_percentage, 1),
                'entries_count': lessons_entries,
                'average_per_entry': int(avg_time_per_lesson),
                'average_formatted': format_time(avg_time_per_lesson)
            },
            'exams': {
                'total_seconds': int(exams_time),
                'formatted': format_time(exams_time),
                'percentage': round(exams_percentage, 1),
                'entries_count': exams_entries,
                'average_per_entry': int(avg_time_per_exam),
                'average_formatted': format_time(avg_time_per_exam)
            },
            'total_seconds': int(total_seconds)
        },

        # Learning insights
        'insights': {
            'most_studied_type': 'exercises' if exercises_time >= lessons_time and exercises_time >= exams_time
                                else 'lessons' if lessons_time >= exams_time else 'exams',
            'least_studied_type': 'exercises' if exercises_time <= lessons_time and exercises_time <= exams_time
                                 else 'lessons' if lessons_time <= exams_time else 'exams',
            'needs_more_lessons': lessons_time < (total_seconds * 0.3) if total_seconds > 0 else False,  # Less than 30% on lessons
            'balanced_study': abs(exercises_percentage - 33.3) < 10 and abs(lessons_percentage - 33.3) < 10 and abs(exams_percentage - 33.3) < 10
        }
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_learning_path_progress(request):
    """
    Get user's learning path progress for the Learning Path Tracker component.
    Returns progress based on completed chapters across all subjects.
    """
    user = request.user

    # Get all chapters that the user should complete (based on their class level)
    user_class_level = user.profile.class_level

    if not user_class_level:
        # If no class level set, return empty state
        return Response({
            'steps': [],
            'overall_progress': 0,
            'streak': calculate_user_streak(user),
            'level': calculate_user_level(user)
        })

    # Get main chapters for the user's level (ordered by typical curriculum)
    main_chapters = Chapter.objects.filter(
        subject__isnull=False
    ).order_by('name')[:5]  # Limit to 5 main steps

    # Build learning path steps
    steps = []
    completed_count = 0

    for idx, chapter in enumerate(main_chapters):
        # Check if user has completed exercises in this chapter
        content_ct = ContentType.objects.get_for_model(Content)

        chapter_exercises_completed = Complete.objects.filter(
            user=user,
            content_type=content_ct,
            status='success',
            object_id__in=[str(i) for i in Content.objects.filter(type='exercise', chapters=chapter).values_list('id', flat=True)]
        ).exists()

        # Determine status based on completion
        if chapter_exercises_completed:
            step_status = 'completed'
            completed_count += 1
        elif idx == completed_count:
            step_status = 'current'
        else:
            step_status = 'locked'

        steps.append({
            'id': str(chapter.id),
            'title': chapter.name,
            'status': step_status
        })

    # Calculate overall progress percentage
    overall_progress = int((completed_count / len(steps)) * 100) if steps else 0

    return Response({
        'steps': steps,
        'overall_progress': overall_progress,
        'streak': calculate_user_streak(user),
        'level': calculate_user_level(user)
    })


def calculate_user_streak(user):
    """
    Calculate the number of consecutive days the user has been active.
    Activity is defined as having a TimeSession or Complete entry.
    """
    from django.utils import timezone
    from datetime import timedelta

    streak = 0
    current_date = timezone.now().date()

    # Check up to 365 days back
    for i in range(365):
        check_date = current_date - timedelta(days=i)
        start_of_day = timezone.make_aware(
            timezone.datetime.combine(check_date, timezone.datetime.min.time())
        )
        end_of_day = timezone.make_aware(
            timezone.datetime.combine(check_date, timezone.datetime.max.time())
        )

        # Check if user had any activity this day (completions or study time)
        has_activity = (
            Complete.objects.filter(
                user=user,
                created_at__range=(start_of_day, end_of_day)
            ).exists() or
            StudyTimeTracker.objects.filter(
                user=user,
                recorded_at__range=(start_of_day, end_of_day)
            ).exists()
        )

        if has_activity:
            streak += 1
        elif i > 0:  # Allow missing today, but break on first gap after that
            break

    return streak


def calculate_user_level(user):
    """
    Calculate user level based on total completed exercises.
    Level formula: 1 level per 10 completed exercises
    """
    content_ct = ContentType.objects.get_for_model(Content)
    exercise_ids = [str(i) for i in Content.objects.filter(type='exercise').values_list('id', flat=True)]

    total_completed = Complete.objects.filter(
        user=user,
        content_type=content_ct,
        object_id__in=exercise_ids,
        status='success'
    ).count()

    # 10 exercises = 1 level
    level = (total_completed // 10) + 1

    return level


REC_LIMIT = 8   # contenus proposés par type


def _target_subjects(profile):
    """Matières visées du profil (ManyToMany, ou liste pour un ancien format)."""
    ts = getattr(profile, 'target_subjects', None) if profile else None
    if ts is None:
        return []
    if hasattr(ts, 'all'):
        return list(ts.values_list('id', flat=True))
    return list(ts) if isinstance(ts, list) else []


def _recommended(user, kind, scope, ds, done):
    """[(id, raison)] « Pour toi » d'un type de contenu, sans ce qu'il a déjà réussi.

    Ordre des viviers, le premier qui propose encore quelque chose l'emporte : chapitres du DS
    (au niveau du DS, toutes matières : les chapitres la disent déjà), son niveau, tout le site.
    Le classement porte sur tout le vivier, réussis compris (un chapitre presque fini intéresse
    moins), puis on retire les réussis.
    """
    from apps.interactions.models import Vote
    from apps.things import for_you
    base = Content.objects.filter(type=kind)
    scoped = base.filter(scope) if scope else base
    pools = []
    if ds:
        ds_chapters, ds_level = ds
        in_ds = base.filter(id__in=Content.chapters.through.objects.filter(
            chapter_id__in=ds_chapters).values('content_id'))
        pools.append((in_ds.filter(class_levels=ds_level) if ds_level else in_ds, True))
    pools.append((scoped, False))
    if scope:
        pools.append((base, False))
    pool, for_ds = next(((qs, is_ds) for qs, is_ds in pools if qs.exclude(id__in=done).exists()), (None, False))
    if pool is None:
        return []
    likes = Count('votes', filter=Q(votes__value=Vote.UP), distinct=True)
    dislikes = Count('votes', filter=Q(votes__value=Vote.DOWN), distinct=True)
    ranked = for_you.rank(pool.annotate(like_count_annotation=likes, dislike_count_annotation=dislikes), user)
    picked = [(cid, label) for cid, label in ranked if cid not in done][:REC_LIMIT]
    if for_ds:
        picked = [(cid, label or 'Au programme de ton DS') for cid, label in picked]
    return picked


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_recommended_content(request):
    """« Pour toi » de l'accueil : exercices, leçons et examens (8 de chaque au plus).

    Même classement que les listes (things/for_you.py : chapitres travaillés, « à retravailler »,
    nouveautés, popularité), avec la raison de chaque choix (`reason`) :
    - de son niveau (et de ses matières), sinon de tout le site s'il n'y a plus rien ;
    - jamais ce qu'il a déjà réussi ; ce qu'il a marqué « à revoir » reste proposé ;
    - un DS annoncé dans les 14 jours (comme le rappel de l'accueil) : seulement ses chapitres, même hors
      de ses matières visées.
    Avant (10/10/2026) : les 8 plus aimés du niveau, les mêmes pour tous, « à revoir » exclus.
    """
    from apps.interactions.devoirs import SOON_DAYS
    from apps.interactions.models import UpcomingTest
    from apps.things.listing import in_order, with_list_relations
    from apps.things.serializers import ContentListSerializer

    try:
        user = request.user
        profile = getattr(user, 'profile', None)
        class_level = getattr(profile, 'class_level', None) if profile else None
        subjects = _target_subjects(profile)
        scope = Q()
        if class_level:
            scope &= Q(class_levels=class_level)
        if subjects:
            scope &= Q(subject_id__in=subjects)

        ct = ContentType.objects.get_for_model(Content)
        # Complete.object_id est un CharField : ids relus en entiers.
        done = {int(o) for o in Complete.objects.filter(user=user, content_type=ct, status='success')
                .values_list('object_id', flat=True) if str(o).isdigit()}
        today = timezone.localdate()
        test = (UpcomingTest.objects.filter(user=user, date__gte=today, date__lte=today + timedelta(days=SOON_DAYS))
                .select_related('class_level').order_by('date', 'id').first())
        ds_chapters = list(test.chapters.values_list('id', flat=True)) if test else []
        ds = (ds_chapters, test.class_level or class_level) if ds_chapters else None

        ctx = {'request': request}
        out = {}
        for kind, key in (('exercise', 'exercises'), ('lesson', 'lessons'), ('exam', 'exams')):
            picked = _recommended(user, kind, scope, ds, done)
            reasons = dict(picked)
            items = in_order(with_list_relations(Content.objects.all(), user), [cid for cid, _ in picked])
            rows = ContentListSerializer(items, many=True, context=ctx).data
            for row in rows:
                row['reason'] = reasons.get(row['id'])
            out[key] = rows
        out['level'] = class_level.name if class_level else None
        return Response(out)
    except Exception:
        logger.exception('get_recommended_content')
        return Response({'exercises': [], 'lessons': [], 'exams': []}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
