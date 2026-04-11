from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes as perm_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from datetime import timedelta
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache
import time

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q, F
from django.conf import settings

USE_TRIGRAM = 'postgresql' in settings.DATABASES['default']['ENGINE']
if USE_TRIGRAM:
    try:
        from django.contrib.postgres.search import TrigramSimilarity
    except ImportError:
        USE_TRIGRAM = False
        TrigramSimilarity = None
else:
    TrigramSimilarity = None

from .models import Content, Solution, Comment
from .content_store import get_structures_batch
from .serializers import ContentSerializer, ContentListSerializer, ContentCreateSerializer, SolutionSerializer, CommentSerializer
from apps.interactions.models import Vote, Save, Complete, TimeSession, SolutionView, SolutionMatch, QuestionProgress, AICorrection
from apps.interactions.serializers import VoteSerializer, SaveSerializer, CompleteSerializer, AICorrectionSerializer
from apps.interactions.views import VoteMixin
from apps.interactions.services import AIVisionService
from apps.users.models import ViewHistory
from rest_framework.permissions import IsAuthenticatedOrReadOnly, IsAuthenticated

import logging
logger = logging.getLogger('django')


# =====================
# PAGINATION
# =====================

class LargeResultsSetPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# =====================
# CONTENT VIEWSET
# =====================

