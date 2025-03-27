from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination


from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q


from .models import ClassLevel, Subject, Chapter, Exercise, Solution, Comment, Vote, Lesson,Theorem, Subfield
from .serializers import ClassLevelSerializer, SubjectSerializer, ChapterSerializer, ExerciseSerializer, SolutionSerializer, CommentSerializer, ExerciseCreateSerializer,LessonSerializer,TheoremSerializer, SubfieldSerializer


import logging


logger = logging.getLogger('django')




class IsAuthenticatedOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated
    

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


    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        logger.info(f"ClassLevel count: {queryset.count()}")
        logger.info(f"ClassLevel data: {list(queryset.values())}")
        serializer = self.get_serializer(queryset, many=True)
        logger.info(f"Serialized data: {serializer.data}")
        return Response(serializer.data)

class SubjectViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    pagination_class = StandardResultsSetPagination  # Ajouter cette ligne



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

    def get_queryset(self):
        queryset = Theorem.objects.all()
        subject_id = self.request.query_params.getlist('subject')
        class_level_id = self.request.query_params.getlist('class_level[]')
        subfield_id = self.request.query_params.getlist('subfields[]')
        chapter_id = self.request.query_params.getlist('chapters[]')


        logger.info(self.request)


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

        logger.info(queryset)
        return queryset
    
class ChapterViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Chapter.objects.all()
    serializer_class = ChapterSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = Chapter.objects.all()
        subject_id = self.request.query_params.getlist('subject[]')
        class_level_id = self.request.query_params.getlist('class_level[]')
        subfield_id = self.request.query_params.getlist('subfields[]')


        logger.info(f"voila {self.request.query_params}")


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
    @action(detail=True, methods=['post'])
    def vote(self, request, pk=None):
        obj = self.get_object()
        vote_value = request.data.get('value')

        if vote_value not in [Vote.UP, Vote.DOWN, Vote.UNVOTE]:
            return Response({'error': 'Invalid vote value'}, status=status.HTTP_400_BAD_REQUEST)

        vote, created = Vote.objects.get_or_create(
            user=request.user,
            content_type=ContentType.objects.get_for_model(obj),
            object_id=obj.id,
            defaults={'value': vote_value}
        )

        if not created:
            if vote_value == Vote.UNVOTE:
                vote.delete()
            elif vote.value != vote_value:
                vote.value = vote_value
                vote.save()

        return Response(self.get_serializer(obj).data)
    
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

        logger.info(self.request.query_params)
        
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
    def vote(self, request, pk=None):
        exercise = self.get_object()
        vote_value = request.data.get('value')

        logger.info(f"Vote request for Exercise ID {exercise.id} with vote value: {vote_value}")
        logger.info(f"Request data: {request.data}")

        if vote_value not in [Vote.UP, Vote.DOWN, Vote.UNVOTE]:
            logger.error(f"Invalid vote value: {vote_value} for Exercise ID {exercise.id}")
            return Response(
                {'error': 'Invalid vote value'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        vote, created = Vote.objects.get_or_create(
            user=request.user,
            content_type=ContentType.objects.get_for_model(exercise),
            object_id=exercise.id,
            defaults={'value': vote_value}
        )

        if not created:
            if vote_value == Vote.UNVOTE:
                vote.delete()
            elif vote.value != vote_value:
                vote.value = vote_value
                vote.save()
        # Refresh the exercise object to get updated vote count
        exercise.refresh_from_db()
        return Response(self.get_serializer(exercise).data)

    @action(detail=True, methods=['post'])
    def comment(self, request, pk=None):
        exercise = self.get_object()
        serializer = CommentSerializer(
            data=request.data,
            context={'request': request}
        )
        logger.info(f"Comment request for Exercise ID {exercise.id}")
        logger.info(f"Request data: {request.data}")
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
    def vote(self, request, pk=None):
        exercise = self.get_object()
        vote_value = request.data.get('value')

        logger.info(f"Vote request for Exercise ID {exercise.id} with vote value: {vote_value}")
        logger.info(f"Request data: {request.data}")

        if vote_value not in [Vote.UP, Vote.DOWN, Vote.UNVOTE]:
            logger.error(f"Invalid vote value: {vote_value} for Exercise ID {exercise.id}")
            return Response(
                {'error': 'Invalid vote value'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        vote, created = Vote.objects.get_or_create(
            user=request.user,
            content_type=ContentType.objects.get_for_model(exercise),
            object_id=exercise.id,
            defaults={'value': vote_value}
        )

        if not created:
            if vote_value == Vote.UNVOTE:
                vote.delete()
            elif vote.value != vote_value:
                vote.value = vote_value
                vote.save()
        # Refresh the exercise object to get updated vote count
        exercise.refresh_from_db()
        return Response(self.get_serializer(exercise).data)

    @action(detail=True, methods=['post'])
    def comment(self, request, pk=None):
        exercise = self.get_object()
        serializer = CommentSerializer(
            data=request.data,
            context={'request': request}
        )
        logger.info(f"Comment request for Exercise ID {exercise.id}")
        logger.info(f"Request data: {request.data}")
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