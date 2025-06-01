from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum, Avg, Count, Q
from django.utils import timezone
from datetime import timedelta, datetime
from interactions.models import TimeSession, TimeSpent
from things.models import Exercise, Exam


class TimeStatsViewMixin:
    """
    Mixin to add time tracking statistics to user views
    """
    
    @action(detail=True, methods=['get'])
    def time_statistics(self, request, username=None):
        """
        Get comprehensive time tracking statistics for the user
        Separated by exercise and exam content types
        """
        user = self.get_object()
        
        # Check permissions
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error': 'You cannot view other users\' time statistics'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get content types
        exercise_content_type = ContentType.objects.get_for_model(Exercise)
        exam_content_type = ContentType.objects.get_for_model(Exam)
        
        # Calculate statistics for exercises
        exercise_stats = self._calculate_content_type_stats(user, exercise_content_type, 'exercise')
        
        # Calculate statistics for exams
        exam_stats = self._calculate_content_type_stats(user, exam_content_type, 'exam')
        
        # Calculate overall statistics
        overall_stats = self._calculate_overall_stats(user)
        
        return Response({
            'exercise_stats': exercise_stats,
            'exam_stats': exam_stats,
            'overall_stats': overall_stats,
            'recent_activity': self._get_recent_activity(user)
        })
    
    def _calculate_content_type_stats(self, user, content_type, content_name):
        """
        Calculate statistics for a specific content type (exercise or exam)
        """
        # Get all sessions for this content type
        sessions = TimeSession.objects.filter(
            user=user,
            content_type=content_type
        )
        
        # Get total time spent records
        time_spent_records = TimeSpent.objects.filter(
            user=user,
            content_type=content_type
        )
        
        # Basic session statistics
        total_sessions = sessions.count()
        total_time_seconds = sum(session.session_duration_in_seconds for session in sessions)
        
        # Calculate averages and extremes
        if total_sessions > 0:
            durations = [session.session_duration_in_seconds for session in sessions]
            average_session_time = sum(durations) / len(durations)
            best_time = min(durations)
            longest_session = max(durations)
        else:
            average_session_time = 0
            best_time = 0
            longest_session = 0
        
        # Time distribution by session type
        session_types = sessions.values('session_type').annotate(
            count=Count('id'),
            total_duration=Sum('session_duration')
        )
        
        # Weekly progress (last 4 weeks)
        weekly_progress = self._get_weekly_progress(user, content_type)
        
        # Content engagement statistics
        unique_content_count = sessions.values('object_id').distinct().count()
        
        # Recent improvement trend (last 10 sessions vs previous 10)
        improvement_trend = self._calculate_improvement_trend(sessions)
        
        return {
            'content_type': content_name,
            'total_sessions': total_sessions,
            'total_time_seconds': total_time_seconds,
            'total_time_formatted': self._format_duration(total_time_seconds),
            'average_session_time': average_session_time,
            'average_session_formatted': self._format_duration(average_session_time),
            'best_time': best_time,
            'best_time_formatted': self._format_duration(best_time),
            'longest_session': longest_session,
            'longest_session_formatted': self._format_duration(longest_session),
            'unique_content_studied': unique_content_count,
            'session_types_distribution': list(session_types),
            'weekly_progress': weekly_progress,
            'improvement_trend': improvement_trend,
            'consistency_score': self._calculate_consistency_score(user, content_type)
        }
    
    def _calculate_overall_stats(self, user):
        """
        Calculate overall statistics across all content types
        """
        all_sessions = TimeSession.objects.filter(user=user)
        total_sessions = all_sessions.count()
        total_time_seconds = sum(session.session_duration_in_seconds for session in all_sessions)
        
        # Study streak calculation
        study_streak = self._calculate_study_streak(user)
        
        # Most active day of week
        most_active_day = self._get_most_active_day(all_sessions)
        
        # Study habits analysis
        study_habits = self._analyze_study_habits(all_sessions)
        
        return {
            'total_sessions_all_content': total_sessions,
            'total_time_all_content': total_time_seconds,
            'total_time_formatted': self._format_duration(total_time_seconds),
            'current_study_streak': study_streak,
            'most_active_day': most_active_day,
            'study_habits': study_habits
        }
    
    def _get_weekly_progress(self, user, content_type):
        """
        Get weekly progress for the last 4 weeks
        """
        now = timezone.now()
        weeks_data = []
        
        for i in range(4):
            week_start = now - timedelta(weeks=i+1)
            week_end = now - timedelta(weeks=i)
            
            week_sessions = TimeSession.objects.filter(
                user=user,
                content_type=content_type,
                created_at__gte=week_start,
                created_at__lt=week_end
            )
            
            total_time = sum(session.session_duration_in_seconds for session in week_sessions)
            session_count = week_sessions.count()
            
            weeks_data.append({
                'week_number': i + 1,
                'week_start': week_start.strftime('%Y-%m-%d'),
                'session_count': session_count,
                'total_time_seconds': total_time,
                'total_time_formatted': self._format_duration(total_time)
            })
        
        return list(reversed(weeks_data))  # Most recent first
    
    def _calculate_improvement_trend(self, sessions):
        """
        Calculate improvement trend based on recent sessions
        """
        recent_sessions = sessions.order_by('-created_at')[:10]
        previous_sessions = sessions.order_by('-created_at')[10:20]
        
        if len(recent_sessions) < 5 or len(previous_sessions) < 5:
            return {'trend': 'insufficient_data', 'percentage': 0}
        
        recent_avg = sum(s.session_duration_in_seconds for s in recent_sessions) / len(recent_sessions)
        previous_avg = sum(s.session_duration_in_seconds for s in previous_sessions) / len(previous_sessions)
        
        if previous_avg == 0:
            return {'trend': 'no_comparison', 'percentage': 0}
        
        percentage_change = ((recent_avg - previous_avg) / previous_avg) * 100
        
        if percentage_change > 5:
            trend = 'improving'
        elif percentage_change < -5:
            trend = 'declining'
        else:
            trend = 'stable'
        
        return {
            'trend': trend,
            'percentage': round(abs(percentage_change), 1)
        }
    
    def _calculate_consistency_score(self, user, content_type):
        """
        Calculate a consistency score based on regular study patterns
        """
        # Get sessions from last 30 days
        thirty_days_ago = timezone.now() - timedelta(days=30)
        recent_sessions = TimeSession.objects.filter(
            user=user,
            content_type=content_type,
            created_at__gte=thirty_days_ago
        ).order_by('created_at')
        
        if recent_sessions.count() < 3:
            return 0
        
        # Calculate days with study activity
        study_days = set()
        for session in recent_sessions:
            study_days.add(session.created_at.date())
        
        # Consistency score based on frequency and regularity
        days_studied = len(study_days)
        consistency_percentage = (days_studied / 30) * 100
        
        return min(100, round(consistency_percentage))
    
    def _calculate_study_streak(self, user):
        """
        Calculate current study streak in days
        """
        today = timezone.now().date()
        streak = 0
        current_date = today
        
        while True:
            has_session = TimeSession.objects.filter(
                user=user,
                created_at__date=current_date
            ).exists()
            
            if has_session:
                streak += 1
                current_date -= timedelta(days=1)
            else:
                break
            
            # Prevent infinite loop
            if streak > 365:
                break
        
        return streak
    
    def _get_most_active_day(self, sessions):
        """
        Get the most active day of the week
        """
        if not sessions.exists():
            return None
        
        day_counts = {}
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        
        for session in sessions:
            day_name = days[session.created_at.weekday()]
            day_counts[day_name] = day_counts.get(day_name, 0) + 1
        
        if not day_counts:
            return None
        
        most_active = max(day_counts, key=day_counts.get)
        return {
            'day': most_active,
            'session_count': day_counts[most_active]
        }
    
    def _analyze_study_habits(self, sessions):
        """
        Analyze study habits and patterns
        """
        if not sessions.exists():
            return {}
        
        # Analyze preferred study times
        morning_sessions = sessions.filter(created_at__hour__lt=12).count()
        afternoon_sessions = sessions.filter(created_at__hour__gte=12, created_at__hour__lt=18).count()
        evening_sessions = sessions.filter(created_at__hour__gte=18).count()
        
        total = sessions.count()
        
        return {
            'preferred_time': {
                'morning': round((morning_sessions / total) * 100, 1) if total > 0 else 0,
                'afternoon': round((afternoon_sessions / total) * 100, 1) if total > 0 else 0,
                'evening': round((evening_sessions / total) * 100, 1) if total > 0 else 0
            },
            'average_sessions_per_week': round((total / 52), 1) if total > 0 else 0
        }
    
    def _get_recent_activity(self, user, limit=10):
        """
        Get recent study activity
        """
        recent_sessions = TimeSession.objects.filter(
            user=user
        ).select_related('content_type').order_by('-created_at')[:limit]
        
        activity_data = []
        for session in recent_sessions:
            # Get the actual content object
            content_object = session.content_object
            content_title = getattr(content_object, 'title', 'Unknown Content')
            
            activity_data.append({
                'id': session.id,
                'content_type': session.content_type.model,
                'content_title': content_title,
                'duration_seconds': session.session_duration_in_seconds,
                'duration_formatted': self._format_duration(session.session_duration_in_seconds),
                'session_type': session.session_type,
                'date': session.created_at.strftime('%Y-%m-%d'),
                'time': session.created_at.strftime('%H:%M')
            })
        
        return activity_data
    
    def _format_duration(self, seconds):
        """
        Format duration in seconds to human readable format
        """
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