class ContentViewSet(VoteMixin, viewsets.ModelViewSet):
    """
    Single ViewSet for all content types (exercise, lesson, exam).
    Filter by type: GET /api/contents/?type=exercise
    """
    queryset = Content.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = StandardResultsSetPagination

    # Subclasses set this to scope automatically
    content_type_scope = None

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ContentCreateSerializer
        if self.action == 'list':
            return ContentListSerializer
        return ContentSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        items = page if page is not None else queryset
        # batch fetch structures from Mongo
        type_scope = self.content_type_scope or request.query_params.get('type')
        if type_scope and items:
            display_ids = [i.display_id for i in items if i.display_id]
            structures = get_structures_batch(type_scope, display_ids)
        else:
            # mixed types — fetch per type
            from collections import defaultdict
            by_type = defaultdict(list)
            for i in items:
                if i.display_id:
                    by_type[i.type].append(i.display_id)
            structures = {}
            for t, ids in by_type.items():
                batch = get_structures_batch(t, ids)
                structures.update(batch)
        ctx = {**self.get_serializer_context(), 'mongo_structures': structures}
        serializer = self.get_serializer(items, many=True, context=ctx)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    def get_queryset(self):
        queryset = Content.objects.all().select_related(
            'author', 'solution', 'subject'
        ).prefetch_related(
            'chapters', 'class_levels', 'comments', 'votes', 'theorems', 'subfields', 'completed'
        ).annotate(
            vote_count_annotation=Count('votes', filter=Q(votes__value=Vote.UP)) -
                                  Count('votes', filter=Q(votes__value=Vote.DOWN))
        )

        # Type scope (from subclass or query param)
        type_scope = self.content_type_scope or self.request.query_params.get('type')
        if type_scope:
            queryset = queryset.filter(type=type_scope)

        # Search
        search_query = self.request.query_params.get('search')
        if search_query:
            if USE_TRIGRAM:
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
                queryset = queryset.filter(
                    Q(title__icontains=search_query) |
                    Q(content__icontains=search_query) |
                    Q(subject__name__icontains=search_query) |
                    Q(chapters__name__icontains=search_query) |
                    Q(theorems__name__icontains=search_query) |
                    Q(subfields__name__icontains=search_query) |
                    Q(class_levels__name__icontains=search_query)
                )

        # Filters
        class_levels = self.request.query_params.getlist('class_levels[]')
        subjects = self.request.query_params.getlist('subjects[]')
        chapters = self.request.query_params.getlist('chapters[]')
        difficulties = self.request.query_params.getlist('difficulties[]')
        subfields = self.request.query_params.getlist('subfields[]')
        theorems = self.request.query_params.getlist('theorems[]')

        show_viewed = self.request.query_params.get('showViewed', '').lower() == 'true'
        hide_viewed = self.request.query_params.get('hideViewed', '').lower() == 'true'
        show_completed = self.request.query_params.get('showCompleted', '').lower() == 'true'
        show_failed = self.request.query_params.get('showFailed', '').lower() == 'true'

        # Exam-specific filters
        is_national = self.request.query_params.get('is_national_exam')
        national_year = self.request.query_params.get('national_year')

        filters = Q()
        if class_levels:
            filters &= Q(class_levels__id__in=class_levels)
        if subjects:
            filters &= Q(subject__id__in=subjects)
        if subfields:
            filters &= Q(subfields__id__in=subfields)
        if theorems:
            filters &= Q(theorems__id__in=theorems)
        if chapters:
            filters &= Q(chapters__id__in=chapters)
        if difficulties:
            filters &= Q(difficulty__in=difficulties)
        if is_national is not None:
            filters &= Q(is_national_exam=is_national.lower() == 'true')
        if national_year:
            filters &= Q(national_year=national_year)

        if self.request.user and self.request.user.is_authenticated:
            content_ct = ContentType.objects.get_for_model(Content)
            status_filter = Q()
            if show_viewed:
                viewed_ids = ViewHistory.objects.filter(
                    user=self.request.user, content_type=content_ct
                ).values_list('object_id', flat=True)
                status_filter |= Q(id__in=viewed_ids)
            if show_completed:
                status_filter |= Q(completed__user=self.request.user, completed__status='success')
            if show_failed:
                status_filter |= Q(completed__user=self.request.user, completed__status='review')
            if status_filter:
                filters &= status_filter

        queryset = queryset.filter(filters)

        if hide_viewed and self.request.user and self.request.user.is_authenticated:
            content_ct = ContentType.objects.get_for_model(Content)
            viewed_ids = ViewHistory.objects.filter(
                user=self.request.user, content_type=content_ct
            ).values_list('object_id', flat=True)
            queryset = queryset.exclude(id__in=viewed_ids)

        sort_by = self.request.query_params.get('sort', 'newest')
        if sort_by == 'oldest':
            queryset = queryset.order_by('created_at')
        elif sort_by == 'most_upvoted':
            queryset = queryset.order_by('-vote_count_annotation', '-created_at')
        else:
            queryset = queryset.order_by('-created_at')

        return queryset.distinct()

    # ---- vote ----
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def vote(self, request, pk=None):
        return super().vote(request, pk)

    # ---- comment ----
    @action(detail=True, methods=['post'])
    def comment(self, request, pk=None):
        from apps.uploads.models import FileAttachment
        item = self.get_object()
        serializer = CommentSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            comment = serializer.save(
                content_item=item,
                author=request.user,
                parent_id=request.data.get('parent')
            )
            file_ids = request.data.get('file_ids', [])
            if file_ids:
                ct = ContentType.objects.get_for_model(comment)
                FileAttachment.objects.filter(id__in=file_ids).update(
                    content_type=ct, object_id=comment.id
                )
            return Response(
                CommentSerializer(comment, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ---- solution ----
    @action(detail=True, methods=['post'])
    def solution(self, request, pk=None):
        item = self.get_object()
        solution_text = request.data.get('content', '')
        sol, created = Solution.objects.get_or_create(
            content_item=item,
            defaults={'author': request.user, 'solution_text': solution_text}
        )
        if not created:
            sol.solution_text = solution_text
            sol.save()
        return Response(
            SolutionSerializer(sol, context={'request': request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    # ---- progress ----
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def mark_progress(self, request, pk=None):
        item = self.get_object()
        status_value = request.data.get('status')
        if status_value not in ['success', 'review']:
            return Response({'error': 'status must be "success" or "review"'}, status=status.HTTP_400_BAD_REQUEST)
        ct = ContentType.objects.get_for_model(Content)
        progress, _ = Complete.objects.update_or_create(
            user=request.user, content_type=ct, object_id=item.id,
            defaults={'status': status_value}
        )
        cache.delete(f'content_stats_{item.id}_user_{request.user.id}')
        cache.delete(f'content_stats_{item.id}_user_None')
        return Response({'id': progress.id, 'status': progress.status,
                         'created_at': progress.created_at, 'updated_at': progress.updated_at})

    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated])
    def remove_progress(self, request, pk=None):
        item = self.get_object()
        ct = ContentType.objects.get_for_model(Content)
        deleted, _ = Complete.objects.filter(
            user=request.user, content_type=ct, object_id=item.id
        ).delete()
        if deleted:
            cache.delete(f'content_stats_{item.id}_user_{request.user.id}')
            cache.delete(f'content_stats_{item.id}_user_None')
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response({'error': 'No progress record found'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def complete(self, request, pk=None):
        return self.mark_progress(request, pk)

    # ---- question progress ----
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def assess_question(self, request, pk=None):
        item = self.get_object()
        question_path = request.data.get('question_path')
        assessment_status = request.data.get('status')
        if not question_path:
            return Response({'error': 'question_path required'}, status=status.HTTP_400_BAD_REQUEST)
        if assessment_status not in ['success', 'partial', 'review', 'failed']:
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)
        ct = ContentType.objects.get_for_model(Content)
        progress, _ = QuestionProgress.objects.update_or_create(
            user=request.user, content_type=ct, object_id=item.id,
            question_path=question_path, defaults={'status': assessment_status}
        )
        return Response({'question_path': progress.question_path, 'status': progress.status,
                         'assessed_at': progress.assessed_at})

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def remove_assessment(self, request, pk=None):
        item = self.get_object()
        question_path = request.data.get('question_path')
        if not question_path:
            return Response({'error': 'question_path required'}, status=status.HTTP_400_BAD_REQUEST)
        ct = ContentType.objects.get_for_model(Content)
        deleted, _ = QuestionProgress.objects.filter(
            user=request.user, content_type=ct, object_id=item.id, question_path=question_path
        ).delete()
        return Response({'deleted': deleted > 0})

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def validate_solution(self, request, pk=None):
        item = self.get_object()
        question_path = request.data.get('question_path')
        validation = request.data.get('validation')
        if not question_path:
            return Response({'error': 'question_path required'}, status=status.HTTP_400_BAD_REQUEST)
        if validation and validation not in ['compatible', 'different', 'not-understood']:
            return Response({'error': 'Invalid validation'}, status=status.HTTP_400_BAD_REQUEST)
        ct = ContentType.objects.get_for_model(Content)
        progress, _ = QuestionProgress.objects.update_or_create(
            user=request.user, content_type=ct, object_id=item.id,
            question_path=question_path, defaults={'solution_validation': validation}
        )
        return Response({'question_path': progress.question_path,
                         'solution_validation': progress.solution_validation,
                         'assessed_at': progress.assessed_at})

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def question_progress(self, request, pk=None):
        item = self.get_object()
        ct = ContentType.objects.get_for_model(Content)
        records = QuestionProgress.objects.filter(
            user=request.user, content_type=ct, object_id=item.id
        )
        return Response({
            r.question_path: {
                'status': r.status,
                'solution_validation': r.solution_validation,
                'assessed_at': r.assessed_at
            }
            for r in records
        })

    # ---- similar ----
    @action(detail=True, methods=['get'])
    def similar(self, request, pk=None):
        item = self.get_object()
        chapters = item.chapters.all()
        if not chapters.exists():
            return Response({'results': [], 'count': 0})
        similar = Content.objects.filter(
            type=item.type, chapters__in=chapters
        ).exclude(id=item.id).distinct()[:10]
        serializer = ContentSerializer(similar, many=True, context={'request': request})
        return Response({'results': serializer.data, 'count': similar.count()})

    # ---- save / unsave ----
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save(self, request, pk=None):
        item = self.get_object()
        ct = ContentType.objects.get_for_model(Content)
        existing = Save.objects.filter(user=request.user, content_type=ct, object_id=item.id).first()
        if existing:
            return Response({'error': 'Already saved', 'already_saved': True},
                            status=status.HTTP_400_BAD_REQUEST)
        s = Save.objects.create(user=request.user, content_type=ct, object_id=item.id)
        return Response({'id': s.id, 'saved_at': s.saved_at}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post', 'delete'], permission_classes=[IsAuthenticated])
    def unsave(self, request, pk=None):
        item = self.get_object()
        ct = ContentType.objects.get_for_model(Content)
        deleted, _ = Save.objects.filter(
            user=request.user, content_type=ct, object_id=item.id
        ).delete()
        return Response({'saved': False, 'deleted': deleted > 0})

    # ---- view ----
    @action(detail=True, methods=['post'])
    def view(self, request, pk=None):
        item = self.get_object()
        should_count = True
        if request.user.is_authenticated:
            ct = ContentType.objects.get_for_model(Content)
            one_day_ago = timezone.now() - timedelta(days=1)
            try:
                already_viewed = ViewHistory.objects.filter(
                    user=request.user, content_type=ct,
                    object_id=item.id, viewed_at__gte=one_day_ago
                ).exists()
                if already_viewed:
                    should_count = False
                else:
                    Content.objects.filter(id=item.id).update(view_count=F('view_count') + 1)
                    item.refresh_from_db()
                ViewHistory.objects.update_or_create(
                    user=request.user, content_type=ct, object_id=item.id,
                    defaults={'status': 'viewed'}
                )
            except Exception as e:
                logger.error(f"Error recording view: {e}")
                should_count = False
        return Response({'view_count': item.view_count, 'counted': should_count})

    # ---- sessions ----
    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def session_stats(self, request, pk=None):
        item = self.get_object()
        ct = ContentType.objects.get_for_model(Content)
        sessions = TimeSession.objects.filter(
            user=request.user, content_type=ct, object_id=item.id
        ).order_by('-created_at')[:10]
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
                },
                'improvement_percentage': None
            }
            if len(durations) >= 2:
                prev = durations[1]
                if prev > 0:
                    stats['improvement_percentage'] = round(((prev - durations[0]) / prev) * 100, 1)
        else:
            stats = {'total_sessions': 0, 'best_time': None, 'worst_time': None,
                     'average_time': None, 'last_session': None, 'improvement_percentage': None}
        sessions_data = [{
            'id': s.id, 'duration_seconds': s.session_duration_in_seconds,
            'session_type': s.session_type, 'started_at': s.started_at,
            'ended_at': s.ended_at, 'notes': s.notes, 'created_at': s.created_at
        } for s in sessions]
        return Response({'sessions': sessions_data, 'stats': stats})

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save_session(self, request, pk=None):
        item = self.get_object()
        try:
            duration_seconds = int(request.data.get('duration_seconds', 0))
            if duration_seconds <= 0:
                return Response({'error': 'Duration must be > 0'}, status=status.HTTP_400_BAD_REQUEST)
        except (TypeError, ValueError):
            return Response({'error': 'Invalid duration'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ct = ContentType.objects.get_for_model(Content)
            session = TimeSession.objects.create(
                user=request.user, content_type=ct, object_id=item.id,
                session_duration=timedelta(seconds=duration_seconds),
                started_at=timezone.now() - timedelta(seconds=duration_seconds),
                ended_at=timezone.now(),
                session_type=request.data.get('session_type', 'practice'),
                notes=request.data.get('notes', '')
            )
            response_data = {
                'message': 'Session saved',
                'session': {'id': session.id, 'duration_seconds': session.session_duration_in_seconds,
                            'created_at': session.created_at}
            }
            previous = TimeSession.objects.filter(
                user=request.user, content_type=ct, object_id=item.id
            ).exclude(id=session.id).order_by('-created_at').first()
            if previous and previous.session_duration_in_seconds > 0:
                improvement = ((previous.session_duration_in_seconds - duration_seconds) /
                               previous.session_duration_in_seconds) * 100
                response_data['comparison'] = {
                    'previous_duration': previous.session_duration_in_seconds,
                    'difference': duration_seconds - previous.session_duration_in_seconds,
                    'improvement_percentage': round(improvement, 1)
                }
            return Response(response_data, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            return Response({'error': 'Failed to save session'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated],
            url_path='delete_session/(?P<session_id>[^/.]+)')
    def delete_session(self, request, pk=None, session_id=None):
        item = self.get_object()
        ct = ContentType.objects.get_for_model(Content)
        try:
            session = TimeSession.objects.get(
                id=session_id, user=request.user, content_type=ct, object_id=item.id
            )
            session.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except TimeSession.DoesNotExist:
            return Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def session_history(self, request, pk=None):
        item = self.get_object()
        try:
            ct = ContentType.objects.get_for_model(Content)
            sessions = TimeSession.objects.filter(
                user=request.user, content_type=ct, object_id=item.id
            ).order_by('-created_at')[:20]
            return Response({'sessions': [{
                'id': str(s.id),
                'session_duration': int(s.session_duration.total_seconds()),
                'started_at': s.started_at.isoformat(),
                'ended_at': s.ended_at.isoformat(),
                'created_at': s.created_at.isoformat(),
                'session_type': s.session_type,
                'notes': s.notes
            } for s in sessions]})
        except Exception as e:
            logger.error(f"Error retrieving session history: {e}")
            return Response({'error': 'Failed to retrieve session history'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ---- statistics ----
    def _get_successful_users_study_stats(self, item, ct):
        from apps.interactions.models import TaxonomyTimeSpent
        from apps.caracteristics.models import Chapter
        successful_users = Complete.objects.filter(
            content_type=ct, object_id=item.id, status='success'
        ).values_list('user', flat=True)
        if not successful_users:
            return {'exercises_avg_seconds': 0, 'lessons_avg_seconds': 0,
                    'exams_avg_seconds': 0, 'chapters': []}
        chapters = item.chapters.all()
        if not chapters:
            return {'exercises_avg_seconds': 0, 'lessons_avg_seconds': 0,
                    'exams_avg_seconds': 0, 'chapters': []}
        chapter_ct = ContentType.objects.get_for_model(Chapter)
        from datetime import timedelta as td
        total_ex = td(); total_le = td(); total_ex2 = td(); count = 0
        for user_id in successful_users:
            for chapter in chapters:
                ts = TaxonomyTimeSpent.objects.filter(
                    user_id=user_id, taxonomy_type='chapter',
                    content_type=chapter_ct, object_id=chapter.id
                ).first()
                if ts:
                    total_ex += ts.exercise_time
                    total_le += ts.lesson_time
                    total_ex2 += ts.exam_time
            count += 1
        if count > 0:
            return {
                'exercises_avg_seconds': int(total_ex.total_seconds() / count),
                'lessons_avg_seconds': int(total_le.total_seconds() / count),
                'exams_avg_seconds': int(total_ex2.total_seconds() / count),
                'chapters': [c.name for c in chapters]
            }
        return {'exercises_avg_seconds': 0, 'lessons_avg_seconds': 0,
                'exams_avg_seconds': 0, 'chapters': [c.name for c in chapters]}

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        item = self.get_object()
        user_id = request.user.id if (request.user and request.user.is_authenticated) else None
        cache_key = f'content_stats_{item.id}_user_{user_id}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)
        try:
            ct = ContentType.objects.get_for_model(Content)
            completions = Complete.objects.filter(content_type=ct, object_id=item.id)
            success_count = completions.filter(status='success').count()
            review_count = completions.filter(status='review').count()
            total_participants = completions.values('user').distinct().count()
            success_percentage = int(success_count / total_participants * 100) if total_participants > 0 else 0
            sessions = TimeSession.objects.filter(content_type=ct, object_id=item.id)
            if sessions.exists():
                total_secs = sum(int(s.session_duration.total_seconds()) for s in sessions)
                average_time_seconds = int(total_secs / sessions.count())
                best_time_seconds = min(int(s.session_duration.total_seconds()) for s in sessions)
            else:
                average_time_seconds = best_time_seconds = 0
            user_time_seconds = user_time_percentile = user_completed = None
            is_auth = request.user and request.user.is_authenticated
            if is_auth:
                uc = Complete.objects.filter(user=request.user, content_type=ct, object_id=item.id).first()
                user_completed = uc.status if uc else None
                user_session = sessions.filter(user=request.user).order_by('-created_at').first()
                if user_session:
                    user_time_seconds = int(user_session.session_duration.total_seconds())
                    slower = sessions.filter(
                        session_duration__gt=user_session.session_duration
                    ).values('user').distinct().count()
                    user_time_percentile = int(slower / max(total_participants, 1) * 100)
            solution_views = SolutionView.objects.filter(content_type=ct, object_id=item.id)
            users_viewed_before_success = 0
            for u in solution_views.values('user').distinct():
                uid = u['user']
                uv = solution_views.filter(user=uid).first()
                uc = Complete.objects.filter(user=uid, content_type=ct, object_id=item.id, status='success').first()
                if uv and uc and uv.viewed_at <= uc.created_at:
                    users_viewed_before_success += 1
            user_viewed_solution = is_auth and solution_views.filter(user=request.user).exists()
            solution_matches = SolutionMatch.objects.filter(content_type=ct, object_id=item.id)
            user_solution_matched = is_auth and solution_matches.filter(user=request.user).exists()
            study_stats = self._get_successful_users_study_stats(item, ct)
            data = {
                'total_participants': total_participants,
                'success_count': success_count,
                'review_count': review_count,
                'success_percentage': success_percentage,
                'average_time_seconds': average_time_seconds,
                'best_time_seconds': best_time_seconds,
                'solution_views_before_success': users_viewed_before_success,
                'solution_view_percentage': int(users_viewed_before_success / max(success_count, 1) * 100) if success_count else 0,
                'user_time_percentile': user_time_percentile,
                'user_completed': user_completed,
                'user_viewed_solution': user_viewed_solution,
                'user_time_seconds': user_time_seconds,
                'solution_match_count': solution_matches.count(),
                'user_solution_matched': user_solution_matched,
                'successful_users_study_stats': study_stats
            }
            cache.set(cache_key, data, 300)
            return Response(data)
        except Exception as e:
            logger.error(f"Error calculating statistics: {e}")
            return Response({'error': 'Failed to calculate statistics'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ---- solution view/match tracking ----
    @action(detail=True, methods=['post', 'delete'], permission_classes=[IsAuthenticated])
    def mark_solution_viewed(self, request, pk=None):
        item = self.get_object()
        ct = ContentType.objects.get_for_model(Content)
        try:
            if request.method == 'POST':
                SolutionView.objects.get_or_create(user=request.user, content_type=ct, object_id=item.id)
                cache.delete(f'content_stats_{item.id}_user_{request.user.id}')
                return Response({'marked_as_viewed': True})
            else:
                deleted, _ = SolutionView.objects.filter(
                    user=request.user, content_type=ct, object_id=item.id
                ).delete()
                cache.delete(f'content_stats_{item.id}_user_{request.user.id}')
                cache.delete(f'content_stats_{item.id}_user_None')
                return Response({'marked_as_viewed': False, 'deleted': deleted > 0})
        except Exception as e:
            logger.error(f"Error managing solution view: {e}")
            return Response({'error': 'Failed'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post', 'delete'], permission_classes=[IsAuthenticated])
    def mark_solution_match(self, request, pk=None):
        item = self.get_object()
        ct = ContentType.objects.get_for_model(Content)
        try:
            if request.method == 'POST':
                SolutionMatch.objects.get_or_create(user=request.user, content_type=ct, object_id=item.id)
                cache.delete(f'content_stats_{item.id}_user_{request.user.id}')
                return Response({'solution_matched': True})
            else:
                deleted, _ = SolutionMatch.objects.filter(
                    user=request.user, content_type=ct, object_id=item.id
                ).delete()
                return Response({'solution_matched': False, 'deleted': deleted > 0})
        except Exception as e:
            logger.error(f"Failed to manage solution match: {e}")
            return Response({'error': 'Failed'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ---- AI actions ----
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def ai_start_chat(self, request, pk=None):
        item = self.get_object()
        try:
            ct = ContentType.objects.get_for_model(Content)
            correction = AICorrection.objects.create(
                user=request.user, content_type=ct, object_id=item.id,
                conversation_started_at=timezone.now(),
                submission_state='pre_submission', language='fr'
            )
            solution_content = item.solution.solution_text if hasattr(item, 'solution') and item.solution else ''
            structure = item.structure or {}
            total_points = item.total_points if hasattr(item, 'total_points') else 20
            exercise_context = {'structure': structure, 'solution': solution_content, 'total_points': total_points}
            ai_service = AIVisionService()
            result = ai_service.start_conversation(exercise_context)
            correction.chat_history = [{'role': 'assistant', 'content': result['greeting_message'],
                                         'timestamp': int(time.time() * 1000)}]
            correction.save()
            return Response({
                'correction_id': str(correction.id),
                'greeting_message': result['greeting_message'],
                'exercise_info': {'total_points': total_points}
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Failed to start chat: {e}", exc_info=True)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def ai_chat_pedagogical(self, request, pk=None):
        item = self.get_object()
        correction_id = request.data.get('correction_id')
        user_message = request.data.get('message', '').strip()
        pedagogical_mode = request.data.get('mode', 'general')
        if not correction_id or not user_message:
            return Response({'error': 'correction_id and message required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ct = ContentType.objects.get_for_model(Content)
            correction = AICorrection.objects.get(
                id=correction_id, user=request.user, content_type=ct, object_id=item.id
            )
            solution_content = item.solution.solution_text if hasattr(item, 'solution') and item.solution else ''
            exercise_context = {
                'structure': item.structure or {},
                'solution': solution_content,
                'total_points': item.total_points if hasattr(item, 'total_points') else 20
            }
            ai_service = AIVisionService()
            result = ai_service.chat_pedagogical(
                user_message=user_message, chat_history=correction.chat_history,
                exercise_context=exercise_context, pedagogical_mode=pedagogical_mode,
                pedagogical_context=correction.pedagogical_context
            )
            if not result.get('response'):
                return Response({'error': 'Empty AI response'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            correction.chat_history = result['updated_history']
            correction.pedagogical_context = result['updated_context']
            correction.submission_state = 'discussed'
            correction.save()
            return Response({'response': result['response'], 'chat_history': correction.chat_history,
                             'pedagogical_context': correction.pedagogical_context})
        except AICorrection.DoesNotExist:
            return Response({'error': 'Correction not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Pedagogical chat failed: {e}", exc_info=True)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def ai_correct(self, request, pk=None):
        item = self.get_object()
        if 'image' not in request.FILES:
            return Response({'error': 'No image provided'}, status=status.HTTP_400_BAD_REQUEST)
        image_file = request.FILES['image']
        if image_file.size > 10 * 1024 * 1024:
            return Response({'error': 'Image too large (max 10MB)'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ct = ContentType.objects.get_for_model(Content)
            correction_id = request.data.get('correction_id')
            if correction_id:
                try:
                    correction = AICorrection.objects.get(
                        id=correction_id, user=request.user, content_type=ct, object_id=item.id
                    )
                    correction.image = image_file
                    correction.submission_state = 'submitted'
                    correction.save()
                except AICorrection.DoesNotExist:
                    correction = AICorrection.objects.create(
                        user=request.user, content_type=ct, object_id=item.id,
                        image=image_file, submission_state='submitted', language='fr'
                    )
            else:
                correction = AICorrection.objects.create(
                    user=request.user, content_type=ct, object_id=item.id,
                    image=image_file, submission_state='submitted', language='fr'
                )
            solution_content = item.solution.solution_text if hasattr(item, 'solution') and item.solution else ''
            structure = item.structure or {}
            total_points = item.total_points if hasattr(item, 'total_points') else 20
            try:
                ai_service = AIVisionService()
                result = ai_service.analyze_solution(
                    image_path=correction.image.path, marked_solution=solution_content,
                    structure=structure, total_points=total_points
                )
                correction.score_awarded = result['score_awarded']
                correction.score_total = result['score_total']
                correction.feedback = result['feedback']
                correction.raw_response = result['raw_response']
                correction.processing_time_ms = result['processing_time_ms']
                correction.save()
                serializer = AICorrectionSerializer(correction, context={'request': request})
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            except Exception as e:
                logger.error(f"AI correction failed: {e}", exc_info=True)
                correction.delete()
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.error(f"Error creating AI correction: {e}", exc_info=True)
            return Response({'error': 'Failed to process correction'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def ai_chat(self, request, pk=None):
        item = self.get_object()
        correction_id = request.data.get('correction_id')
        message = request.data.get('message')
        if not correction_id or not message:
            return Response({'error': 'correction_id and message required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ct = ContentType.objects.get_for_model(Content)
            correction = AICorrection.objects.get(
                id=correction_id, user=request.user, content_type=ct, object_id=item.id
            )
            ai_service = AIVisionService()
            result = ai_service.chat_followup(
                user_message=message, chat_history=correction.chat_history,
                original_feedback=correction.feedback
            )
            correction.chat_history = result['updated_history']
            correction.save()
            return Response({'response': result['response'], 'chat_history': correction.chat_history})
        except AICorrection.DoesNotExist:
            return Response({'error': 'Correction not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"AI chat failed: {e}", exc_info=True)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def ai_corrections(self, request, pk=None):
        item = self.get_object()
        ct = ContentType.objects.get_for_model(Content)
        corrections = AICorrection.objects.filter(
            user=request.user, content_type=ct, object_id=item.id
        ).order_by('-submitted_at')[:10]
        serializer = AICorrectionSerializer(corrections, many=True, context={'request': request})
        return Response(serializer.data)


# =====================
# SOLUTION VIEWSET
# =====================

class SolutionViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Solution.objects.all()
    serializer_class = SolutionSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


# =====================
# COMMENT VIEWSET
# =====================

class CommentViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def _taxonomy_qs(source, exclude_id=None):
    qs = Content.objects.filter(
        Q(chapters__in=source.chapters.all()) |
        Q(theorems__in=source.theorems.all()) |
        Q(subfields__in=source.subfields.all()) |
        Q(subject=source.subject)
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return qs.distinct().annotate(
        relevance=Count('chapters') + Count('theorems') + Count('subfields')
    ).order_by('-relevance', '-view_count')


@api_view(['GET'])
def get_content_recommendations(request, content_id):
    try:
        source = Content.objects.get(id=content_id)
    except Content.DoesNotExist:
        return Response({'error': 'Not found'}, status=404)

    qs = _taxonomy_qs(source, exclude_id=content_id)
    ctx = {'request': request}
    return Response({
        'exercises': ContentListSerializer(qs.filter(type='exercise')[:3], many=True, context=ctx).data,
        'lessons': ContentListSerializer(qs.filter(type='lesson')[:2], many=True, context=ctx).data,
        'exams': ContentListSerializer(qs.filter(type='exam')[:2], many=True, context=ctx).data,
    })
