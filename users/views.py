from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth.models import User
from django.db.models import Q, Count, Avg, Sum, F
from django.contrib.contenttypes.models import ContentType
from datetime import datetime, timedelta
from django.utils import timezone

from .models import UserProfile
from .serializers import UserProfileSerializer, UserSerializer, UserSettingsSerializer, OnboardingSerializer
from things.models import Exercise, Exam
from .models import ViewHistory
from interactions.models import TimeSession, TimeSpent


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    lookup_field = 'username'
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return UserProfileSerializer
        return UserSerializer

    def get_queryset(self):
        return User.objects.select_related('profile').all()

    @action(detail=True, methods=['get'])
    def profile(self, request, username=None):
        """Get user profile information"""
        user = self.get_object()
        serializer = UserProfileSerializer(user.profile)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def stats(self, request, username=None):
        """Get user statistics"""
        user = self.get_object()
        
        # Get contribution stats
        contribution_stats = user.profile.get_contribution_stats()
        
        # Get learning stats
        learning_stats = user.profile.get_learning_stats()
        
        # Get view count for user's exercises
        view_count = ViewHistory.objects.filter(
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id__in=Exercise.objects.filter(author=user).values_list('id', flat=True)
        ).count()
        
        contribution_stats['view_count'] = view_count
        
        return Response({
            'contribution_stats': contribution_stats,
            'learning_stats': learning_stats
        })

    @action(detail=True, methods=['get'])
    def contributions(self, request, username=None):
        """Get user contributions (exercises created)"""
        user = self.get_object()
        exercises = Exercise.objects.filter(author=user).order_by('-created_at')
        
        # Simple serialization - you might want to use a proper serializer
        data = []
        for exercise in exercises:
            data.append({
                'id': exercise.id,
                'title': exercise.title,
                'description': exercise.description,
                'difficulty': exercise.difficulty,
                'created_at': exercise.created_at,
                'subject': {
                    'id': exercise.subject.id,
                    'name': exercise.subject.name
                } if exercise.subject else None,
                'chapters': [{
                    'id': chapter.id,
                    'name': chapter.name
                } for chapter in exercise.chapters.all()],
                'class_levels': [{
                    'id': level.id,
                    'name': level.name
                } for level in exercise.class_levels.all()],
                'vote_score': exercise.vote_score,
                'view_count': ViewHistory.objects.filter(
                    content_type=ContentType.objects.get_for_model(Exercise),
                    object_id=exercise.id
                ).count()
            })
        
        return Response({'results': data})

    @action(detail=True, methods=['get'])
    def saved_exercises(self, request, username=None):
        """Get user's saved exercises"""
        user = self.get_object()
        
        # Check if requesting user is the profile owner
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error': 'You cannot view other users\' saved exercises'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get saved exercises from ViewHistory or a dedicated SavedExercise model
        # For now, we'll return exercises the user has interacted with
        viewed_exercises = ViewHistory.objects.filter(
            user=user,
            content_type=ContentType.objects.get_for_model(Exercise)
        ).values_list('object_id', flat=True)
        
        exercises = Exercise.objects.filter(id__in=viewed_exercises).order_by('-created_at')
        
        data = []
        for exercise in exercises:
            data.append({
                'id': exercise.id,
                'title': exercise.title,
                'description': exercise.description,
                'difficulty': exercise.difficulty,
                'created_at': exercise.created_at,
                'subject': {
                    'id': exercise.subject.id,
                    'name': exercise.subject.name
                } if exercise.subject else None,
                'chapters': [{
                    'id': chapter.id,
                    'name': chapter.name
                } for chapter in exercise.chapters.all()],
                'class_levels': [{
                    'id': level.id,
                    'name': level.name
                } for level in exercise.class_levels.all()],
                'vote_score': exercise.vote_score
            })
        
        return Response(data)

    @action(detail=True, methods=['get'])
    def progress_exercises(self, request, username=None):
        """Get user's progress on exercises"""
        user = self.get_object()
        
        # Check if requesting user is the profile owner
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error': 'You cannot view other users\' progress'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get exercises with progress data
        # This is a simplified version - you might want to add more sophisticated progress tracking
        viewed_exercises = ViewHistory.objects.filter(
            user=user,
            content_type=ContentType.objects.get_for_model(Exercise)
        ).select_related('content_object')
        
        success_exercises = []
        review_exercises = []
        
        for view in viewed_exercises:
            exercise_data = {
                'id': view.object_id,
                'title': getattr(view.content_object, 'title', 'Unknown'),
                'description': getattr(view.content_object, 'description', ''),
                'difficulty': getattr(view.content_object, 'difficulty', 'medium'),
                'last_viewed': view.viewed_at,
                'time_spent': view.time_spent
            }
            
            # Simple logic to categorize - you can make this more sophisticated
            if view.time_spent > 300:  # More than 5 minutes
                success_exercises.append(exercise_data)
            else:
                review_exercises.append(exercise_data)
        
        return Response({
            'success': success_exercises,
            'review': review_exercises
        })

    @action(detail=True, methods=['get'])
    def history(self, request, username=None):
        """Get user's view history"""
        user = self.get_object()
        
        # Check if requesting user is the profile owner
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error': 'You cannot view other users\' history'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        history = ViewHistory.objects.filter(user=user).order_by('-viewed_at')[:50]
        
        data = []
        for item in history:
            data.append({
                'id': item.id,
                'content_type': item.content_type.model,
                'object_id': item.object_id,
                'title': getattr(item.content_object, 'title', 'Unknown'),
                'viewed_at': item.viewed_at,
                'time_spent': item.time_spent
            })
        
        return Response(data)

    @action(detail=True, methods=['patch'])
    def update_profile(self, request, username=None):
        """Update user profile"""
        user = self.get_object()
        
        # Check if requesting user is the profile owner
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error': 'You cannot update other users\' profiles'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = UserProfileSerializer(user.profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def get_time_spent(self,request,username = None):
        """Get time spent on specific exercise for the user"""
        user = self.get_object()
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error' : 'You cannnot view other users \' progress'}
            )
        content_type = ContentType.objects.get_for_model(Exercise)

    @action(detail=True, methods=['get'])
    def time_statistics(self, request, username=None):
        """Get comprehensive time statistics for the user"""
        user = self.get_object()
        
        # Check if requesting user is the profile owner
        if user.id != request.user.id and not request.user.is_superuser:
            return Response(
                {'error': 'You cannot view other users\' time statistics'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get content types
        exercise_content_type = ContentType.objects.get_for_model(Exercise)
        exam_content_type = ContentType.objects.get_for_model(Exam)
        
        # Get exercise time statistics
        exercise_sessions = TimeSession.objects.filter(
            user=user,
            content_type=exercise_content_type
        )
        
        exercise_stats = {
            'total_sessions': exercise_sessions.count(),
            'total_time_seconds': sum(session.session_duration_in_seconds for session in exercise_sessions),
            'average_session_time': 0,
            'best_session_time': 0,
            'worst_session_time': 0,
            'sessions_this_week': 0,
            'sessions_this_month': 0,
            'time_this_week': 0,
            'time_this_month': 0,
            'recent_sessions': []
        }
        
        if exercise_sessions.exists():
            durations = [s.session_duration_in_seconds for s in exercise_sessions]
            exercise_stats['average_session_time'] = sum(durations) / len(durations)
            exercise_stats['best_session_time'] = min(durations)
            exercise_stats['worst_session_time'] = max(durations)
            
            # Weekly and monthly stats
            week_ago = timezone.now() - timedelta(days=7)
            month_ago = timezone.now() - timedelta(days=30)
            
            weekly_sessions = exercise_sessions.filter(created_at__gte=week_ago)
            monthly_sessions = exercise_sessions.filter(created_at__gte=month_ago)
            
            exercise_stats['sessions_this_week'] = weekly_sessions.count()
            exercise_stats['sessions_this_month'] = monthly_sessions.count()
            exercise_stats['time_this_week'] = sum(s.session_duration_in_seconds for s in weekly_sessions)
            exercise_stats['time_this_month'] = sum(s.session_duration_in_seconds for s in monthly_sessions)
            
            # Recent sessions
            recent = exercise_sessions.order_by('-created_at')[:10]
            exercise_stats['recent_sessions'] = [{
                'id': str(s.id),
                'duration_seconds': s.session_duration_in_seconds,
                'started_at': s.started_at.isoformat(),
                'ended_at': s.ended_at.isoformat(),
                'session_type': s.session_type,
                'content_title': getattr(s.content_object, 'title', 'Unknown') if s.content_object else 'Unknown'
            } for s in recent]
        
        # Get exam time statistics
        exam_sessions = TimeSession.objects.filter(
            user=user,
            content_type=exam_content_type
        )
        
        exam_stats = {
            'total_sessions': exam_sessions.count(),
            'total_time_seconds': sum(session.session_duration_in_seconds for session in exam_sessions),
            'average_session_time': 0,
            'best_session_time': 0,
            'worst_session_time': 0,
            'sessions_this_week': 0,
            'sessions_this_month': 0,
            'time_this_week': 0,
            'time_this_month': 0,
            'recent_sessions': []
        }
        
        if exam_sessions.exists():
            durations = [s.session_duration_in_seconds for s in exam_sessions]
            exam_stats['average_session_time'] = sum(durations) / len(durations)
            exam_stats['best_session_time'] = min(durations)
            exam_stats['worst_session_time'] = max(durations)
            
            # Weekly and monthly stats
            weekly_sessions = exam_sessions.filter(created_at__gte=week_ago)
            monthly_sessions = exam_sessions.filter(created_at__gte=month_ago)
            
            exam_stats['sessions_this_week'] = weekly_sessions.count()
            exam_stats['sessions_this_month'] = monthly_sessions.count()
            exam_stats['time_this_week'] = sum(s.session_duration_in_seconds for s in weekly_sessions)
            exam_stats['time_this_month'] = sum(s.session_duration_in_seconds for s in monthly_sessions)
            
            # Recent sessions
            recent = exam_sessions.order_by('-created_at')[:10]
            exam_stats['recent_sessions'] = [{
                'id': str(s.id),
                'duration_seconds': s.session_duration_in_seconds,
                'started_at': s.started_at.isoformat(),
                'ended_at': s.ended_at.isoformat(),
                'session_type': s.session_type,
                'content_title': getattr(s.content_object, 'title', 'Unknown') if s.content_object else 'Unknown'
            } for s in recent]
        
        # Overall statistics
        total_sessions = exercise_stats['total_sessions'] + exam_stats['total_sessions']
        total_time = exercise_stats['total_time_seconds'] + exam_stats['total_time_seconds']
        
        overall_stats = {
            'total_sessions': total_sessions,
            'total_time_seconds': total_time,
            'total_time_hours': round(total_time / 3600, 2),
            'sessions_this_week': exercise_stats['sessions_this_week'] + exam_stats['sessions_this_week'],
            'sessions_this_month': exercise_stats['sessions_this_month'] + exam_stats['sessions_this_month'],
            'time_this_week': exercise_stats['time_this_week'] + exam_stats['time_this_week'],
            'time_this_month': exercise_stats['time_this_month'] + exam_stats['time_this_month'],
            'average_daily_time': round(total_time / max(1, (timezone.now() - user.date_joined).days), 2) if user.date_joined else 0
        }
        
        return Response({
            'exercise_stats': exercise_stats,
            'exam_stats': exam_stats,
            'overall_stats': overall_stats
        })


class UserSettingsView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get current user settings"""
        serializer = UserSettingsSerializer(request.user.profile)
        return Response(serializer.data)
    
    def patch(self, request):
        """Update user settings"""
        serializer = UserSettingsSerializer(request.user.profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_current_user(request):
    """Get current authenticated user information"""
    serializer = UserSerializer(request.user)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_content_viewed(request, content_id):
    """Mark content as viewed and update view count"""
    try:
        content = Exercise.objects.get(id=content_id)
        time_spent = request.data.get('time_spent', 0)
        
        # Get or create view history entry
        view_history, created = ViewHistory.objects.get_or_create(
            user=request.user,
            content_type=ContentType.objects.get_for_model(Exercise),
            object_id=content_id,
            defaults={'time_spent': time_spent}
        )
        
        if not created:
            # Update time spent if entry already exists
            view_history.time_spent = max(view_history.time_spent, time_spent)
            view_history.viewed_at = timezone.now()
            view_history.save()
        
        return Response({'status': 'success'})
    except Exercise.DoesNotExist:
        return Response({'error': 'Exercise not found'}, status=status.HTTP_404_NOT_FOUND)
    

# Alias for URL routing
UserProfileViewSet = UserViewSet
    

