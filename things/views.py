from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination


from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q


from .models import ClassLevel, Subject, Chapter, Exercise, Solution, Comment, Vote, Lesson,Theorem, Subfield,Save,Complete
from .serializers import ClassLevelSerializer, SubjectSerializer, ChapterSerializer, ExerciseSerializer, SolutionSerializer, CommentSerializer, ExerciseCreateSerializer,LessonSerializer,TheoremSerializer, SubfieldSerializer
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.permissions import IsAuthenticated

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
    

#----------------------------CLASS LEVEL/ SUBJECT/ CHAPTER-------------------------------

class ClassLevelViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ClassLevel.objects.all()
    serializer_class = ClassLevelSerializer
    pagination_class = StandardResultsSetPagination  # Ajouter cette ligne
    permission_classes = [permissions.AllowAny]


    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class SubjectViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    pagination_class = StandardResultsSetPagination  # Ajouter cette ligne
    permission_classes = [permissions.AllowAny]




    def get_queryset(self):
        queryset = Subject.objects.all()
        class_level_id = self.request.query_params.getlist('class_level[]')

        filters = Q()
        if class_level_id or class_level_id != '':
            filters |= Q(class_levels__id__in=class_level_id)
        queryset = queryset.filter(filters)

        return queryset
    
class SubfieldViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubfieldSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]



    def get_queryset(self):
        queryset = Subfield.objects.all()
        class_level_id = self.request.query_params.getlist('class_level[]')
        subject_id = self.request.query_params.getlist('subject')

        subject_ids = [int(id) for id in subject_id if id.isdigit()]
        class_level_ids = [int(id) for id in class_level_id if id.isdigit()]

        filters_class = Q()
        filters_subject = Q()
        if class_level_ids:
            filters_class |= Q(class_levels__id__in=class_level_id)
        if subject_ids:
            filters_subject |= Q(subject__id__in = subject_id)
        filters = (filters_subject) & (filters_class)

        
        queryset = queryset.filter(filters)

        return queryset


class TheoremViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Theorem.objects.all()
    serializer_class = TheoremSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]


    def get_queryset(self):
        queryset = Theorem.objects.all()
        subject_id = self.request.query_params.getlist('subject')
        class_level_id = self.request.query_params.getlist('class_level[]')
        subfield_id = self.request.query_params.getlist('subfields[]')
        chapter_id = self.request.query_params.getlist('chapters[]')


        # Filter out empty strings and convert to integers
        subject_ids = [int(id) for id in subject_id if id.isdigit()]
        class_level_ids = [int(id) for id in class_level_id if id.isdigit()]
        subfield_ids = [int(id) for id in subfield_id if id.isdigit()]
        chapter_ids = [int(id) for id in chapter_id if id.isdigit()]


        filters_subject = Q()
        filters_class_level = Q()
        filters_subfield = Q()
        filters_chapter = Q()


        if subject_ids:
            filters_subject |= Q(subject__id__in=subject_ids)
        if class_level_ids:
            filters_class_level |= Q(class_levels__id__in=class_level_ids)
        if subfield_ids:
            filters_subfield |= Q(subfield__id__in=subfield_ids)
        if chapter_ids:
            filters_chapter |= Q(chapters__id__in=chapter_ids)
            

        filters = (filters_subject) & (filters_class_level) & (filters_subfield) & (filters_chapter)
        queryset = queryset.filter(filters)

        return queryset
    
class ChapterViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Chapter.objects.all()
    serializer_class = ChapterSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]


    def get_queryset(self):
        queryset = Chapter.objects.all()
        subject_id = self.request.query_params.getlist('subject[]')
        class_level_id = self.request.query_params.getlist('class_level[]')
        subfield_id = self.request.query_params.getlist('subfields[]')




        # Filter out empty strings and convert to integers
        subject_ids = [int(id) for id in subject_id if id.isdigit()]
        class_level_ids = [int(id) for id in class_level_id if id.isdigit()]
        subfield_ids = [int(id) for id in subfield_id if id.isdigit()]

        filters_subject = Q()
        filters_class_level = Q()
        filters_subfield = Q()

        if subject_ids:
            filters_subject |= Q(subject__id__in=subject_ids)
        if class_level_ids:
            filters_class_level |= Q(class_levels__id__in=class_level_ids)
        if subfield_ids:
            filters_subfield |= Q(subfield__id__in=subfield_ids)
            

        filters = (filters_subject) & (filters_class_level) & (filters_subfield)
        queryset = queryset.filter(filters)

        return queryset


#----------------------------VOTEMIXIN-------------------------------

