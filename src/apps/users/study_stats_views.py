"""
Study Statistics Views - Based on automatic StudyTimeTracker
Replaces the old TimeSession-based statistics
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth.models import User
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from datetime import timedelta, datetime
from apps.interactions.models import StudyTimeTracker
from django.contrib.contenttypes.models import ContentType
from apps.things.models import Content


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_study_statistics(request, username):
    """
    Get comprehensive study statistics based on automatic time tracking
    """
    try:
        user = User.objects.get(username=username)

        # Only allow users to see their own stats
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error': 'You cannot view other users\' statistics'},
                status=status.HTTP_403_FORBIDDEN
            )

        # All content uses a single ContentType
        content_ct = ContentType.objects.get_for_model(Content)

        # Calculate statistics for each content type
        exercise_stats = calculate_content_stats(user, content_ct, 'exercise')
        lesson_stats = calculate_content_stats(user, content_ct, 'lesson')
        exam_stats = calculate_content_stats(user, content_ct, 'exam')

        # Calculate overall statistics
        overall_stats = calculate_overall_stats(user)

        # Get recent activity
        recent_activity = get_recent_study_activity(user, limit=20)

        # Daily activity for the last 365 days (full year heatmap)
        daily_activity = get_daily_activity(user, days=365)

        return Response({
            'exercise_stats': exercise_stats,
            'lesson_stats': lesson_stats,
            'exam_stats': exam_stats,
            'overall_stats': overall_stats,
            'recent_activity': recent_activity,
            'daily_activity': daily_activity
        })

    except User.DoesNotExist:
        return Response(
            {'error': 'User not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def calculate_content_stats(user, content_type, content_name):
    """Calculate statistics for a specific content type"""

    # Get IDs for this content sub-type (exercise/lesson/exam)
    type_ids = Content.objects.filter(type=content_name).values_list('id', flat=True)

    # Get all study time entries for this content type
    entries = StudyTimeTracker.objects.filter(
        user=user,
        content_type=content_type,
        object_id__in=type_ids,
    )

    total_entries = entries.count()
    total_time_seconds = entries.aggregate(total=Sum('time_spent_seconds'))['total'] or 0

    # Calculate averages
    if total_entries > 0:
        average_time = total_time_seconds / total_entries
        longest_session = entries.order_by('-time_spent_seconds').first()
        shortest_session = entries.order_by('time_spent_seconds').first()
    else:
        average_time = 0
        longest_session = None
        shortest_session = None

    # Unique content studied
    unique_content = entries.values('object_id').distinct().count()

    # Weekly progress (last 4 weeks)
    weekly_progress = []
    now = timezone.now()
    for i in range(4):
        week_start = now - timedelta(weeks=i+1)
        week_end = now - timedelta(weeks=i)

        week_entries = entries.filter(
            recorded_at__gte=week_start,
            recorded_at__lt=week_end
        )

        week_time = week_entries.aggregate(total=Sum('time_spent_seconds'))['total'] or 0
        week_count = week_entries.count()

        weekly_progress.append({
            'week_number': i + 1,
            'week_start': week_start.strftime('%Y-%m-%d'),
            'week_end': week_end.strftime('%Y-%m-%d'),
            'entry_count': week_count,
            'total_time_seconds': week_time,
            'total_time_formatted': format_duration(week_time)
        })

    weekly_progress.reverse()  # Most recent first

    # Consistency score (last 30 days)
    thirty_days_ago = now - timedelta(days=30)
    recent_entries = entries.filter(recorded_at__gte=thirty_days_ago)

    # Count unique days with activity
    study_days = set()
    for entry in recent_entries:
        study_days.add(entry.recorded_at.date())

    consistency_score = min(100, int((len(study_days) / 30) * 100))

    return {
        'content_type': content_name,
        'total_entries': total_entries,
        'total_time_seconds': int(total_time_seconds),
        'total_time_formatted': format_duration(total_time_seconds),
        'average_time_seconds': int(average_time),
        'average_time_formatted': format_duration(average_time),
        'longest_session_seconds': longest_session.time_spent_seconds if longest_session else 0,
        'longest_session_formatted': format_duration(longest_session.time_spent_seconds) if longest_session else '0s',
        'shortest_session_seconds': shortest_session.time_spent_seconds if shortest_session else 0,
        'shortest_session_formatted': format_duration(shortest_session.time_spent_seconds) if shortest_session else '0s',
        'unique_content_studied': unique_content,
        'weekly_progress': weekly_progress,
        'consistency_score': consistency_score
    }


def calculate_overall_stats(user):
    """Calculate overall statistics across all content types"""

    all_entries = StudyTimeTracker.objects.filter(user=user)
    total_entries = all_entries.count()
    total_time_seconds = all_entries.aggregate(total=Sum('time_spent_seconds'))['total'] or 0

    # Study streak (consecutive days)
    streak = calculate_study_streak(user)

    # Most active day of week
    most_active_day = get_most_active_day(all_entries)

    # Study habits (morning, afternoon, evening)
    study_habits = analyze_study_habits(all_entries)

    # This week vs last week
    now = timezone.now()
    week_start = now - timedelta(days=now.weekday())
    last_week_start = week_start - timedelta(days=7)

    this_week_time = all_entries.filter(
        recorded_at__gte=week_start
    ).aggregate(total=Sum('time_spent_seconds'))['total'] or 0

    last_week_time = all_entries.filter(
        recorded_at__gte=last_week_start,
        recorded_at__lt=week_start
    ).aggregate(total=Sum('time_spent_seconds'))['total'] or 0

    # Calculate percentage change
    if last_week_time > 0:
        weekly_change = ((this_week_time - last_week_time) / last_week_time) * 100
    else:
        weekly_change = 100 if this_week_time > 0 else 0

    return {
        'total_entries': total_entries,
        'total_time_seconds': int(total_time_seconds),
        'total_time_formatted': format_duration(total_time_seconds),
        'current_study_streak': streak,
        'most_active_day': most_active_day,
        'study_habits': study_habits,
        'this_week_time_seconds': int(this_week_time),
        'this_week_time_formatted': format_duration(this_week_time),
        'last_week_time_seconds': int(last_week_time),
        'last_week_time_formatted': format_duration(last_week_time),
        'weekly_change_percentage': round(weekly_change, 1)
    }


def calculate_study_streak(user):
    """Calculate current study streak in days (optimized)"""
    from django.db.models.functions import TruncDate

    today = timezone.now().date()

    # Get all unique study dates in descending order (last 400 days max)
    start_date = today - timedelta(days=400)

    study_dates = StudyTimeTracker.objects.filter(
        user=user,
        recorded_at__gte=start_date
    ).annotate(
        study_date=TruncDate('recorded_at')
    ).values('study_date').distinct().order_by('-study_date')

    # Convert to set for O(1) lookup
    study_dates_set = {item['study_date'] for item in study_dates}

    # Calculate streak
    streak = 0
    current_date = today

    # Allow skipping today if no activity yet
    if current_date not in study_dates_set:
        current_date -= timedelta(days=1)

    # Count consecutive days
    while current_date in study_dates_set:
        streak += 1
        current_date -= timedelta(days=1)

        # Prevent infinite loop
        if streak > 400:
            break

    return streak


def get_most_active_day(entries):
    """Get the most active day of the week"""
    if not entries.exists():
        return None

    day_counts = {}
    days = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']

    for entry in entries:
        day_name = days[entry.recorded_at.weekday()]
        day_counts[day_name] = day_counts.get(day_name, 0) + 1

    if not day_counts:
        return None

    most_active = max(day_counts, key=day_counts.get)
    return {
        'day': most_active,
        'entry_count': day_counts[most_active]
    }


def analyze_study_habits(entries):
    """Analyze study habits - preferred time of day"""
    if not entries.exists():
        return {
            'preferred_time': {'morning': 0, 'afternoon': 0, 'evening': 0},
            'average_entries_per_week': 0
        }

    morning = entries.filter(recorded_at__hour__lt=12).count()
    afternoon = entries.filter(recorded_at__hour__gte=12, recorded_at__hour__lt=18).count()
    evening = entries.filter(recorded_at__hour__gte=18).count()

    total = entries.count()

    # Calculate weeks span
    if entries.exists():
        first_entry = entries.order_by('recorded_at').first()
        weeks_span = max(1, (timezone.now() - first_entry.recorded_at).days / 7)
    else:
        weeks_span = 1

    return {
        'preferred_time': {
            'morning': round((morning / total) * 100, 1) if total > 0 else 0,
            'afternoon': round((afternoon / total) * 100, 1) if total > 0 else 0,
            'evening': round((evening / total) * 100, 1) if total > 0 else 0
        },
        'average_entries_per_week': round(total / weeks_span, 1)
    }


def get_recent_study_activity(user, limit=20):
    """Get recent study activity (optimized to prevent N+1 queries)"""
    recent_entries = list(
        StudyTimeTracker.objects.filter(user=user).order_by('-recorded_at')[:limit]
    )

    # Bulk fetch Content titles
    content_ids = [e.object_id for e in recent_entries]
    content_map = {c.id: c for c in Content.objects.filter(id__in=content_ids).only('id', 'title', 'type')}

    activity_data = []
    for entry in recent_entries:
        obj = content_map.get(entry.object_id)
        activity_data.append({
            'id': entry.id,
            'content_type': obj.type if obj else entry.content_type.model,
            'content_title': obj.title if obj else 'Unknown',
            'time_spent_seconds': entry.time_spent_seconds,
            'time_spent_formatted': format_duration(entry.time_spent_seconds),
            'date': entry.recorded_at.strftime('%Y-%m-%d'),
            'time': entry.recorded_at.strftime('%H:%M')
        })

    return activity_data


def get_daily_activity(user, days=365):
    """Get daily activity for the last N days (optimized with aggregation)"""
    from django.db.models.functions import TruncDate

    now = timezone.now()
    end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    start_date = end_date - timedelta(days=days - 1)
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

    content_ct = ContentType.objects.get_for_model(Content)

    # IDs per type
    exercise_ids = list(Content.objects.filter(type='exercise').values_list('id', flat=True))
    lesson_ids = list(Content.objects.filter(type='lesson').values_list('id', flat=True))
    exam_ids = list(Content.objects.filter(type='exam').values_list('id', flat=True))

    base_qs = StudyTimeTracker.objects.filter(
        user=user,
        content_type=content_ct,
        recorded_at__gte=start_date,
        recorded_at__lte=end_date,
    )

    # Aggregate all data in one query using TruncDate
    daily_aggregates = base_qs.annotate(
        date=TruncDate('recorded_at')
    ).values('date').annotate(
        total_time=Sum('time_spent_seconds'),
        entry_count=Count('id')
    ).order_by('date')

    daily_lookup = {item['date']: item for item in daily_aggregates}

    def count_by_type(ids):
        return base_qs.filter(object_id__in=ids)\
            .annotate(date=TruncDate('recorded_at'))\
            .values('date').annotate(count=Count('id'))

    exercise_lookup = {item['date']: item['count'] for item in count_by_type(exercise_ids)}
    lesson_lookup = {item['date']: item['count'] for item in count_by_type(lesson_ids)}
    exam_lookup = {item['date']: item['count'] for item in count_by_type(exam_ids)}

    # Build response for all days
    daily_data = []
    for i in range(days):
        date = start_date + timedelta(days=i)
        date_key = date.date()

        # Get aggregated data or use zeros
        day_data = daily_lookup.get(date_key, {'total_time': 0, 'entry_count': 0})

        # Convert Python's weekday (0=Monday, 6=Sunday) to JS's getDay (0=Sunday, 6=Saturday)
        js_day_of_week = (date.weekday() + 1) % 7

        daily_data.append({
            'date': date.strftime('%Y-%m-%d'),
            'day_name': ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam'][js_day_of_week],
            'day_of_week': js_day_of_week,
            'total_time_seconds': day_data['total_time'] or 0,
            'total_time_formatted': format_duration(day_data['total_time'] or 0),
            'entries_count': day_data['entry_count'],
            'content_types': {
                'exercise': exercise_lookup.get(date_key, 0),
                'lesson': lesson_lookup.get(date_key, 0),
                'exam': exam_lookup.get(date_key, 0)
            }
        })

    return daily_data


def format_duration(seconds):
    """Format duration in seconds to human readable format"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        remaining_seconds = int(seconds % 60)
        return f"{minutes}m {remaining_seconds}s" if remaining_seconds > 0 else f"{minutes}m"
    else:
        hours = int(seconds // 3600)
        remaining_minutes = int((seconds % 3600) // 60)
        return f"{hours}h {remaining_minutes}m" if remaining_minutes > 0 else f"{hours}h"
