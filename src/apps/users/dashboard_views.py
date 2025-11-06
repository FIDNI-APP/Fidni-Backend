"""
Dashboard views for user statistics and learning path tracking
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum, Count, Q, Avg
from django.utils import timezone
from datetime import timedelta

from apps.things.models import Exercise, Lesson, Exam
from apps.interactions.models import Complete, Save, StudyTimeTracker
from apps.learningpath.models import (
    UserLearningPathProgress,
    UserChapterProgress,
    PathChapter
)
from apps.caracteristics.models import Chapter


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

    # Get content types
    exercise_ct = ContentType.objects.get_for_model(Exercise)
    lesson_ct = ContentType.objects.get_for_model(Lesson)
    exam_ct = ContentType.objects.get_for_model(Exam)

    # 1. Exercises started this week
    exercises_started = Complete.objects.filter(
        user=user,
        content_type=exercise_ct,
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
        content_type=exercise_ct,
        recorded_at__gte=week_ago
    ).aggregate(total=Sum('time_spent_seconds'))['total'] or 0

    lessons_time = StudyTimeTracker.objects.filter(
        user=user,
        content_type=lesson_ct,
        recorded_at__gte=week_ago
    ).aggregate(total=Sum('time_spent_seconds'))['total'] or 0

    exams_time = StudyTimeTracker.objects.filter(
        user=user,
        content_type=exam_ct,
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
        content_type=exercise_ct,
        recorded_at__gte=week_ago
    ).count()

    lessons_entries = StudyTimeTracker.objects.filter(
        user=user,
        content_type=lesson_ct,
        recorded_at__gte=week_ago
    ).count()

    exams_entries = StudyTimeTracker.objects.filter(
        user=user,
        content_type=exam_ct,
        recorded_at__gte=week_ago
    ).count()

    # Format overall study time
    study_time = format_time(total_seconds)

    # 3. Perfect completions (marked as 'success') this week
    perfect_completions = Complete.objects.filter(
        user=user,
        content_type=exercise_ct,
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
        exercise_ct = ContentType.objects.get_for_model(Exercise)

        chapter_exercises_completed = Complete.objects.filter(
            user=user,
            content_type=exercise_ct,
            status='success'
        ).filter(
            Q(object_id__in=Exercise.objects.filter(
                chapters=chapter
            ).values_list('id', flat=True))
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
    exercise_ct = ContentType.objects.get_for_model(Exercise)

    total_completed = Complete.objects.filter(
        user=user,
        content_type=exercise_ct,
        status='success'
    ).count()

    # 10 exercises = 1 level
    level = (total_completed // 10) + 1

    return level


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_recommended_content(request):
    """
    Get recommended exercises, lessons, and exams for the user.
    Uses a simple recommendation algorithm based on:
    - User's class level
    - User's target subjects
    - Most upvoted content
    - Content user hasn't completed yet
    """
    try:
        user = request.user
        user_profile = getattr(user, 'profile', None)

        # Get user's class level and target subjects safely
        class_level = getattr(user_profile, 'class_level', None) if user_profile else None

        # Handle target_subjects - it could be a ManyRelatedManager or a list/JSONField
        target_subjects = []
        if user_profile:
            ts = getattr(user_profile, 'target_subjects', None)
            if ts is not None:
                # If it's a ManyRelatedManager (ManyToManyField)
                if hasattr(ts, 'all'):
                    target_subjects = list(ts.values_list('id', flat=True))
                # If it's already a list or JSONField
                elif isinstance(ts, list):
                    target_subjects = ts
                else:
                    target_subjects = []

        # Content types
        exercise_ct = ContentType.objects.get_for_model(Exercise)
        lesson_ct = ContentType.objects.get_for_model(Lesson)
        exam_ct = ContentType.objects.get_for_model(Exam)

        # Get IDs of content user has already completed
        completed_exercise_ids = Complete.objects.filter(
            user=user,
            content_type=exercise_ct
        ).values_list('object_id', flat=True)

        completed_lesson_ids = Complete.objects.filter(
            user=user,
            content_type=lesson_ct
        ).values_list('object_id', flat=True)

        completed_exam_ids = Complete.objects.filter(
            user=user,
            content_type=exam_ct
        ).values_list('object_id', flat=True)

        # Base query filters
        base_filters = Q()
        if class_level:
            base_filters &= Q(class_levels=class_level)
            print(f"[Recommendations] Filtering by class_level: {class_level}")
        if target_subjects and len(target_subjects) > 0:
            base_filters &= Q(subject_id__in=target_subjects)
            print(f"[Recommendations] Filtering by target_subjects: {target_subjects}")

        print(f"[Recommendations] Has filters: {bool(base_filters)}")

        # Annotate with vote count for ordering
        from django.db.models import Count, Case, When, IntegerField
        from apps.interactions.models import Vote

        # If no filters, just get most upvoted content
        if not base_filters:
            print("[Recommendations] No filters, getting most upvoted content")
            exercises = Exercise.objects.exclude(id__in=completed_exercise_ids)\
                .annotate(
                    upvotes=Count(Case(When(votes__value=Vote.UP, then=1), output_field=IntegerField())),
                    downvotes=Count(Case(When(votes__value=Vote.DOWN, then=1), output_field=IntegerField()))
                )\
                .order_by('-upvotes', '-created_at')[:8]

            lessons = Lesson.objects.exclude(id__in=completed_lesson_ids)\
                .annotate(
                    upvotes=Count(Case(When(votes__value=Vote.UP, then=1), output_field=IntegerField())),
                    downvotes=Count(Case(When(votes__value=Vote.DOWN, then=1), output_field=IntegerField()))
                )\
                .order_by('-upvotes', '-created_at')[:8]

            exams = Exam.objects.exclude(id__in=completed_exam_ids)\
                .annotate(
                    upvotes=Count(Case(When(votes__value=Vote.UP, then=1), output_field=IntegerField())),
                    downvotes=Count(Case(When(votes__value=Vote.DOWN, then=1), output_field=IntegerField()))
                )\
                .order_by('-upvotes', '-created_at')[:8]
        else:
            # Recommended Exercises
            exercises = Exercise.objects.filter(base_filters)\
                .exclude(id__in=completed_exercise_ids)\
                .annotate(
                    upvotes=Count(Case(When(votes__value=Vote.UP, then=1), output_field=IntegerField())),
                    downvotes=Count(Case(When(votes__value=Vote.DOWN, then=1), output_field=IntegerField()))
                )\
                .order_by('-upvotes', '-created_at')[:8]

            # Recommended Lessons
            lessons = Lesson.objects.filter(base_filters)\
                .exclude(id__in=completed_lesson_ids)\
                .annotate(
                    upvotes=Count(Case(When(votes__value=Vote.UP, then=1), output_field=IntegerField())),
                    downvotes=Count(Case(When(votes__value=Vote.DOWN, then=1), output_field=IntegerField()))
                )\
                .order_by('-upvotes', '-created_at')[:8]

            # Recommended Exams
            exams = Exam.objects.filter(base_filters)\
                .exclude(id__in=completed_exam_ids)\
                .annotate(
                    upvotes=Count(Case(When(votes__value=Vote.UP, then=1), output_field=IntegerField())),
                    downvotes=Count(Case(When(votes__value=Vote.DOWN, then=1), output_field=IntegerField()))
                )\
                .order_by('-upvotes', '-created_at')[:8]

        # Fallback: If filtered results are empty, get most upvoted content instead
        exercises_count = exercises.count()
        print(f"[Recommendations] Initial exercises count: {exercises_count}")
        if exercises_count == 0:
            print("[Recommendations] No exercises found, falling back to most upvoted")
            exercises = Exercise.objects.exclude(id__in=completed_exercise_ids)\
                .annotate(
                    upvotes=Count(Case(When(votes__value=Vote.UP, then=1), output_field=IntegerField())),
                    downvotes=Count(Case(When(votes__value=Vote.DOWN, then=1), output_field=IntegerField()))
                )\
                .order_by('-upvotes', '-created_at')[:8]
            print(f"[Recommendations] Fallback exercises count: {exercises.count()}")

        lessons_count = lessons.count()
        print(f"[Recommendations] Initial lessons count: {lessons_count}")
        if lessons_count == 0:
            print("[Recommendations] No lessons found, falling back to most upvoted")
            lessons = Lesson.objects.exclude(id__in=completed_lesson_ids)\
                .annotate(
                    upvotes=Count(Case(When(votes__value=Vote.UP, then=1), output_field=IntegerField())),
                    downvotes=Count(Case(When(votes__value=Vote.DOWN, then=1), output_field=IntegerField()))
                )\
                .order_by('-upvotes', '-created_at')[:8]
            print(f"[Recommendations] Fallback lessons count: {lessons.count()}")

        exams_count = exams.count()
        print(f"[Recommendations] Initial exams count: {exams_count}")
        if exams_count == 0:
            print("[Recommendations] No exams found, falling back to most upvoted")
            exams = Exam.objects.exclude(id__in=completed_exam_ids)\
                .annotate(
                    upvotes=Count(Case(When(votes__value=Vote.UP, then=1), output_field=IntegerField())),
                    downvotes=Count(Case(When(votes__value=Vote.DOWN, then=1), output_field=IntegerField()))
                )\
                .order_by('-upvotes', '-created_at')[:8]
            print(f"[Recommendations] Fallback exams count: {exams.count()}")

        # Serialize the data
        from apps.things.serializers import ExerciseSerializer, LessonSerializer, ExamSerializer

        return Response({
            'exercises': ExerciseSerializer(exercises, many=True, context={'request': request}).data,
            'lessons': LessonSerializer(lessons, many=True, context={'request': request}).data,
            'exams': ExamSerializer(exams, many=True, context={'request': request}).data
        })
    except Exception as e:
        # Log the error and return a more helpful response
        import traceback
        print(f"Error in get_recommended_content: {str(e)}")
        print(traceback.format_exc())
        return Response({
            'error': str(e),
            'exercises': [],
            'lessons': [],
            'exams': []
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