class VoteMixin:
    """
    Mixin that provides vote functionality with toggle behavior
    """
    
    @action(detail=True, methods=['post'])
    def vote(self, request, pk=None):
        obj = self.get_object()
        vote_value = request.data.get('value')
        
        logger.debug(f"Vote request for {obj.__class__.__name__} ID {obj.id} with vote value: {vote_value}")
        
        try:
            vote_value = int(vote_value)
        except (TypeError, ValueError):
            logger.error(f"Invalid vote value type: {vote_value} for {obj.__class__.__name__} ID {obj.id}")
            return Response({'error': 'Invalid vote value'}, status=status.HTTP_400_BAD_REQUEST)

        if vote_value not in [Vote.UP, Vote.DOWN]:
            logger.error(f"Invalid vote value: {vote_value} for {obj.__class__.__name__} ID {obj.id}")
            return Response({'error': 'Invalid vote value'}, status=status.HTTP_400_BAD_REQUEST)

        existing_vote = obj.votes.filter(user=request.user).first()
        
        if existing_vote:
            # If clicking the same vote type, delete the vote
            if existing_vote.value == vote_value:
                existing_vote.delete()
                current_vote = None
            else:
                # If changing vote type (up to down or down to up)
                existing_vote.value = vote_value
                existing_vote.save()
                current_vote = existing_vote
        else:
            # Create new vote
            current_vote = obj.votes.create(user=request.user, value=vote_value)
            
        # Refresh the object to get updated vote count
        obj.refresh_from_db()
        
        return Response({
            'vote_count': obj.vote_count,
            'user_vote': current_vote.value if current_vote else 0,  # Return 0 if vote was deleted
            'item': self.get_serializer(obj).data
        })
    
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
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save_exercise(self, request, pk=None):
        """
        Save an exercise for later
        """
        exercise = self.get_object()
        content_type = ContentType.objects.get_for_model(Exercise)
        
        # Check if already saved
        existing = Save.objects.filter(
            user=request.user,
            content_type=content_type,
            object_id=exercise.id
        ).first()
        
        if existing:
            return Response(
                {'error': 'Exercise already saved'}, 
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
            'saved_at': save.saved_at
        }, status=status.HTTP_201_CREATED)
    
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
    def user_status(self, request, pk=None):
        """
        Get user's status for an exercise (progress and saved status)
        """
        exercise = self.get_object()
        content_type = ContentType.objects.get_for_model(Exercise)
        
        # Check progress status
        progress = Complete.objects.filter(
            user=request.user,
            content_type=content_type,
            object_id=exercise.id
        ).first()
        
        # Check if saved
        saved = Save.objects.filter(
            user=request.user,
            content_type=content_type,
            object_id=exercise.id
        ).exists()
        
        return Response({
            'progress': {
                'status': progress.status if progress else None,
                'created_at': progress.created_at if progress else None,
                'updated_at': progress.updated_at if progress else None
            },
            'saved': saved
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

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


#----------------------------LESSON-------------------------------

class LessonViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Lesson.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_serializer_class(self):

        return LessonSerializer

    def get_queryset(self):
        queryset = Exercise.objects.all().select_related(
            'author', 'solution', 'subject'
        ).prefetch_related(
            'chapters',
            'class_levels',
            'comments',
            'votes'
        ).annotate(
            vote_count_annotation=Count('votes', filter=Q(votes__value=Vote.UP)) - 
                                  Count('votes', filter=Q(votes__value=Vote.DOWN))
        )
        

        # Filtering
        class_levels = self.request.query_params.getlist('class_levels[]')
        subjects = self.request.query_params.getlist('subjects[]')
        chapters = self.request.query_params.getlist('chapters[]')

        if class_levels:
            queryset = queryset.filter(class_levels__id__in=class_levels)
        if subjects:
            queryset = queryset.filter(subject__id__in=subjects)
        if chapters:
            queryset = queryset.filter(chapters__id__in=chapters)

        # Sorting
        sort_by = self.request.query_params.get('sort', '-created_at')
        if sort_by == 'votes':
            queryset = queryset.order_by('-vote_count_annotation')
        else:
            queryset = queryset.order_by(sort_by)

        return queryset.distinct()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data)
        print(serializer.is_valid(raise_exception=True))
        self.perform_update(serializer)
        return Response(serializer.data)

    def perform_create(self, serializer):
        if not self.request.user.is_authenticated:
            logger.warning("Unauthorized attempt to create an exercise.")

            raise PermissionDenied("You must be logged in to create an exercise.")
        serializer.save()

    def perform_update(self, serializer):
        if not self.request.user.is_authenticated:
            logger.warning("Unauthorized attempt to update an exercise.")

            raise PermissionDenied("You must be logged in to create an exercise.")
        serializer.save()


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