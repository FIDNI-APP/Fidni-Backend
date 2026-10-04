from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes as perm_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination


from django.db.models import Q, Count


from .models import ClassLevel, Subject, Chapter,Theorem, Subfield, School, school_search_key
from .serializers import (
    ClassLevelSerializer, SubjectSerializer, ChapterSerializer,
    TheoremSerializer, SubfieldSerializer, ClassLevelWithTaxonomySerializer
)

import logging


logger = logging.getLogger('django')



CONTENT_TYPE_RELATED = {
    'exercise': 'content_items',
    'exam': 'content_items',
    'lesson': 'content_items',
}


#----------------------------PAGINATION-------------------------------


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 1000
    page_size_query_param = 'page_size'
    max_page_size = 1000


#----------------------------CLASS LEVEL/ SUBJECT/ CHAPTER-------------------------------

class ClassLevelViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ClassLevel.objects.all()
    serializer_class = ClassLevelSerializer
    pagination_class = StandardResultsSetPagination
    authentication_classes = []

    def get_serializer_class(self):
        # Use full taxonomy serializer when include_taxonomy=true
        if self.request.query_params.get('include_taxonomy') == 'true':
            return ClassLevelWithTaxonomySerializer
        return ClassLevelSerializer

    def get_queryset(self):
        queryset = ClassLevel.objects.all()
        content_type_param = self.request.query_params.get('content_type', '')
        related = CONTENT_TYPE_RELATED.get(content_type_param)
        if related:
            queryset = queryset.annotate(content_count=Count(
                related, filter=Q(**{f'{related}__type': content_type_param}), distinct=True
            ))
        # Ordre du programme (TC → 1ère → 2ème) : annotate() fait perdre le Meta.ordering (GROUP BY).
        return queryset.order_by("order")

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset().prefetch_related('subjects', 'subjects__chapters')
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class SubjectViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    pagination_class = StandardResultsSetPagination
    authentication_classes = []



    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


    def get_queryset(self):
        queryset = Subject.objects.prefetch_related('class_levels')
        class_level_id = self.request.query_params.getlist('class_level[]')

        filters = Q()
        if class_level_id and any(class_level_id):
            filters |= Q(class_levels__id__in=class_level_id)
            queryset = queryset.filter(filters)

        content_type_param = self.request.query_params.get('content_type', '')
        related = CONTENT_TYPE_RELATED.get(content_type_param)
        if related:
            count_filter = Q(**{f'{related}__type': content_type_param})
            if class_level_id and any(class_level_id):
                count_filter &= Q(**{f'{related}__class_levels__id__in': class_level_id})
            queryset = queryset.annotate(content_count=Count(related, filter=count_filter, distinct=True))

        return queryset

class SubfieldViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Subfield.objects.all()
    serializer_class = SubfieldSerializer
    pagination_class = StandardResultsSetPagination
    authentication_classes = []

    def get_queryset(self):
        queryset = Subfield.objects.select_related('subject').prefetch_related('class_levels', 'subject__class_levels')
        class_level_id = self.request.query_params.getlist('class_level[]')
        subject_id = self.request.query_params.getlist('subject')

        subject_ids = [int(id) for id in subject_id if id.isdigit()]
        class_level_ids = [int(id) for id in class_level_id if id.isdigit()]

        filters_class = Q()
        filters_subject = Q()
        if class_level_ids:
            filters_class |= Q(class_levels__id__in=class_level_id)
        if subject_ids:
            filters_subject |= Q(subject__id__in=subject_id)
        filters = (filters_subject) & (filters_class)

        queryset = queryset.filter(filters)

        content_type_param = self.request.query_params.get('content_type', '')
        related = CONTENT_TYPE_RELATED.get(content_type_param)
        if related:
            count_filter = Q(**{f'{related}__type': content_type_param})
            if class_level_ids:
                count_filter &= Q(**{f'{related}__class_levels__id__in': class_level_ids})
            if subject_ids:
                count_filter &= Q(**{f'{related}__subject__id__in': subject_ids})
            queryset = queryset.annotate(content_count=Count(related, filter=count_filter, distinct=True))

        return queryset


class TheoremViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Theorem.objects.all()
    serializer_class = TheoremSerializer
    pagination_class = StandardResultsSetPagination
    authentication_classes = []


    def get_queryset(self):
        queryset = Theorem.objects.select_related('subject', 'subfield__subject').prefetch_related(
            'chapters', 'class_levels', 'subject__class_levels', 'subfield__class_levels', 'subfield__subject__class_levels')
        subject_id = self.request.query_params.getlist('subject')
        class_level_id = self.request.query_params.getlist('class_level[]')
        subfield_id = self.request.query_params.getlist('subfields[]')
        chapter_id = self.request.query_params.getlist('chapters[]')

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

        content_type_param = self.request.query_params.get('content_type', '')
        related = CONTENT_TYPE_RELATED.get(content_type_param)
        if related:
            count_filter = Q(**{f'{related}__type': content_type_param})
            if class_level_ids:
                count_filter &= Q(**{f'{related}__class_levels__id__in': class_level_ids})
            if subject_ids:
                count_filter &= Q(**{f'{related}__subject__id__in': subject_ids})
            if subfield_ids:
                count_filter &= Q(**{f'{related}__subfields__id__in': subfield_ids})
            if chapter_ids:
                count_filter &= Q(**{f'{related}__chapters__id__in': chapter_ids})
            queryset = queryset.annotate(content_count=Count(related, filter=count_filter, distinct=True))

        return queryset

class ChapterViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Chapter.objects.all()
    serializer_class = ChapterSerializer
    pagination_class = StandardResultsSetPagination
    authentication_classes = []


    def get_queryset(self):
        # Relations chargées en lot : sans ça, chaque chapitre coûtait ~7 requêtes (N+1),
        # soit ~1,8 s pour la liste avec la base sur AWS.
        queryset = Chapter.objects.select_related('subject', 'subfield__subject').prefetch_related(
            'class_levels', 'subject__class_levels', 'subfield__class_levels', 'subfield__subject__class_levels')
        subject_id = self.request.query_params.getlist('subject[]')
        class_level_id = self.request.query_params.getlist('class_level[]')
        subfield_id = self.request.query_params.getlist('subfields[]')

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

        content_type_param = self.request.query_params.get('content_type', '')
        related = CONTENT_TYPE_RELATED.get(content_type_param)
        if related:
            count_filter = Q(**{f'{related}__type': content_type_param})
            if class_level_ids:
                count_filter &= Q(**{f'{related}__class_levels__id__in': class_level_ids})
            if subject_ids:
                count_filter &= Q(**{f'{related}__subject__id__in': subject_ids})
            if subfield_ids:
                count_filter &= Q(**{f'{related}__subfields__id__in': subfield_ids})
            queryset = queryset.annotate(content_count=Count(related, filter=count_filter, distinct=True))

        return queryset


#----------------------------DIFFICULTY COUNTS-------------------------------

@api_view(['GET'])
@perm_classes([AllowAny])
def difficulty_counts(request):
    """Return count of content per difficulty, filtered by current taxonomy selections."""
    from apps.things.models import Content

    content_type = request.query_params.get('content_type', 'exercise')
    qs = Content.objects.filter(type=content_type)

    class_level_ids = request.query_params.getlist('class_levels[]')
    subject_ids = request.query_params.getlist('subjects[]')
    subfield_ids = request.query_params.getlist('subfields[]')
    chapter_ids = request.query_params.getlist('chapters[]')
    theorem_ids = request.query_params.getlist('theorems[]')

    if class_level_ids:
        qs = qs.filter(class_levels__id__in=class_level_ids)
    if subject_ids:
        qs = qs.filter(subject__id__in=subject_ids)
    if subfield_ids:
        qs = qs.filter(subfields__id__in=subfield_ids)
    if chapter_ids:
        qs = qs.filter(chapters__id__in=chapter_ids)
    if theorem_ids:
        qs = qs.filter(theorems__id__in=theorem_ids)

    counts = qs.values('difficulty').annotate(count=Count('id', distinct=True))
    result = {item['difficulty']: item['count'] for item in counts if item['difficulty']}
    return Response(result)


#----------------------------SCHOOLS-------------------------------

_KIND_RANK = {'lycee': 0, 'cpge': 1, 'college': 2, 'prive': 3}
_KIND_LABEL = dict(School.KIND_CHOICES)


@api_view(['GET'])
@perm_classes([AllowAny])
def school_search(request):
    """Autocomplétion des établissements : ?q=moutanabi agadir → 12 résultats au plus.

    Chaque mot doit apparaître dans le nom (français ou arabe) ou la ville ; les noms qui
    commencent par la recherche passent devant, puis les lycées, CPGE, collèges, privés.
    """
    query = school_search_key(request.query_params.get('q', ''))[:80]
    tokens = [t for t in query.split() if t][:6]
    if len(query) < 2 or not tokens:
        return Response([])
    qs = School.objects.all()
    for token in tokens:
        qs = qs.filter(search__contains=token)
    candidates = list(qs.only('id', 'name', 'name_ar', 'city', 'region', 'kind', 'search')[:300])
    candidates.sort(key=lambda s: (
        not s.search.startswith(query),
        _KIND_RANK.get(s.kind, 9),
        s.name,
    ))
    return Response([
        {'id': s.id, 'name': s.name, 'name_ar': s.name_ar, 'city': s.city, 'region': s.region,
         'kind': s.kind, 'kind_label': _KIND_LABEL.get(s.kind, '')}
        for s in candidates[:12]
    ])
