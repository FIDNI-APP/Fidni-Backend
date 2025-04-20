from rest_framework import viewsets, permissions
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination


from django.db.models import Q


from .models import ClassLevel, Subject, Chapter,Theorem, Subfield
from .serializers import ClassLevelSerializer, SubjectSerializer, ChapterSerializer, TheoremSerializer, SubfieldSerializer

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
    authentication_classes = []  # Skip authentication



    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class SubjectViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    pagination_class = StandardResultsSetPagination  # Ajouter cette ligne
    authentication_classes = []  # Skip authentication



    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


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
    authentication_classes = []  # Skip authentication




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
    authentication_classes = []  # Skip authentication


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
    authentication_classes = []  # Skip authentication


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

