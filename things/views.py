from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
import rest_framework
from datetime import timedelta
from django.shortcuts import get_object_or_404
from django.utils import timezone


from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q


from .models import Exercise, Solution, Comment, Lesson
from .serializers import  ExerciseSerializer, SolutionSerializer, CommentSerializer, ExerciseCreateSerializer, LessonSerializer, LessonCreateSerializer
from interactions.models import Vote, Save, Complete, TimeSpent
from interactions.serializers import VoteSerializer, SaveSerializer, CompleteSerializer, TimeSpentSerializer
from interactions.views import VoteMixin
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
        
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def update_session_time(self, request, pk=None):
        """
        Update current session time
        """
        exercise = self.get_object()
        time_seconds = request.data.get('time_seconds', 0)
        
        try:
            time_seconds = int(time_seconds)
            if time_seconds < 0:
                raise ValueError("Time cannot be negative")
        except (TypeError, ValueError):
            return Response(
                {'error': 'Invalid time_seconds value'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            content_type = ContentType.objects.get_for_model(Exercise)
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
        
        try:
            content_type = ContentType.objects.get_for_model(Exercise)
            time_spent = TimeSpent.objects.get(
                user=request.user,
                content_type=content_type,
                object_id=exercise.id
            )
            
            if time_spent.save_and_reset_session():
                return Response({
                    'message': 'Session saved successfully',
                    'total_time_seconds': time_spent.total_time
                })
            else:
                return Response({
                    'message': 'No session time to save',
                    'total_time_seconds': time_spent.total_time
                })
            
        except TimeSpent.DoesNotExist:
            return Response(
                {'error': 'No time tracking found for this exercise'},
                status=status.HTTP_404_NOT_FOUND
            )

                    
    
    
#----------------------------SOLUTION-------------------------------
class SolutionViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Solution.objects.all()
    serializer_class = SolutionSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = []  # Skip authentication


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
        Mark exam as viewed and increment view count
        """
        exam = self.get_object()
        exam.view_count += 1
        exam.save()
        
        # Optionally, you can track user view history here
        # This would require creating a ViewHistory record
        
        return Response({'view_count': exam.view_count})

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
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def update_session_time(self, request, pk=None):
        """
        Update current session time
        """
        exam = self.get_object()
        time_seconds = request.data.get('time_seconds', 0)
        
        try:
            time_seconds = int(time_seconds)
            if time_seconds < 0:
                raise ValueError("Time cannot be negative")
        except (TypeError, ValueError):
            return Response(
                {'error': 'Invalid time_seconds value'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            content_type = ContentType.objects.get_for_model(Exam)
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
        
        try:
            content_type = ContentType.objects.get_for_model(Exam)
            time_spent = TimeSpent.objects.get(
                user=request.user,
                content_type=content_type,
                object_id=exam.id
            )
            
            if time_spent.save_and_reset_session():
                return Response({
                    'message': 'Session saved successfully',
                    'total_time_seconds': time_spent.total_time,
                })
            else:
                return Response({
                    'message': 'No session time to save',
                    'total_time_seconds': time_spent.total_time
                })
            
        except TimeSpent.DoesNotExist:
            return Response(
                {'error': 'No time tracking found for this exercise'},
                status=status.HTTP_404_NOT_FOUND
            )