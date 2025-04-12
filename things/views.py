from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination


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
    def time_spent(self, request, pk=None):
        """
        Record time spent on an exercise
        """
        exercise = self.get_object()
        time_spent = request.data.get('time_spent', 0)
        content_type = ContentType.objects.get_for_model(Exercise)
        try:
            time_spent = TimeSpent.objects.create(
                user=request.user,
                content_type=content_type,
                object_id=exercise.id,
                time_spent_in_seconds=time_spent
            )
            logger.debug(f"Time spent on exercise {exercise.id} recorded for user {request.user.id}")
            return Response(TimeSpentSerializer(time_spent).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error recording time spent: {str(e)}")
            return Response(
                {'error': 'Failed to record time spent', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated])
    def delete_time_spent(self, request, pk=None):
        """
        Delete time spent record for an exercise
        """
        exercise = self.get_object()
        content_type = ContentType.objects.get_for_model(Exercise)
        
        try:
            time_spent = TimeSpent.objects.get(
                user=request.user,
                content_type=content_type,
                object_id=exercise.id
            )
            time_spent.delete()
            logger.debug(f"Time spent record deleted for exercise {exercise.id} by user {request.user.id}")
            return Response(status=status.HTTP_204_NO_CONTENT)
        except TimeSpent.DoesNotExist:
            return Response(
                {'error': 'Time spent record not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
                    
    
    
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