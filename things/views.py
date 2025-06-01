from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from datetime import timedelta
import logging

from .models import (
    Exercise, Solution, Comment, Lesson, Exam
)
from interactions.models import TimeSpent, TimeSession
from .serializers import (
    ExerciseSerializer, SolutionSerializer, CommentSerializer,
    LessonSerializer, ExamSerializer
)
from interactions.models import Vote
from interactions.serializers import VoteSerializer

logger = logging.getLogger(__name__)

class VoteMixin:
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def vote(self, request, pk=None):
        obj = self.get_object()
        vote_type = request.data.get('vote_type')
        
        if vote_type not in ['upvote', 'downvote']:
            return Response(
                {'error': 'Invalid vote type'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        content_type = ContentType.objects.get_for_model(obj)
        
        # Check if user already voted
        existing_vote = Vote.objects.filter(
            user=request.user,
            content_type=content_type,
            object_id=obj.id
        ).first()
        
        if existing_vote:
            if existing_vote.vote_type == vote_type:
                # Remove vote if same type
                existing_vote.delete()
                return Response({'message': 'Vote removed'})
            else:
                # Update vote if different type
                existing_vote.vote_type = vote_type
                existing_vote.save()
                return Response({'message': 'Vote updated'})
        else:
            # Create new vote
            Vote.objects.create(
                user=request.user,
                content_type=content_type,
                object_id=obj.id,
                vote_type=vote_type
            )
            return Response({'message': 'Vote created'})

#----------------------------EXERCISE-------------------------------
class ExerciseViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Exercise.objects.all()
    serializer_class = ExerciseSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = []  # Skip authentication

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=['get'], permission_classes=[])
    def view(self, request, pk=None):
        """
        Mark exercise as viewed and return exercise data
        """
        exercise = self.get_object()
        
        # Increment view count
        exercise.views += 1
        exercise.save()
        
        serializer = self.get_serializer(exercise)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def update_session_time(self, request, pk=None):
        """
        Update current session time for this exercise
        """
        exercise = self.get_object()
        time_seconds = request.data.get('time_seconds', 0)
        
        try:
            content_type = ContentType.objects.get_for_model(Exercise)
            
            # Get or create TimeSpent record
            time_spent, created = TimeSpent.objects.get_or_create(
                user=request.user,
                content_type=content_type,
                object_id=exercise.id,
                defaults={
                    'total_time': timedelta(0),
                    'current_session_time': timedelta(seconds=time_seconds),
                    'last_session_start': timezone.now()
                }
            )
            
            if not created:
                time_spent.update_session_time(time_seconds)
                if not time_spent.last_session_start:
                    time_spent.last_session_start = timezone.now()
                    time_spent.save()
            
            return Response({
                'total_time_seconds': time_spent.total_time,
                'current_session_seconds': time_spent.current_session_time,
                'success': True
            })
            
        except Exception as e:
            logger.error(f"Error updating session time: {str(e)}")
            return Response(
                {'error': 'Failed to update session time'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save_session(self, request, pk=None):
        """
        Save current session and add to total time
        """
        exercise = self.get_object()
        session_type = request.data.get('session_type', 'study')
        notes = request.data.get('notes', '')
        
        try:
            content_type = ContentType.objects.get_for_model(Exercise)
            time_spent = TimeSpent.objects.get(
                user=request.user,
                content_type=content_type,
                object_id=exercise.id
            )
            
            if time_spent.save_and_reset_session(session_type=session_type, notes=notes):
                return Response({
                    'message': 'Session saved successfully',
                    'total_time_seconds': time_spent.total_time
                })
            else:
                return Response(
                    {'error': 'No active session to save'},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except TimeSpent.DoesNotExist:
            return Response(
                {'error': 'No time tracking data found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error saving session: {str(e)}")
            return Response(
                {'error': 'Failed to save session'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def session_history(self, request, pk=None):
        """
        Get session history for this exercise
        """
        exercise = self.get_object()
        
        try:
            content_type = ContentType.objects.get_for_model(Exercise)
            
            # Get all sessions for this exercise
            sessions = TimeSession.objects.filter(
                user=request.user,
                content_type=content_type,
                object_id=exercise.id
            ).order_by('-created_at')[:20]  # Limit to last 20 sessions
            
            # Format the response
            session_data = [{
                'id': str(session.id),
                'session_duration': int(session.session_duration.total_seconds()),
                'started_at': session.started_at.isoformat(),
                'ended_at': session.ended_at.isoformat(),
                'created_at': session.created_at.isoformat(),
                'session_type': session.session_type,
                'notes': session.notes
            } for session in sessions]
            
            return Response({
                'sessions': session_data
            })
            
        except Exception as e:
            logger.error(f"Error retrieving session history: {str(e)}")
            return Response(
                {'error': 'Failed to retrieve session history'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated], url_path='delete_session/(?P<session_id>[^/.]+)')
    def delete_session(self, request, pk=None, session_id=None):
        """
        Delete a specific session
        """
        exercise = self.get_object()
        
        try:
            content_type = ContentType.objects.get_for_model(Exercise)
            
            # Get the session to delete
            session = TimeSession.objects.get(
                id=session_id,
                user=request.user,
                content_type=content_type,
                object_id=exercise.id
            )
            
            session.delete()
            
            return Response({
                'message': 'Session deleted successfully'
            })
            
        except TimeSession.DoesNotExist:
            return Response(
                {'error': 'Session not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error deleting session: {str(e)}")
            return Response(
                {'error': 'Failed to delete session'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

#----------------------------SOLUTION-------------------------------
class SolutionViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Solution.objects.all()
    serializer_class = SolutionSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = []  # Skip authentication

    def perform_create(self, serializer):
        serializer.save()

#----------------------------COMMENT-------------------------------
class CommentViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = []  # Skip authentication

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=False, methods=['get'])
    def by_exercise(self, request):
        exercise_id = request.query_params.get('exercise_id')
        if exercise_id:
            comments = Comment.objects.filter(exercise_id=exercise_id)
            serializer = self.get_serializer(comments, many=True)
            return Response(serializer.data)
        return Response({'error': 'exercise_id parameter required'}, status=400)

    @action(detail=False, methods=['get'])
    def by_solution(self, request):
        solution_id = request.query_params.get('solution_id')
        if solution_id:
            comments = Comment.objects.filter(solution_id=solution_id)
            serializer = self.get_serializer(comments, many=True)
            return Response(serializer.data)
        return Response({'error': 'solution_id parameter required'}, status=400)

#----------------------------LESSON-------------------------------
class LessonViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = []  # Skip authentication

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=['get'], permission_classes=[])
    def view(self, request, pk=None):
        """
        Mark lesson as viewed and return lesson data
        """
        lesson = self.get_object()
        
        # Increment view count
        lesson.views += 1
        lesson.save()
        
        serializer = self.get_serializer(lesson)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def update_session_time(self, request, pk=None):
        """
        Update current session time for this lesson
        """
        lesson = self.get_object()
        time_seconds = request.data.get('time_seconds', 0)
        
        try:
            content_type = ContentType.objects.get_for_model(Lesson)
            
            # Get or create TimeSpent record
            time_spent, created = TimeSpent.objects.get_or_create(
                user=request.user,
                content_type=content_type,
                object_id=lesson.id,
                defaults={
                    'total_time': timedelta(0),
                    'current_session_time': timedelta(seconds=time_seconds),
                    'last_session_start': timezone.now()
                }
            )
            
            if not created:
                time_spent.update_session_time(time_seconds)
                if not time_spent.last_session_start:
                    time_spent.last_session_start = timezone.now()
                    time_spent.save()
            
            return Response({
                'total_time_seconds': time_spent.total_time,
                'current_session_seconds': time_spent.current_session_time,
                'success': True
            })
            
        except Exception as e:
            logger.error(f"Error updating session time: {str(e)}")
            return Response(
                {'error': 'Failed to update session time'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save_session(self, request, pk=None):
        """
        Save current session and add to total time
        """
        lesson = self.get_object()
        session_type = request.data.get('session_type', 'study')
        notes = request.data.get('notes', '')
        
        try:
            content_type = ContentType.objects.get_for_model(Lesson)
            time_spent = TimeSpent.objects.get(
                user=request.user,
                content_type=content_type,
                object_id=lesson.id
            )
            
            if time_spent.save_and_reset_session(session_type=session_type, notes=notes):
                return Response({
                    'message': 'Session saved successfully',
                    'total_time_seconds': time_spent.total_time
                })
            else:
                return Response(
                    {'error': 'No active session to save'},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except TimeSpent.DoesNotExist:
            return Response(
                {'error': 'No time tracking data found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error saving session: {str(e)}")
            return Response(
                {'error': 'Failed to save session'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

#----------------------------EXAM-------------------------------
class ExamViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Exam.objects.all()
    serializer_class = ExamSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = []  # Skip authentication

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=['get'], permission_classes=[])
    def view(self, request, pk=None):
        """
        Mark exam as viewed and return exam data
        """
        exam = self.get_object()
        
        # Increment view count
        exam.views += 1
        exam.save()
        
        serializer = self.get_serializer(exam)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def update_session_time(self, request, pk=None):
        """
        Update current session time for this exam
        """
        exam = self.get_object()
        time_seconds = request.data.get('time_seconds', 0)
        
        try:
            content_type = ContentType.objects.get_for_model(Exam)
            
            # Get or create TimeSpent record
            time_spent, created = TimeSpent.objects.get_or_create(
                user=request.user,
                content_type=content_type,
                object_id=exam.id,
                defaults={
                    'total_time': timedelta(0),
                    'current_session_time': timedelta(seconds=time_seconds),
                    'last_session_start': timezone.now()
                }
            )
            
            if not created:
                time_spent.update_session_time(time_seconds)
                if not time_spent.last_session_start:
                    time_spent.last_session_start = timezone.now()
                    time_spent.save()
            
            return Response({
                'total_time_seconds': time_spent.total_time,
                'current_session_seconds': time_spent.current_session_time,
                'success': True
            })
            
        except Exception as e:
            logger.error(f"Error updating session time: {str(e)}")
            return Response(
                {'error': 'Failed to update session time'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save_session(self, request, pk=None):
        """
        Save current session and add to total time
        """
        exam = self.get_object()
        session_type = request.data.get('session_type', 'study')
        notes = request.data.get('notes', '')
        
        try:
            content_type = ContentType.objects.get_for_model(Exam)
            time_spent = TimeSpent.objects.get(
                user=request.user,
                content_type=content_type,
                object_id=exam.id
            )
            
            if time_spent.save_and_reset_session(session_type=session_type, notes=notes):
                return Response({
                    'message': 'Session saved successfully',
                    'total_time_seconds': time_spent.total_time
                })
            else:
                return Response(
                    {'error': 'No active session to save'},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except TimeSpent.DoesNotExist:
            return Response(
                {'error': 'No time tracking data found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error saving session: {str(e)}")
            return Response(
                {'error': 'Failed to save session'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def session_history(self, request, pk=None):
        """
        Get session history for this exam
        """
        exam = self.get_object()
        
        try:
            content_type = ContentType.objects.get_for_model(Exam)
            
            # Get all sessions for this exam
            sessions = TimeSession.objects.filter(
                user=request.user,
                content_type=content_type,
                object_id=exam.id
            ).order_by('-created_at')[:20]  # Limit to last 20 sessions
            
            # Format the response
            session_data = [{
                'id': str(session.id),
                'session_duration': int(session.session_duration.total_seconds()),
                'started_at': session.started_at.isoformat(),
                'ended_at': session.ended_at.isoformat(),
                'created_at': session.created_at.isoformat(),
                'session_type': session.session_type,
                'notes': session.notes
            } for session in sessions]
            
            return Response({
                'sessions': session_data
            })
            
        except Exception as e:
            logger.error(f"Error retrieving session history: {str(e)}")
            return Response(
                {'error': 'Failed to retrieve session history'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )