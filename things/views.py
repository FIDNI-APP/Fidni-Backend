from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
import rest_framework
from datetime import timedelta
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction


from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q, Avg, F
from django.conf import settings

# Check if using PostgreSQL for trigram support
USE_TRIGRAM = 'postgresql' in settings.DATABASES['default']['ENGINE']

# Import TrigramSimilarity only if using PostgreSQL
if USE_TRIGRAM:
    try:
        from django.contrib.postgres.search import TrigramSimilarity
    except ImportError:
        USE_TRIGRAM = False
        TrigramSimilarity = None  # Dummy value
else:
    TrigramSimilarity = None  # Dummy value for SQLite


from .models import Exercise, Solution, Comment, Lesson, Exam
from .serializers import  ExerciseSerializer, SolutionSerializer, CommentSerializer, ExerciseCreateSerializer, LessonSerializer, LessonCreateSerializer
from interactions.models import Vote, Save, Complete, TimeSpent, TimeSession, SolutionView, SolutionMatch
from interactions.serializers import VoteSerializer, SaveSerializer, CompleteSerializer, TimeSpentSerializer
from interactions.views import VoteMixin
from users.models import ViewHistory
from rest_framework.permissions import IsAuthenticatedOrReadOnly,IsAuthenticated


import logging


logger = logging.getLogger('django')



#----------------------------PAGINATION-------------------------------
class LargeResultsSetPagination(PageNumberPagination):
    page_size = 1000
    page_size_query_param = 'page_size'
    max_page_size = 10000

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 1000
    page_size_query_param = 'page_size'
    max_page_size = 1000
    
#----------------------------EXERCISE-------------------------------


class ExerciseViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Exercise.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = StandardResultsSetPagination  

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ExerciseCreateSerializer
        return ExerciseSerializer

    def get_queryset(self):
        queryset = Exercise.objects.all().select_related(
            'author', 'solution', 'subject'
        ).prefetch_related(
            'chapters',
            'class_levels',
            'subject',
            'comments',
            'votes',
            'theorems',
            'subfields'
        ).annotate(
            vote_count_annotation=Count('votes', filter=Q(votes__value=Vote.UP)) - 
                                  Count('votes', filter=Q(votes__value=Vote.DOWN))
        )

        # Search functionality with optional fuzzy matching
        search_query = self.request.query_params.get('search', None)
        if search_query:
            if USE_TRIGRAM:
                # PostgreSQL: Use trigram similarity for fuzzy matching
                queryset = queryset.annotate(
                    title_similarity=TrigramSimilarity('title', search_query),
                    content_similarity=TrigramSimilarity('content', search_query),
                ).filter(
                    Q(title__icontains=search_query) |
                    Q(content__icontains=search_query) |
                    Q(subject__name__icontains=search_query) |
                    Q(chapters__name__icontains=search_query) |
                    Q(theorems__name__icontains=search_query) |
                    Q(subfields__name__icontains=search_query) |
                    Q(class_levels__name__icontains=search_query) |
                    Q(title_similarity__gt=0.1) |
                    Q(content_similarity__gt=0.1)
                ).order_by('-title_similarity', '-content_similarity')
            else:
                # SQLite: Use simple case-insensitive search
                queryset = queryset.filter(
                    Q(title__icontains=search_query) |
                    Q(content__icontains=search_query) |
                    Q(subject__name__icontains=search_query) |
                    Q(chapters__name__icontains=search_query) |
                    Q(theorems__name__icontains=search_query) |
                    Q(subfields__name__icontains=search_query) |
                    Q(class_levels__name__icontains=search_query)
                )

        # Filtering
        class_levels = self.request.query_params.getlist('class_levels[]')
        subjects = self.request.query_params.getlist('subjects[]')
        chapters = self.request.query_params.getlist('chapters[]')
        difficulties = self.request.query_params.getlist('difficulties[]')
        subfields = self.request.query_params.getlist('subfields[]')
        theorems = self.request.query_params.getlist('theorems[]')


        filters_subject = Q()
        filters_class_level = Q()
        filters_subfield = Q()
        filters_chapter = Q()
        filters_theorem = Q()
        filters_difficulty = Q()


        if class_levels:
            filters_class_level |= Q(class_levels__id__in=class_levels)
        if subjects:
            filters_subject |= Q(subject__id__in=subjects)
        if subfields:
            filters_subfield |= Q(subfields__id__in=subfields)
        if theorems:
            filters_theorem |= Q(theorems__id__in=theorems)
        if chapters:
            filters_chapter |= Q(chapters__id__in=chapters)
        if difficulties:
            filters_difficulty |= Q(difficulty__in=difficulties)
        filters = (filters_subject) & (filters_class_level) & (filters_subfield) & (filters_chapter) & (filters_theorem) & (filters_difficulty)
        queryset = queryset.filter(filters)
        return queryset.distinct()
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def vote(self, request, pk=None):
        return super().vote(request, pk)  # Call the parent class implementation

     
    @action(detail=True, methods=['post'])
    def comment(self, request, pk=None):
        exercise = self.get_object()
        serializer = CommentSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save(
                exercise=exercise,
                author=request.user,
                parent_id=request.data.get('parent')  # Pass parent_id here
            )
            return Response(
                serializer.data,
                status=status.HTTP_201_CREATED
            )
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )
    @action(detail=True, methods=['post'])
    def solution(self, request, pk=None):
        exercise = self.get_object()
        serializer = SolutionSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save(
                exercise=exercise,
                author=request.user,
                content=request.data.get('content')  
            )
            return Response(
                serializer.data,
                status=status.HTTP_201_CREATED
            )
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def mark_progress(self, request, pk=None):
        """
        Mark an exercise as completed with status 'success' or 'review'
        """
        exercise = self.get_object()
        status_value = request.data.get('status')
        
        if status_value not in ['success', 'review']:
            return Response(
                {'error': 'Invalid status value. Must be "success" or "review".'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        content_type = ContentType.objects.get_for_model(Exercise)
        progress, created = Complete.objects.update_or_create(
            user=request.user,
            content_type=content_type,
            object_id=exercise.id,
            defaults={'status': status_value}
        )
        
        logger.debug(f"Exercise {exercise.id} marked as {status_value} by user {request.user.id}")
        
        return Response({
            'id': progress.id,
            'status': progress.status,
            'created_at': progress.created_at,
            'updated_at': progress.updated_at
        })
    
    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated])
    def remove_progress(self, request, pk=None):
        """
        Remove progress marking from an exercise
        """
        exercise = self.get_object()
        content_type = ContentType.objects.get_for_model(Exercise)
        
        try:
            progress = Complete.objects.get(
                user=request.user,
                content_type=content_type,
                object_id=exercise.id
            )
            progress.delete()
            logger.debug(f"Progress removed for exercise {exercise.id} by user {request.user.id}")
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Complete.DoesNotExist:
            return Response(
                {'error': 'No progress record found for this exercise'}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    # Update this function in things/views.py
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save_exercise(self, request, pk=None):
        """
        Save an exercise for later
        """
        try:
            exercise = self.get_object()
            content_type = ContentType.objects.get_for_model(Exercise)
            
            # Check if already saved
            existing = Save.objects.filter(
                user=request.user,
                content_type=content_type,
                object_id=exercise.id
            ).first()
            
            if existing:
                # Return a more descriptive response for already saved
                return Response(
                    {
                        'error': 'Exercise already saved',
                        'message': 'This exercise is already in your saved list',
                        'already_saved': True
                    }, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create new save record
            save = Save.objects.create(
                user=request.user,
                content_type=content_type,
                object_id=exercise.id
            )
            
            logger.debug(f"Exercise {exercise.id} saved by user {request.user.id}")
            
            return Response({
                'id': save.id,
                'saved_at': save.saved_at,
                'message': 'Exercise saved successfully'
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error saving exercise: {str(e)}")
            return Response(
                {'error': 'Failed to save exercise', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated])
    def unsave_exercise(self, request, pk=None):
        """
        Remove exercise from saved list
        """
        exercise = self.get_object()
        content_type = ContentType.objects.get_for_model(Exercise)
        
        try:
            save = Save.objects.get(
                user=request.user,
                content_type=content_type,
                object_id=exercise.id
            )
            save.delete()
            logger.debug(f"Exercise {exercise.id} unsaved by user {request.user.id}")
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Save.DoesNotExist:
            return Response(
                {'error': 'Exercise not found in saved list'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def session_stats(self, request, pk=None):
        """
        Get session statistics and history for comparison
        """
        exercise = self.get_object()
        content_type = ContentType.objects.get_for_model(Exercise)
        
        # Get all sessions for this user and exercise
        sessions = TimeSession.objects.filter(
            user=request.user,
            content_type=content_type,
            object_id=exercise.id
        ).order_by('-created_at')[:10]  # Last 10 sessions
        
        # Calculate statistics
        if sessions.exists():
            durations = [s.session_duration_in_seconds for s in sessions]
            stats = {
                'total_sessions': sessions.count(),
                'best_time': min(durations),
                'worst_time': max(durations),
                'average_time': sum(durations) / len(durations),
                'last_session': {
                    'id': sessions[0].id,
                    'duration_seconds': sessions[0].session_duration_in_seconds,
                    'session_type': sessions[0].session_type,
                    'started_at': sessions[0].started_at,
                    'ended_at': sessions[0].ended_at,
                    'notes': sessions[0].notes,
                    'created_at': sessions[0].created_at
                } if sessions else None,
                'improvement_percentage': None
            }
            
            # Calculate improvement between last two sessions
            if len(sessions) >= 2:
                last_time = sessions[0].session_duration_in_seconds
                previous_time = sessions[1].session_duration_in_seconds
                if previous_time > 0:
                    improvement = ((previous_time - last_time) / previous_time) * 100
                    stats['improvement_percentage'] = round(improvement, 1)
        else:
            stats = {
                'total_sessions': 0,
                'best_time': None,
                'worst_time': None,
                'average_time': None,
                'last_session': None,
                'improvement_percentage': None
            }
        
        # Format sessions for response
        sessions_data = [
            {
                'id': session.id,
                'duration_seconds': session.session_duration_in_seconds,
                'session_type': session.session_type,
                'started_at': session.started_at,
                'ended_at': session.ended_at,
                'notes': session.notes,
                'created_at': session.created_at
            }
            for session in sessions
        ]
        
        return Response({
            'sessions': sessions_data,
            'stats': stats
        })

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save_session(self, request, pk=None):
        """
        Save a completed timing session
        """
        exercise = self.get_object()
        duration_seconds = request.data.get('duration_seconds', 0)
        session_type = request.data.get('session_type', 'practice')
        notes = request.data.get('notes', '')
        
        try:
            duration_seconds = int(duration_seconds)
            if duration_seconds <= 0:
                return Response(
                    {'error': 'Duration must be greater than 0'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (TypeError, ValueError):
            return Response(
                {'error': 'Invalid duration value'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            content_type = ContentType.objects.get_for_model(Exercise)
            
            # Create the session record
            session = TimeSession.objects.create(
                user=request.user,
                content_type=content_type,
                object_id=exercise.id,
                session_duration=timedelta(seconds=duration_seconds),
                started_at=timezone.now() - timedelta(seconds=duration_seconds),
                ended_at=timezone.now(),
                session_type=session_type,
                notes=notes
            )
            
            # Get previous session for comparison
            previous_sessions = TimeSession.objects.filter(
                user=request.user,
                content_type=content_type,
                object_id=exercise.id
            ).exclude(id=session.id).order_by('-created_at')
            
            response_data = {
                'message': 'Session saved successfully',
                'session': {
                    'id': session.id,
                    'duration_seconds': session.session_duration_in_seconds,
                    'created_at': session.created_at
                }
            }
            
            # Add comparison data if there's a previous session
            if previous_sessions.exists():
                previous = previous_sessions.first()
                improvement = None
                if previous.session_duration_in_seconds > 0:
                    improvement = ((previous.session_duration_in_seconds - duration_seconds) / previous.session_duration_in_seconds) * 100
                
                response_data['comparison'] = {
                    'previous_duration': previous.session_duration_in_seconds,
                    'difference': duration_seconds - previous.session_duration_in_seconds,
                    'improvement_percentage': round(improvement, 1) if improvement is not None else None
                }
            
            return Response(response_data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error saving session: {str(e)}")
            return Response(
                {'error': 'Failed to save session'},
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
            session = TimeSession.objects.get(
                id=session_id,
                user=request.user,
                content_type=content_type,
                object_id=exercise.id
            )
            session.delete()
            
            return Response(status=status.HTTP_204_NO_CONTENT)
        except TimeSession.DoesNotExist:
            return Response(
                {'error': 'Session not found'},
                status=status.HTTP_404_NOT_FOUND
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

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """
        Get statistics for this exercise
        Returns: success rate, average time, best time, user's percentile, etc.
        """
        exercise = self.get_object()

        try:
            content_type = ContentType.objects.get_for_model(Exercise)

            # Get all completions for this exercise
            completions = Complete.objects.filter(
                content_type=content_type,
                object_id=exercise.id
            )

            success_count = completions.filter(status='success').count()
            review_count = completions.filter(status='review').count()
            total_participants = completions.values('user').distinct().count()

            # Calculate success percentage
            success_percentage = int((success_count / total_participants * 100)) if total_participants > 0 else 0

            # Get average time
            sessions = TimeSession.objects.filter(
                content_type=content_type,
                object_id=exercise.id
            ).all()

            if sessions.exists():
                # Calculate average in Python to avoid DurationField issues
                total_seconds = sum(int(s.session_duration.total_seconds()) for s in sessions)
                average_time_seconds = int(total_seconds / sessions.count())

                # Get best time
                best_time_seconds = min(int(s.session_duration.total_seconds()) for s in sessions)
            else:
                average_time_seconds = 0
                best_time_seconds = 0

            # User's stats
            user_time_seconds = None
            user_time_percentile = None
            user_completed = None

            # Check if user is authenticated
            is_user_authenticated = (hasattr(self.request, 'user') and self.request.user and self.request.user.is_authenticated)

            if is_user_authenticated:
                # Get user's completion status
                user_completion = Complete.objects.filter(
                    user=request.user,
                    content_type=content_type,
                    object_id=exercise.id
                ).first()
                user_completed = user_completion.status if user_completion else None

                # Get user's time
                user_session = sessions.filter(user=request.user).order_by('-created_at').first()
                if user_session:
                    user_time_seconds = int(user_session.session_duration.total_seconds())

                    # Calculate percentile (how many are slower)
                    slower_count = sessions.filter(
                        session_duration__gt=user_session.session_duration
                    ).values('user').distinct().count()
                    user_time_percentile = int((slower_count / max(total_participants, 1)) * 100) if total_participants > 0 else 0

            # Get solution view tracking data
            solution_views = SolutionView.objects.filter(
                content_type=content_type,
                object_id=exercise.id
            )

            # Count users who viewed solution before success
            users_viewed_before_success = 0
            for user in solution_views.values('user').distinct():
                user_id = user['user']
                user_view = solution_views.filter(user=user_id).first()
                user_completion = Complete.objects.filter(
                    user=user_id,
                    content_type=content_type,
                    object_id=exercise.id,
                    status='success'
                ).first()

                # If user viewed solution and either didn't complete or viewed before completing
                if user_view and user_completion:
                    if user_view.viewed_at <= user_completion.created_at:
                        users_viewed_before_success += 1

            solution_views_before_success = users_viewed_before_success

            # Check if current user viewed solution
            user_viewed_solution = False
            # Check if user is authenticated
            is_user_authenticated = (hasattr(self.request, 'user') and self.request.user and self.request.user.is_authenticated)

            if is_user_authenticated:
                user_viewed_solution = solution_views.filter(user=request.user).exists()

            # Get solution match tracking data
            solution_matches = SolutionMatch.objects.filter(
                content_type=content_type,
                object_id=exercise.id
            )

            solution_match_count = solution_matches.count()
            user_solution_matched = False

            if is_user_authenticated:
                user_solution_matched = solution_matches.filter(user=request.user).exists()

            return Response({
                'total_participants': total_participants,
                'success_count': success_count,
                'review_count': review_count,
                'success_percentage': success_percentage,
                'average_time_seconds': average_time_seconds,
                'best_time_seconds': best_time_seconds,
                'solution_views_before_success': solution_views_before_success,
                'user_time_percentile': user_time_percentile,
                'user_completed': user_completed,
                'user_viewed_solution': user_viewed_solution,
                'user_time_seconds': user_time_seconds,
                'solution_match_count': solution_match_count,
                'user_solution_matched': user_solution_matched
            })

        except Exception as e:
            logger.error(f"Error calculating statistics: {str(e)}")
            return Response(
                {'error': 'Failed to calculate statistics'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post', 'delete'], permission_classes=[IsAuthenticated])
    def mark_solution_viewed(self, request, pk=None):
        """
        Mark or unmark that the current user viewed the solution for this exercise
        POST: Mark solution as viewed
        DELETE: Remove the solution view flag
        """
        exercise = self.get_object()

        try:
            content_type = ContentType.objects.get_for_model(Exercise)

            if request.method == 'POST':
                # Create or get the solution view record
                solution_view, created = SolutionView.objects.get_or_create(
                    user=request.user,
                    content_type=content_type,
                    object_id=exercise.id
                )

                return Response({
                    'marked_as_viewed': True,
                    'message': 'Solution view recorded'
                })

            elif request.method == 'DELETE':
                # Delete the solution view record
                deleted_count, _ = SolutionView.objects.filter(
                    user=request.user,
                    content_type=content_type,
                    object_id=exercise.id
                ).delete()

                if deleted_count > 0:
                    return Response({
                        'marked_as_viewed': False,
                        'message': 'Solution view flag removed'
                    })
                else:
                    return Response({
                        'marked_as_viewed': False,
                        'message': 'No solution view flag found'
                    })

        except Exception as e:
            logger.error(f"Error managing solution view: {str(e)}")
            return Response(
                {'error': 'Failed to manage solution view'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post', 'delete'], permission_classes=[IsAuthenticated])
    def mark_solution_match(self, request, pk=None):
        """Mark or unmark that the current user's solution matches the proposed solution"""
        exercise = self.get_object()
        try:
            content_type = ContentType.objects.get_for_model(Exercise)

            if request.method == 'POST':
                solution_match, created = SolutionMatch.objects.get_or_create(
                    user=request.user,
                    content_type=content_type,
                    object_id=exercise.id
                )
                return Response({
                    'solution_matched': True,
                    'message': 'Solution match recorded'
                })

            elif request.method == 'DELETE':
                deleted_count, _ = SolutionMatch.objects.filter(
                    user=request.user,
                    content_type=content_type,
                    object_id=exercise.id
                ).delete()

                if deleted_count > 0:
                    return Response({
                        'solution_matched': False,
                        'message': 'Solution match flag removed'
                    })
                else:
                    return Response({
                        'solution_matched': False,
                        'message': 'No solution match flag found'
                    })

        except Exception as e:
            logger.error(f"Error managing solution match: {str(e)}")
            return Response(
                {'error': 'Failed to manage solution match'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    def view(self, request, pk=None):
        """
        Mark exercise as viewed and increment view count.
        Only counts as a new view if 1 hour has passed since the last view.
        """
        exercise = self.get_object()
        should_count_view = True

        # Check if user is authenticated
        if request.user.is_authenticated:
            content_type = ContentType.objects.get_for_model(Exercise)
            one_hour_ago = timezone.now() - timedelta(hours=1)

            try:
                # Check if there's a recent view (without locking to avoid SQLite issues)
                last_view = ViewHistory.objects.filter(
                    user=request.user,
                    content_type=content_type,
                    object_id=exercise.id,
                    viewed_at__gte=one_hour_ago
                ).exists()

                if last_view:
                    # User viewed this exercise within the last hour, don't count it
                    should_count_view = False
                else:
                    # This is a new view after 1 hour, count it
                    should_count_view = True
                    # Increment view count
                    Exercise.objects.filter(id=exercise.id).update(
                        view_count=F('view_count') + 1
                    )
                    exercise.refresh_from_db()

                # Always update view history (creates or updates the record)
                # Do this after the view count update to minimize lock time
                ViewHistory.objects.update_or_create(
                    user=request.user,
                    content_type=content_type,
                    object_id=exercise.id,
                    defaults={'status': 'viewed'}
                )

            except Exception as e:
                logger.error(f"Error recording view: {str(e)}")
                # If there's an error, still return a response but don't count it
                should_count_view = False

        return Response({
            'view_count': exercise.view_count,
            'counted': should_count_view
        })


#----------------------------SOLUTION-------------------------------
class SolutionViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Solution.objects.all()
    serializer_class = SolutionSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


#----------------------------COMMENT-------------------------------
class CommentViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = []  # Skip authentication


    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


from rest_framework.decorators import api_view, permission_classes

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_bulk_user_status(request):
    """
    Get user's progress and saved status for multiple exercises at once
    """
    exercise_ids = request.data.get('exercise_ids', [])
    if not exercise_ids:
        return Response({})
    
    # Get content type for Exercise model
    content_type = ContentType.objects.get_for_model(Exercise)
    
    # Fetch all saved objects for this user and these exercises
    saved_objects = Save.objects.filter(
        user=request.user,
        content_type=content_type,
        object_id__in=exercise_ids
    )
    
    # Create a dictionary with exercise_id as key
    result = {}
    for exercise_id in exercise_ids:        
        # Check if exercise is saved
        saved = any(str(s.object_id) == exercise_id for s in saved_objects)
        
        # Construct response
        result[exercise_id] = {
            'saved': saved
        }
    
    return Response(result)

class LessonViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Lesson.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = StandardResultsSetPagination


    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return LessonCreateSerializer
        return LessonSerializer

    def get_queryset(self):
        queryset = Lesson.objects.all().select_related(
            'author', 'subject'
        ).prefetch_related(
            'chapters',
            'class_levels',
            'subject',
            'comments',
            'votes',
            'theorems',
            'subfields'
        ).annotate(
            vote_count_annotation=Count('votes', filter=Q(votes__value=Vote.UP)) -
                                  Count('votes', filter=Q(votes__value=Vote.DOWN))
        )

        # Search functionality with optional fuzzy matching
        search_query = self.request.query_params.get('search', None)
        if search_query:
            if USE_TRIGRAM:
                # PostgreSQL: Use trigram similarity for fuzzy matching
                queryset = queryset.annotate(
                    title_similarity=TrigramSimilarity('title', search_query),
                    content_similarity=TrigramSimilarity('content', search_query),
                ).filter(
                    Q(title__icontains=search_query) |
                    Q(content__icontains=search_query) |
                    Q(subject__name__icontains=search_query) |
                    Q(chapters__name__icontains=search_query) |
                    Q(theorems__name__icontains=search_query) |
                    Q(subfields__name__icontains=search_query) |
                    Q(class_levels__name__icontains=search_query) |
                    Q(title_similarity__gt=0.1) |
                    Q(content_similarity__gt=0.1)
                ).order_by('-title_similarity', '-content_similarity')
            else:
                # SQLite: Use simple case-insensitive search
                queryset = queryset.filter(
                    Q(title__icontains=search_query) |
                    Q(content__icontains=search_query) |
                    Q(subject__name__icontains=search_query) |
                    Q(chapters__name__icontains=search_query) |
                    Q(theorems__name__icontains=search_query) |
                    Q(subfields__name__icontains=search_query) |
                    Q(class_levels__name__icontains=search_query)
                )

        # Filtering
        class_levels = self.request.query_params.getlist('class_levels[]')
        subjects = self.request.query_params.getlist('subjects[]')
        chapters = self.request.query_params.getlist('chapters[]')
        subfields = self.request.query_params.getlist('subfields[]')
        theorems = self.request.query_params.getlist('theorems[]')


        filters_subject = Q()
        filters_class_level = Q()
        filters_subfield = Q()
        filters_chapter = Q()
        filters_theorem = Q()

        if class_levels:
            filters_class_level |= Q(class_levels__id__in=class_levels)
        if subjects:
            filters_subject |= Q(subject__id__in=subjects)
        if subfields:
            filters_subfield |= Q(subfields__id__in=subfields)
        if theorems:
            filters_theorem |= Q(theorems__id__in=theorems)
        if chapters:
            filters_chapter |= Q(chapters__id__in=chapters)

        filters = (filters_subject) & (filters_class_level) & (filters_subfield) & (filters_chapter) & (filters_theorem)
        queryset = queryset.filter(filters)
        return queryset.distinct()

    @action(detail=True, methods=['post'])
    def comment(self, request, pk=None):
        lesson = self.get_object()
        
        # Add the lesson_id to the request data
        request_data = request.data.copy()
        request_data['lesson_id'] = pk
        
        serializer = CommentSerializer(
            data=request_data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            comment = serializer.save(author=request.user)
            return Response(
                CommentSerializer(comment, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )
    

# Add these to your things/views.py file

from .models import Exam
from .serializers import ExamSerializer, ExamCreateSerializer

# things/views.py (Update the ExamViewSet class)

class ExamViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Exam.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ExamCreateSerializer
        return ExamSerializer

    def get_queryset(self):
        queryset = Exam.objects.all().select_related(
            'author', 'subject', 'solution'
        ).prefetch_related(
            'chapters',
            'class_levels',
            'subject',
            'comments',
            'votes',
            'theorems',
            'subfields',
            'solution__author',
            'solution__votes'
        ).annotate(
            vote_count_annotation=Count('votes', filter=Q(votes__value=Vote.UP)) -
                                  Count('votes', filter=Q(votes__value=Vote.DOWN))
        )

        # Search functionality with optional fuzzy matching
        search_query = self.request.query_params.get('search', None)
        if search_query:
            if USE_TRIGRAM:
                # PostgreSQL: Use trigram similarity for fuzzy matching
                queryset = queryset.annotate(
                    title_similarity=TrigramSimilarity('title', search_query),
                    content_similarity=TrigramSimilarity('content', search_query),
                ).filter(
                    Q(title__icontains=search_query) |
                    Q(content__icontains=search_query) |
                    Q(subject__name__icontains=search_query) |
                    Q(chapters__name__icontains=search_query) |
                    Q(theorems__name__icontains=search_query) |
                    Q(subfields__name__icontains=search_query) |
                    Q(class_levels__name__icontains=search_query) |
                    Q(title_similarity__gt=0.1) |
                    Q(content_similarity__gt=0.1)
                ).order_by('-title_similarity', '-content_similarity')
            else:
                # SQLite: Use simple case-insensitive search
                queryset = queryset.filter(
                    Q(title__icontains=search_query) |
                    Q(content__icontains=search_query) |
                    Q(subject__name__icontains=search_query) |
                    Q(chapters__name__icontains=search_query) |
                    Q(theorems__name__icontains=search_query) |
                    Q(subfields__name__icontains=search_query) |
                    Q(class_levels__name__icontains=search_query)
                )

        # Filtering
        class_levels = self.request.query_params.getlist('class_levels[]')
        subjects = self.request.query_params.getlist('subjects[]')
        chapters = self.request.query_params.getlist('chapters[]')
        difficulties = self.request.query_params.getlist('difficulties[]')
        subfields = self.request.query_params.getlist('subfields[]')
        theorems = self.request.query_params.getlist('theorems[]')
        is_national_exam = self.request.query_params.get('is_national_exam')

        # Change from date_from/date_to to year_from/year_to
        year_from = self.request.query_params.get('year_from')
        year_to = self.request.query_params.get('year_to')

        filters_subject = Q()
        filters_class_level = Q()
        filters_subfield = Q()
        filters_chapter = Q()
        filters_theorem = Q()
        filters_difficulty = Q()
        filters_national = Q()
        filters_year = Q()

        if class_levels:
            filters_class_level |= Q(class_levels__id__in=class_levels)
        if subjects:
            filters_subject |= Q(subject__id__in=subjects)
        if subfields:
            filters_subfield |= Q(subfields__id__in=subfields)
        if theorems:
            filters_theorem |= Q(theorems__id__in=theorems)
        if chapters:
            filters_chapter |= Q(chapters__id__in=chapters)
        if difficulties:
            filters_difficulty |= Q(difficulty__in=difficulties)
        if is_national_exam is not None:
            # Convert string to boolean
            is_national = is_national_exam.lower() in ['true', '1', 'yes']
            filters_national |= Q(is_national_exam=is_national)

        # Year filtering
        if year_from:
            try:
                year_from_int = int(year_from)
                filters_year &= Q(national_year__gte=year_from_int)
            except ValueError:
                pass  # Invalid year format, ignore

        if year_to:
            try:
                year_to_int = int(year_to)
                filters_year &= Q(national_year__lte=year_to_int)
            except ValueError:
                pass  # Invalid year format, ignore

        filters = (filters_subject) & (filters_class_level) & (filters_subfield) & (filters_chapter) & (filters_theorem) & (filters_difficulty) & (filters_national) & (filters_year)
        queryset = queryset.filter(filters)
        return queryset.distinct()

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def vote(self, request, pk=None):
        return super().vote(request, pk)

    @action(detail=True, methods=['post'])
    def comment(self, request, pk=None):
        exam = self.get_object()
        
        # Add the exam_id to the request data
        request_data = request.data.copy()
        request_data['exam_id'] = pk
        
        serializer = CommentSerializer(
            data=request_data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            comment = serializer.save(author=request.user)
            return Response(
                CommentSerializer(comment, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    @action(detail=True, methods=['post'])
    def view(self, request, pk=None):
        """
        Mark exam as viewed and increment view count.
        Only counts as a new view if 1 hour has passed since the last view.
        """
        exam = self.get_object()
        should_count_view = True

        # Check if user is authenticated
        if request.user.is_authenticated:
            content_type = ContentType.objects.get_for_model(Exam)
            one_hour_ago = timezone.now() - timedelta(hours=1)

            try:
                # Check if there's a recent view (without locking to avoid SQLite issues)
                last_view = ViewHistory.objects.filter(
                    user=request.user,
                    content_type=content_type,
                    object_id=exam.id,
                    viewed_at__gte=one_hour_ago
                ).exists()

                if last_view:
                    # User viewed this exam within the last hour, don't count it
                    should_count_view = False
                else:
                    # This is a new view after 1 hour, count it
                    should_count_view = True
                    # Increment view count
                    Exam.objects.filter(id=exam.id).update(
                        view_count=F('view_count') + 1
                    )
                    exam.refresh_from_db()

                # Always update view history (creates or updates the record)
                # Do this after the view count update to minimize lock time
                ViewHistory.objects.update_or_create(
                    user=request.user,
                    content_type=content_type,
                    object_id=exam.id,
                    defaults={'status': 'viewed'}
                )

            except Exception as e:
                logger.error(f"Error recording view: {str(e)}")
                # If there's an error, still return a response but don't count it
                should_count_view = False

        return Response({
            'view_count': exam.view_count,
            'counted': should_count_view
        })

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def mark_progress(self, request, pk=None):
        """
        Mark an exam as completed with status 'success' or 'review'
        """
        exam = self.get_object()
        status_value = request.data.get('status')
        
        if status_value not in ['success', 'review']:
            return Response(
                {'error': 'Invalid status value. Must be "success" or "review".'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        content_type = ContentType.objects.get_for_model(Exam)
        progress, created = Complete.objects.update_or_create(
            user=request.user,
            content_type=content_type,
            object_id=exam.id,
            defaults={'status': status_value}
        )
        
        logger.debug(f"Exam {exam.id} marked as {status_value} by user {request.user.id}")
        
        return Response({
            'id': progress.id,
            'status': progress.status,
            'created_at': progress.created_at,
            'updated_at': progress.updated_at
        })

    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated])
    def remove_progress(self, request, pk=None):
        """
        Remove progress marking from an exam
        """
        exam = self.get_object()
        content_type = ContentType.objects.get_for_model(Exam)
        
        try:
            progress = Complete.objects.get(
                user=request.user,
                content_type=content_type,
                object_id=exam.id
            )
            progress.delete()
            logger.debug(f"Progress removed for exam {exam.id} by user {request.user.id}")
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Complete.DoesNotExist:
            return Response(
                {'error': 'No progress record found for this exam'}, 
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save_exam(self, request, pk=None):
        """
        Save an exam for later
        """
        try:
            exam = self.get_object()
            content_type = ContentType.objects.get_for_model(Exam)
            
            # Check if already saved
            existing = Save.objects.filter(
                user=request.user,
                content_type=content_type,
                object_id=exam.id
            ).first()
            
            if existing:
                return Response(
                    {
                        'error': 'Exam already saved',
                        'message': 'This exam is already in your saved list',
                        'already_saved': True
                    }, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create new save record
            save = Save.objects.create(
                user=request.user,
                content_type=content_type,
                object_id=exam.id
            )
            
            logger.debug(f"Exam {exam.id} saved by user {request.user.id}")
            
            return Response({
                'id': save.id,
                'saved_at': save.saved_at,
                'message': 'Exam saved successfully'
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error saving exam: {str(e)}")
            return Response(
                {'error': 'Failed to save exam', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated])
    def unsave_exam(self, request, pk=None):
        """
        Remove exam from saved list
        """
        exam = self.get_object()
        content_type = ContentType.objects.get_for_model(Exam)
        
        try:
            save = Save.objects.get(
                user=request.user,
                content_type=content_type,
                object_id=exam.id
            )
            save.delete()
            logger.debug(f"Exam {exam.id} unsaved by user {request.user.id}")
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Save.DoesNotExist:
            return Response(
                {'error': 'Exam not found in saved list'}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def session_stats(self, request, pk=None):
        """
        Get session statistics and history for comparison
        """
        exam = self.get_object()
        content_type = ContentType.objects.get_for_model(Exam)
        
        # Get all sessions for this user and exam
        sessions = TimeSession.objects.filter(
            user=request.user,
            content_type=content_type,
            object_id=exam.id
        ).order_by('-created_at')[:10]  # Last 10 sessions
        
        # Calculate statistics
        if sessions.exists():
            durations = [s.session_duration_in_seconds for s in sessions]
            stats = {
                'total_sessions': sessions.count(),
                'best_time': min(durations),
                'worst_time': max(durations),
                'average_time': sum(durations) / len(durations),
                'last_session': {
                    'id': sessions[0].id,
                    'duration_seconds': sessions[0].session_duration_in_seconds,
                    'session_type': sessions[0].session_type,
                    'started_at': sessions[0].started_at,
                    'ended_at': sessions[0].ended_at,
                    'notes': sessions[0].notes,
                    'created_at': sessions[0].created_at
                } if sessions else None,
                'improvement_percentage': None
            }
            
            # Calculate improvement between last two sessions
            if len(sessions) >= 2:
                last_time = sessions[0].session_duration_in_seconds
                previous_time = sessions[1].session_duration_in_seconds
                if previous_time > 0:
                    improvement = ((previous_time - last_time) / previous_time) * 100
                    stats['improvement_percentage'] = round(improvement, 1)
        else:
            stats = {
                'total_sessions': 0,
                'best_time': None,
                'worst_time': None,
                'average_time': None,
                'last_session': None,
                'improvement_percentage': None
            }
        
        # Format sessions for response
        sessions_data = [
            {
                'id': session.id,
                'duration_seconds': session.session_duration_in_seconds,
                'session_type': session.session_type,
                'started_at': session.started_at,
                'ended_at': session.ended_at,
                'notes': session.notes,
                'created_at': session.created_at
            }
            for session in sessions
        ]
        
        return Response({
            'sessions': sessions_data,
            'stats': stats
        })

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save_session(self, request, pk=None):
        """
        Save a completed timing session
        """
        exam = self.get_object()
        duration_seconds = request.data.get('duration_seconds', 0)
        session_type = request.data.get('session_type', 'practice')
        notes = request.data.get('notes', '')
        
        try:
            duration_seconds = int(duration_seconds)
            if duration_seconds <= 0:
                return Response(
                    {'error': 'Duration must be greater than 0'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (TypeError, ValueError):
            return Response(
                {'error': 'Invalid duration value'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            content_type = ContentType.objects.get_for_model(Exam)
            
            # Create the session record
            session = TimeSession.objects.create(
                user=request.user,
                content_type=content_type,
                object_id=exam.id,
                session_duration=timedelta(seconds=duration_seconds),
                started_at=timezone.now() - timedelta(seconds=duration_seconds),
                ended_at=timezone.now(),
                session_type=session_type,
                notes=notes
            )
            
            # Get previous session for comparison
            previous_sessions = TimeSession.objects.filter(
                user=request.user,
                content_type=content_type,
                object_id=exam.id
            ).exclude(id=session.id).order_by('-created_at')
            
            response_data = {
                'message': 'Session saved successfully',
                'session': {
                    'id': session.id,
                    'duration_seconds': session.session_duration_in_seconds,
                    'created_at': session.created_at
                }
            }
            
            # Add comparison data if there's a previous session
            if previous_sessions.exists():
                previous = previous_sessions.first()
                improvement = None
                if previous.session_duration_in_seconds > 0:
                    improvement = ((previous.session_duration_in_seconds - duration_seconds) / previous.session_duration_in_seconds) * 100
                
                response_data['comparison'] = {
                    'previous_duration': previous.session_duration_in_seconds,
                    'difference': duration_seconds - previous.session_duration_in_seconds,
                    'improvement_percentage': round(improvement, 1) if improvement is not None else None
                }
            
            return Response(response_data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error saving session: {str(e)}")
            return Response(
                {'error': 'Failed to save session'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated], url_path='delete_session/(?P<session_id>[^/.]+)')
    def delete_session(self, request, pk=None, session_id=None):
        """
        Delete a specific session
        """
        exam = self.get_object()
        
        try:
            content_type = ContentType.objects.get_for_model(Exam)
            session = TimeSession.objects.get(
                id=session_id,
                user=request.user,
                content_type=content_type,
                object_id=exam.id
            )
            session.delete()
            
            return Response(status=status.HTTP_204_NO_CONTENT)
        except TimeSession.DoesNotExist:
            return Response(
                {'error': 'Session not found'},
                status=status.HTTP_404_NOT_FOUND
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

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """
        Get statistics for this exam
        Returns: success rate, average time, best time, user's percentile, etc.
        """
        exam = self.get_object()

        try:
            content_type = ContentType.objects.get_for_model(Exam)

            # Get all completions for this exam
            completions = Complete.objects.filter(
                content_type=content_type,
                object_id=exam.id
            )

            success_count = completions.filter(status='success').count()
            review_count = completions.filter(status='review').count()
            total_participants = completions.values('user').distinct().count()

            # Calculate success percentage
            success_percentage = int((success_count / total_participants * 100)) if total_participants > 0 else 0

            # Get average time
            sessions = TimeSession.objects.filter(
                content_type=content_type,
                object_id=exam.id
            ).all()

            if sessions.exists():
                # Calculate average in Python to avoid DurationField issues
                total_seconds = sum(int(s.session_duration.total_seconds()) for s in sessions)
                average_time_seconds = int(total_seconds / sessions.count())

                # Get best time
                best_time_seconds = min(int(s.session_duration.total_seconds()) for s in sessions)
            else:
                average_time_seconds = 0
                best_time_seconds = 0

            # User's stats
            user_time_seconds = None
            user_time_percentile = None
            user_completed = None

            # Check if user is authenticated
            is_user_authenticated = (hasattr(self.request, 'user') and self.request.user and self.request.user.is_authenticated)

            if is_user_authenticated:
                # Get user's completion status
                user_completion = Complete.objects.filter(
                    user=request.user,
                    content_type=content_type,
                    object_id=exam.id
                ).first()
                user_completed = user_completion.status if user_completion else None

                # Get user's time
                user_session = sessions.filter(user=request.user).order_by('-created_at').first()
                if user_session:
                    user_time_seconds = int(user_session.session_duration.total_seconds())

                    # Calculate percentile (how many are slower)
                    slower_count = sessions.filter(
                        session_duration__gt=user_session.session_duration
                    ).values('user').distinct().count()
                    user_time_percentile = int((slower_count / max(total_participants, 1)) * 100) if total_participants > 0 else 0

            # Get solution view tracking data
            solution_views = SolutionView.objects.filter(
                content_type=content_type,
                object_id=exam.id
            )

            # Count users who viewed solution before success
            users_viewed_before_success = 0
            for user in solution_views.values('user').distinct():
                user_id = user['user']
                user_view = solution_views.filter(user=user_id).first()
                user_completion = Complete.objects.filter(
                    user=user_id,
                    content_type=content_type,
                    object_id=exam.id,
                    status='success'
                ).first()

                # If user viewed solution and either didn't complete or viewed before completing
                if user_view and user_completion:
                    if user_view.viewed_at <= user_completion.created_at:
                        users_viewed_before_success += 1

            solution_views_before_success = users_viewed_before_success

            # Check if current user viewed solution
            user_viewed_solution = False
            # Check if user is authenticated
            is_user_authenticated = (hasattr(self.request, 'user') and self.request.user and self.request.user.is_authenticated)

            if is_user_authenticated:
                user_viewed_solution = solution_views.filter(user=request.user).exists()

            # Get solution match tracking data
            solution_matches = SolutionMatch.objects.filter(
                content_type=content_type,
                object_id=exam.id
            )

            solution_match_count = solution_matches.count()
            user_solution_matched = False

            if is_user_authenticated:
                user_solution_matched = solution_matches.filter(user=request.user).exists()

            return Response({
                'total_participants': total_participants,
                'success_count': success_count,
                'review_count': review_count,
                'success_percentage': success_percentage,
                'average_time_seconds': average_time_seconds,
                'best_time_seconds': best_time_seconds,
                'solution_views_before_success': solution_views_before_success,
                'user_time_percentile': user_time_percentile,
                'user_completed': user_completed,
                'user_viewed_solution': user_viewed_solution,
                'user_time_seconds': user_time_seconds,
                'solution_match_count': solution_match_count,
                'user_solution_matched': user_solution_matched
            })

        except Exception as e:
            logger.error(f"Error calculating statistics: {str(e)}")
            return Response(
                {'error': 'Failed to calculate statistics'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post', 'delete'], permission_classes=[IsAuthenticated])
    def mark_solution_viewed(self, request, pk=None):
        """
        Mark or unmark that the current user viewed the solution for this exam
        POST: Mark solution as viewed
        DELETE: Remove the solution view flag
        """
        exam = self.get_object()

        try:
            content_type = ContentType.objects.get_for_model(Exam)

            if request.method == 'POST':
                # Create or get the solution view record
                solution_view, created = SolutionView.objects.get_or_create(
                    user=request.user,
                    content_type=content_type,
                    object_id=exam.id
                )

                return Response({
                    'marked_as_viewed': True,
                    'message': 'Solution view recorded'
                })

            elif request.method == 'DELETE':
                # Delete the solution view record
                deleted_count, _ = SolutionView.objects.filter(
                    user=request.user,
                    content_type=content_type,
                    object_id=exam.id
                ).delete()

                if deleted_count > 0:
                    return Response({
                        'marked_as_viewed': False,
                        'message': 'Solution view flag removed'
                    })
                else:
                    return Response({
                        'marked_as_viewed': False,
                        'message': 'No solution view flag found'
                    })

        except Exception as e:
            logger.error(f"Error managing solution view: {str(e)}")
            return Response(
                {'error': 'Failed to manage solution view'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
