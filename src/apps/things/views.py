from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes as perm_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from datetime import timedelta
from django.utils import timezone
from django.core.cache import cache
from django.contrib.auth.models import User

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, F

from django.db.models import Case, IntegerField, TextField, When
from django.db.models.functions import Cast

from .models import Content, ContentDailyView, Solution, Comment, ProposedSolution
from .pdf_parser import parse_pdf
from .serializers import ContentSerializer, ContentListSerializer, ContentCreateSerializer, SolutionSerializer, CommentSerializer, ProposedSolutionSerializer
from . import for_you
from .listing import in_order, serialize_content_list, with_list_relations
from apps.interactions.models import Save, Complete, TimeSession, SolutionView, SolutionMatch, QuestionProgress, AICorrection
from apps.interactions.serializers import AICorrectionSerializer
from apps.interactions.views import VoteMixin
from apps.users.models import ViewHistory
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from config.permissions import IsAuthorOrStaffOrReadOnly
from config.throttling import PdfParseThrottle, ProposedSolutionThrottle

import hashlib
import logging
import re
logger = logging.getLogger('django')

# Robots (moteurs de recherche, aperçus de liens, navigateurs automatisés) : leurs passages ne sont pas des vues.
BOT_UA = re.compile(r'bot|crawl|spider|slurp|headless|lighthouse|preview|facebookexternalhit|whatsapp|python-requests|curl|wget', re.I)


def _count_daily_view(content_id):
    """+1 sur la ligne du jour (créée à la première vue ; deux créations simultanées → une seule ligne)."""
    day = timezone.localdate()
    if ContentDailyView.objects.filter(content_id=content_id, date=day).update(count=F('count') + 1):
        return
    try:
        with transaction.atomic():
            ContentDailyView.objects.create(content_id=content_id, date=day, count=1)
    except IntegrityError:
        ContentDailyView.objects.filter(content_id=content_id, date=day).update(count=F('count') + 1)


def _forget_stats(content_id, user_id):
    """Onglet « Activité » : les statistiques sont en cache 5 min ; une auto-évaluation doit s'y voir tout de suite."""
    cache.delete(f'content_stats_{content_id}_user_{user_id}')
    cache.delete(f'content_stats_{content_id}_user_None')


def _walk_questions_meta(structure):
    """Yield (path, label, meta) pour chaque question/sous-question.

    `path` est aligné sur QuestionProgress.question_path tel que produit par le
    renderer front : l'id du bloc, et `<block_id>.<sub_id>` pour les sous-questions.
    `label` est lisible (Q1, Q2a…). `meta` = block.meta (schéma v2.1), {} si absent.
    """
    qnum = 0
    for block in (structure or {}).get('blocks', []):
        if block.get('type') != 'question':
            continue
        qnum += 1
        bid = block.get('id')
        subs = block.get('subQuestions') or []
        if subs:
            for i, sub in enumerate(subs):
                yield (f"{bid}.{sub.get('id')}", f"Q{qnum}{chr(ord('a') + i)}", sub.get('meta') or {})
        else:
            yield (str(bid), f"Q{qnum}", block.get('meta') or {})


@api_view(['GET'])
@perm_classes([AllowAny])
def skill_suggestions(request):
    """Référentiel des notions (liste fermée, apps/caracteristics/notions.py) pour l'éditeur.

    GET /api/skills/?chapter=<id>&q=<recherche>
    Renvoie {slug, label, chapter, count} : d'abord les notions du chapitre demandé, puis les
    transversales, puis les autres ; « count » = nombre de questions qui l'emploient déjà.
    """
    import unicodedata
    from collections import Counter
    from apps.caracteristics.models import Chapter
    from apps.caracteristics.notions import NOTION_INDEX

    def fold(text):
        return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()

    chapter_id = request.query_params.get('chapter')
    query = fold((request.query_params.get('q') or '').strip())
    chapter_name = Chapter.objects.filter(pk=chapter_id).values_list('name', flat=True).first() if chapter_id and chapter_id.isdigit() else None

    counts = cache.get('skill_usage_counts')
    if counts is None:
        counter = Counter()
        for jc in Content.objects.exclude(json_content={}).values_list('json_content', flat=True).iterator():
            for _, _, meta in _walk_questions_meta(jc):
                for slug in (meta.get('skills') or []):
                    counter[slug] += 1
        counts = dict(counter)
        cache.set('skill_usage_counts', counts, 300)

    def rank(item):
        slug, entry = item
        group = 0 if chapter_name and entry['chapter'] == chapter_name else 1 if entry['chapter'] is None else 2
        return (group, -counts.get(slug, 0), entry['label'])

    results = [
        {'slug': slug, 'label': entry['label'], 'chapter': entry['chapter'], 'count': counts.get(slug, 0)}
        for slug, entry in sorted(NOTION_INDEX.items(), key=rank)
        if not query or query in slug or query in fold(entry['label'])
    ]
    # Liste complète (~160 notions) : l'éditeur la garde en cache et filtre lui-même.
    return Response(results)


# =====================
# PAGINATION
# =====================

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
    # Tout utilisateur connecté peut publier ; seul l'auteur (ou le staff) modifie, supprime
    # ou réécrit la solution. Les autres actions (voter, commenter…) restent ouvertes.
    permission_classes = [IsAuthorOrStaffOrReadOnly]
    author_only_actions = ('update', 'partial_update', 'destroy', 'solution')
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
        # Avec une recherche, la pertinence prime : « Pour toi » ne s'applique qu'à la liste parcourue.
        if request.query_params.get('sort') == 'recommended' and not (request.query_params.get('search') or '').strip():
            return self._list_recommended(request, queryset)
        page = self.paginate_queryset(queryset)
        items = page if page is not None else queryset
        # La structure (json_content) est une colonne de chaque ligne, déjà chargée.
        serializer = self.get_serializer(items, many=True)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    def _list_recommended(self, request, queryset):
        """Tri « Pour toi » (things/for_you.py) : l'ordre est calculé en Python, page par page.

        La première page recalcule toujours (ce qu'il vient de réussir descend aussitôt) et garde
        l'ordre 10 min pour les pages suivantes : le défilement ne montre ni doublon ni trou.
        """
        params = sorted((k, v) for k, v in request.query_params.lists() if k not in ('page', 'page_size'))
        user = request.user if getattr(request.user, 'is_authenticated', False) else None
        key = 'for_you_' + hashlib.md5(repr((user and user.id, params)).encode()).hexdigest()
        ranked = cache.get(key) if request.query_params.get('page', '1') != '1' else None
        if ranked is None:
            ranked = for_you.rank(queryset, user)
            cache.set(key, ranked, 600)
        page = self.paginate_queryset(ranked)
        reasons = {str(cid): why for cid, why in page}
        items = in_order(with_list_relations(Content.objects.all(), user), [cid for cid, _ in page])
        data = self.get_serializer(items, many=True).data
        for row in data:
            row['recommendation_reason'] = reasons.get(str(row['id']))
        return self.get_paginated_response(data)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        # Toute action d'un élève sur ce contenu (auto-évaluation, réussite, temps, solution vue)
        # change SES statistiques : on vide son cache (5 min) pour que l'onglet Activité soit à
        # jour tout de suite — sinon il restait sur « Évalue tes réponses » après l'évaluation.
        pk = kwargs.get('pk')
        user = getattr(request, 'user', None)
        if (pk and request.method not in ('GET', 'HEAD', 'OPTIONS') and response.status_code < 400
                and user is not None and user.is_authenticated):
            cache.delete(f'content_stats_{pk}_user_{user.id}')
        return response

    def perform_destroy(self, instance):
        # Supprimé par son auteur ou par l'administration : les fichiers qui en dépendent partent
        # avec lui (figures de l'énoncé, photos des commentaires et des solutions proposées),
        # sinon ils resteraient sur S3 sans plus être rattachés à rien.
        from apps.uploads.models import FileAttachment
        owners = [
            (Content, [instance.pk]),
            (Comment, list(Comment.objects.filter(content_item=instance).values_list('id', flat=True))),
            (ProposedSolution, list(ProposedSolution.objects.filter(content_item=instance).values_list('id', flat=True))),
        ]
        for model, ids in owners:
            if not ids:
                continue
            for att in FileAttachment.objects.filter(content_type=ContentType.objects.get_for_model(model), object_id__in=ids):
                att.file.delete(save=False)
                att.delete()
        instance.delete()

    def get_queryset(self):
        # Préchargements partagés avec les autres listes de cartes (things/listing.py).
        queryset = with_list_relations(Content.objects.all(), getattr(self.request, 'user', None))

        # Type scope (from subclass or query param)
        type_scope = self.content_type_scope or self.request.query_params.get('type')
        if type_scope:
            queryset = queryset.filter(type=type_scope)

        # Recherche : chaque mot doit apparaître dans le titre, l'énoncé (json_content), la
        # matière, un chapitre, un théorème… Avant, la recherche appelait similarity() de
        # l'extension pg_trgm, absente de la base : toute recherche renvoyait une erreur 500.
        # (L'ancien champ texte `content`, hérité de l'époque MongoDB, a été supprimé.)
        search_query = (self.request.query_params.get('search') or '').strip()[:100]
        if search_query:
            matching = Content.objects.annotate(_body=Cast('json_content', TextField()))
            for term in search_query.split()[:6]:
                matching = matching.filter(
                    Q(title__icontains=term) |
                    Q(_body__icontains=term) |
                    Q(subject__name__icontains=term) |
                    Q(chapters__name__icontains=term) |
                    Q(theorems__name__icontains=term) |
                    Q(subfields__name__icontains=term) |
                    Q(class_levels__name__icontains=term)
                )
            # Sous-requête sur les identifiants : les jointures (chapitres, théorèmes…) ne
            # dupliquent pas les résultats et ne faussent pas les compteurs de votes.
            queryset = queryset.filter(pk__in=matching.values('pk')).annotate(
                _search_rank=Case(
                    When(title__icontains=search_query, then=0),
                    default=1,
                    output_field=IntegerField(),
                ),
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
        year_min = self.request.query_params.get('national_year_min')
        year_max = self.request.query_params.get('national_year_max')

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
        if year_min and year_min.isdigit():
            filters &= Q(national_year__gte=int(year_min))
        if year_max and year_max.isdigit():
            filters &= Q(national_year__lte=int(year_max))

        if self.request.user and self.request.user.is_authenticated:
            content_ct = ContentType.objects.get_for_model(Content)
            status_filter = Q()
            if show_viewed:
                # object_id is a CharField — materialize as ints for the bigint id__in
                viewed_ids = [
                    int(oid) for oid in ViewHistory.objects.filter(
                        user=self.request.user, content_type=content_ct
                    ).values_list('object_id', flat=True)
                    if str(oid).isdigit()
                ]
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
            viewed_ids = [
                int(oid) for oid in ViewHistory.objects.filter(
                    user=self.request.user, content_type=content_ct
                ).values_list('object_id', flat=True)
                if str(oid).isdigit()
            ]
            queryset = queryset.exclude(id__in=viewed_ids)

        sort_by = self.request.query_params.get('sort')
        if search_query and sort_by in (None, '', 'recommended'):
            # Recherche sans tri choisi (ou « Pour toi », qui ne vaut que sans recherche) : les titres qui contiennent la recherche d'abord.
            queryset = queryset.order_by('_search_rank', '-created_at')
        elif sort_by == 'oldest':
            queryset = queryset.order_by('created_at')
        elif sort_by == 'recommended':
            pass  # ordre calculé dans list() (things/for_you.py)
        elif sort_by == 'most_upvoted':
            # « Plus aimés » : le plus de j'aime, puis le moins de je n'aime pas.
            queryset = queryset.order_by('-like_count_annotation', 'dislike_count_annotation', '-created_at')
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
        item = self.get_object()
        serializer = CommentSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            comment = serializer.save(
                content_item=item,
                author=request.user,
                parent_id=request.data.get('parent')
            )
            # Uniquement ses propres fichiers, encore libres (voir attach_own_files).
            file_ids = request.data.get('file_ids') or []
            if isinstance(file_ids, list):
                attach_own_files(comment, file_ids[:6], request.user)
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

    # ---- à évaluer (bandeau de rattrapage de la liste « Pour toi ») ----
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated], url_path='a-evaluer')
    def a_evaluer(self, request):
        """Contenus ouverts et travaillés sans « Réussi » ni « À revoir » (things/catch_up.py)."""
        from .catch_up import pending
        kind = self.content_type_scope or request.query_params.get('type') or 'exercise'
        if kind not in (Content.TYPE_EXERCISE, Content.TYPE_EXAM):
            return Response({'count': 0, 'items': []})
        exclude = [int(x) for x in (request.query_params.get('exclude') or '').split(',')[:300] if x.isdigit()]
        count, items = pending(request.user, kind, exclude)
        return Response({'count': count, 'items': items})

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
        _forget_stats(item.id, request.user.id)
        return Response({'question_path': progress.question_path, 'status': progress.status,
                         'assessed_at': progress.assessed_at})

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def assess_many(self, request, pk=None):
        """Plusieurs questions d'un coup (« Tout réussi ») : {assessments: {chemin: statut | null}},
        et, si `completion` est donné, le résultat du contenu (« success », « review » ou null pour l'effacer)."""
        item = self.get_object()
        assessments = request.data.get('assessments')
        if not isinstance(assessments, dict) or not assessments or len(assessments) > 300:
            return Response({'error': 'assessments required'}, status=status.HTTP_400_BAD_REQUEST)
        for path, st in assessments.items():
            if not isinstance(path, str) or not path or len(path) > 255 or st not in (None, 'success', 'partial', 'review', 'failed'):
                return Response({'error': 'Invalid assessment'}, status=status.HTTP_400_BAD_REQUEST)
        completion = request.data.get('completion', 'unchanged')
        if completion not in ('unchanged', None, 'success', 'review'):
            return Response({'error': 'Invalid completion'}, status=status.HTTP_400_BAD_REQUEST)
        ct = ContentType.objects.get_for_model(Content)
        mine = dict(user=request.user, content_type=ct, object_id=item.id)
        with transaction.atomic():
            for path, st in assessments.items():
                if st is None:
                    QuestionProgress.objects.filter(question_path=path, **mine).delete()
                else:
                    QuestionProgress.objects.update_or_create(question_path=path, defaults={'status': st}, **mine)
            if completion is None:
                Complete.objects.filter(**mine).delete()
            elif completion != 'unchanged':
                Complete.objects.update_or_create(defaults={'status': completion}, **mine)
        _forget_stats(item.id, request.user.id)
        progress = {r.question_path: {'status': r.status, 'solution_validation': r.solution_validation,
                                      'assessed_at': r.assessed_at}
                    for r in QuestionProgress.objects.filter(**mine)}
        done = Complete.objects.filter(**mine).first()
        return Response({'item_progress': progress, 'completion': done.status if done else None})

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
        _forget_stats(item.id, request.user.id)
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
    # Compteur de vues : une vue par personne et par contenu sur 24 h. Avant le 05/10/2026, les
    # visiteurs non connectés (l'essentiel du trafic) recevaient une erreur 401 et n'étaient jamais
    # comptés, et les vues des administrateurs / du compte de test l'étaient.
    @action(detail=True, methods=['post'], permission_classes=[AllowAny])
    def view(self, request, pk=None):
        from apps.users.admin_dashboard import _house_filter

        item = self.get_object()
        ua = request.META.get('HTTP_USER_AGENT', '')
        if not ua or BOT_UA.search(ua):
            return Response({'view_count': item.view_count, 'counted': False})

        user = request.user if (request.user and request.user.is_authenticated) else None  # visiteur : None (UNAUTHENTICATED_USER)
        should_count = False
        try:
            if user is not None:
                ct = ContentType.objects.get_for_model(Content)
                one_day_ago = timezone.now() - timedelta(days=1)
                already_viewed = ViewHistory.objects.filter(
                    user=user, content_type=ct, object_id=item.id, viewed_at__gte=one_day_ago
                ).exists()
                house = User.objects.filter(pk=user.pk).filter(_house_filter()).exists()
                should_count = not already_viewed and not house
                ViewHistory.objects.update_or_create(
                    user=user, content_type=ct, object_id=item.id, defaults={'status': 'viewed'}
                )
            else:
                # Visiteur : même adresse IP + même navigateur = une vue par 24 h (cache partagé).
                ip = request.META.get('HTTP_CF_CONNECTING_IP', '').strip() or request.META.get('REMOTE_ADDR', '')
                key = 'vue:%s:%s' % (item.id, hashlib.sha256(f'{ip}|{ua}'.encode()).hexdigest()[:32])
                should_count = cache.add(key, 1, 24 * 3600)
            if should_count:
                Content.objects.filter(id=item.id).update(view_count=F('view_count') + 1)
                item.refresh_from_db(fields=['view_count'])
                _count_daily_view(item.id)
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
    def _get_successful_users_study_stats(self, item, ct):  # noqa: C901
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

            # ── Histogramme des temps (8 classes, bornées au p95 pour lisser les outliers)
            durations = sorted(int(s.session_duration.total_seconds()) for s in sessions)
            time_histogram = None
            if durations:
                p95 = durations[min(len(durations) - 1, int(len(durations) * 0.95))]
                upper = max(p95, durations[0] + 1)
                width = max(1, upper // 8)
                buckets = [0] * 8
                for d in durations:
                    buckets[min(d // width, 7)] += 1
                user_bucket = min(user_time_seconds // width, 7) if user_time_seconds is not None else None
                time_histogram = {
                    'buckets': buckets,
                    'bucket_width_seconds': width,
                    'user_bucket': user_bucket,
                }

            # ── Réussite par question (auto-évaluations QuestionProgress)
            # Ordre + libellés lisibles depuis la structure ; agrégats depuis QuestionProgress.
            from apps.interactions.models import QuestionProgress
            qp = QuestionProgress.objects.filter(content_type=ct, object_id=item.id)
            questions_meta = list(_walk_questions_meta(item.json_content or {}))
            path_label = {path: label for path, label, _ in questions_meta}
            path_skills = {path: (meta.get('skills') or []) for path, _, meta in questions_meta}

            by_path = {}
            for row in qp.values('question_path', 'status'):
                b = by_path.setdefault(row['question_path'], {'total': 0, 'success': 0})
                b['total'] += 1
                if row['status'] == 'success':
                    b['success'] += 1
            user_statuses = {}
            if is_auth:
                user_statuses = dict(qp.filter(user=request.user).values_list('question_path', 'status'))

            # Suivre l'ordre de la structure ; garder les orphelins (paths sans structure) à la fin.
            ordered_paths = [p for p, _, _ in questions_meta] + [p for p in by_path if p not in path_label]
            per_question = []
            for path in ordered_paths:
                b = by_path.get(path)
                if not b:
                    continue
                per_question.append({
                    'path': path,
                    'label': path_label.get(path, path[:6]),
                    'total': b['total'],
                    'success_pct': int(b['success'] / b['total'] * 100),
                    'user_status': user_statuses.get(path),
                })
            candidates = [q for q in per_question if q['total'] >= 3]
            trap_question = min(candidates, key=lambda q: q['success_pct']) if candidates else None

            # ── Maîtrise par notion (schéma v2.1 : meta.skills par question)
            from apps.caracteristics.notions import notion_label
            per_skill = []
            if is_auth and user_statuses:
                skill_agg = {}  # slug -> {done, success}
                for path, st in user_statuses.items():
                    for skill in path_skills.get(path, []):
                        a = skill_agg.setdefault(skill, {'done': 0, 'success': 0})
                        a['done'] += 1
                        if st == 'success':
                            a['success'] += 1
                for slug, a in sorted(skill_agg.items()):
                    per_skill.append({
                        'skill': slug,
                        'label': notion_label(slug),
                        'assessed': a['done'],
                        'mastery_pct': int(a['success'] / a['done'] * 100) if a['done'] else 0,
                    })

            # Gate de réciprocité : l'utilisateur a-t-il évalué quelque chose ici ?
            user_assessed = bool(user_statuses) or user_completed is not None

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
                'successful_users_study_stats': study_stats,
                'time_histogram': time_histogram,
                'per_question': per_question,
                'trap_question': trap_question,
                'per_skill': per_skill,
                'user_assessed': user_assessed,
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

    # ---- Correction IA (réservée au superuser) ----
    # Pipeline minimal : photo de copie → verdict par question (voir services/ai_vision.py).
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def ai_correct(self, request, pk=None):
        item = self.get_object()
        if 'image' not in request.FILES:
            return Response({'error': 'No image provided'}, status=status.HTTP_400_BAD_REQUEST)
        image_file = request.FILES['image']
        if image_file.size > 10 * 1024 * 1024:
            return Response({'error': 'Image too large (max 10MB)'}, status=status.HTTP_400_BAD_REQUEST)

        ct = ContentType.objects.get_for_model(Content)
        correction = AICorrection.objects.create(
            user=request.user, content_type=ct, object_id=item.id,
            image=image_file, submission_state='submitted', language='fr'
        )
        try:
            from apps.interactions.services import AICorrector
            result = AICorrector().correct(
                image_path=correction.image.path,
                structure=item.json_content or {},
            )
        except Exception as e:
            logger.error(f"AI correction failed: {e}", exc_info=True)
            correction.delete()
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Enrichit chaque verdict avec le libellé lisible (Q1, Q2a…) à partir de la structure.
        labels = {p: lbl for p, lbl, _ in _walk_questions_meta(item.json_content or {})}
        for v in result['per_question']:
            v['label'] = labels.get(v.get('path'), v.get('path', ''))

        correction.score_awarded = result['score_awarded']
        correction.score_total = result['score_total']
        correction.feedback = {
            'per_question': result['per_question'],
            'global_feedback': result['global_feedback'],
        }
        correction.raw_response = result['raw_response']
        correction.processing_time_ms = result['processing_time_ms']
        correction.save()
        return Response({
            'correction_id': str(correction.id),
            'score_awarded': result['score_awarded'],
            'score_total': result['score_total'],
            'per_question': result['per_question'],
            'global_feedback': result['global_feedback'],
            'processing_time_ms': result['processing_time_ms'],
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], permission_classes=[IsAdminUser])
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
    permission_classes = [IsAuthorOrStaffOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


# =====================
# COMMENT VIEWSET
# =====================

class CommentViewSet(VoteMixin, viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [IsAuthorOrStaffOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def perform_destroy(self, instance):
        # Les images du commentaire (et de ses réponses) partent avec lui : sinon elles
        # restaient sur S3 sans plus être rattachées à rien.
        from apps.uploads.models import FileAttachment
        ct = ContentType.objects.get_for_model(Comment)
        ids = [instance.id]
        frontier = [instance.id]
        while frontier:
            frontier = list(Comment.objects.filter(parent_id__in=frontier).values_list('id', flat=True))
            ids += frontier
        for attachment in FileAttachment.objects.filter(content_type=ct, object_id__in=ids):
            if attachment.file:
                attachment.file.delete(save=False)
            attachment.delete()
        instance.delete()


@api_view(['POST'])
@perm_classes([IsAuthenticated])
@throttle_classes([PdfParseThrottle])
def parse_pdf_view(request):
    """
    POST /api/parse-pdf/
    Multipart: file=<pdf>, content_type=exercise|exam|lesson
    Returns: simplified JSON ready for JsonImportModal
    """
    pdf_file = request.FILES.get('file')
    if not pdf_file:
        return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
    if not pdf_file.name.lower().endswith('.pdf'):
        return Response({'error': 'File must be a PDF'}, status=status.HTTP_400_BAD_REQUEST)

    content_type = request.data.get('content_type', 'exercise')
    if content_type not in ('exercise', 'exam', 'lesson'):
        return Response({'error': 'content_type must be exercise, exam, or lesson'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        pdf_bytes = pdf_file.read()
        result = parse_pdf(pdf_bytes, content_type, filename=pdf_file.name)
        return Response(result, status=status.HTTP_200_OK)
    except RuntimeError as e:
        return Response({'error': str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    except Exception:
        logger.exception('PDF parsing failed')
        return Response({'error': 'Internal error during PDF parsing'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_content_recommendations(request, content_id):
    """« Pour continuer » sous un contenu : les plus semblables (apps/things/similar.py), avec la raison."""
    from apps.things.similar import similar
    if not Content.objects.filter(id=content_id).exists():
        return Response({'error': 'Not found'}, status=404)
    picks = similar(int(content_id), getattr(request, 'user', None))
    loaded = with_list_relations(Content.objects.all(), getattr(request, 'user', None))
    cards = serialize_content_list(in_order(loaded, [cid for cid, _, _ in picks]), request)
    reasons = {cid: reason for cid, _, reason in picks}
    for card in cards:
        card['reason'] = reasons.get(card['id'], '')
        card.pop('json_content', None)  # la carte n'affiche pas l'énoncé : réponse 20 fois plus légère
        card.pop('structure', None)
    return Response({'items': cards})


# =====================
# PROPOSED SOLUTIONS (élèves)
# =====================

def attach_own_files(obj, file_ids, user, allowed_types=None):
    """Rattache à `obj` les fichiers envoyés par `user` et encore libres.

    Jamais les fichiers d'un autre, ni un fichier déjà rattaché ailleurs (sinon on
    pourrait déplacer la pièce jointe d'un autre commentaire ou d'une autre solution).
    """
    from apps.uploads.models import FileAttachment
    if not file_ids:
        return 0
    qs = FileAttachment.objects.filter(id__in=file_ids, uploaded_by=user, object_id__isnull=True)
    if allowed_types:
        qs = qs.filter(file_type__in=allowed_types)
    return qs.update(content_type=ContentType.objects.get_for_model(obj), object_id=obj.id)


class ProposedSolutionViewSet(VoteMixin, viewsets.ModelViewSet):
    """Solutions proposées par les élèves.

    GET  /api/proposed-solutions/?content=<id>   liste (la plus votée d'abord)
    POST /api/proposed-solutions/                {content, body, file_ids}
    PATCH/DELETE /api/proposed-solutions/<id>/   auteur (ou staff) uniquement
    POST /api/proposed-solutions/<id>/vote/      {value: 1 | -1}
    """
    serializer_class = ProposedSolutionSerializer
    permission_classes = [IsAuthorOrStaffOrReadOnly]
    pagination_class = None

    def get_throttles(self):
        if self.action == 'create':
            return [ProposedSolutionThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        qs = ProposedSolution.objects.select_related('author', 'author__profile').prefetch_related('votes', 'attachments')
        if self.action == 'list':
            content_id = self.request.query_params.get('content')
            if not str(content_id or '').isdigit():
                return qs.none()
            qs = qs.filter(content_item_id=int(content_id))
        return qs

    def list(self, request, *args, **kwargs):
        items = list(self.get_queryset()[:200])
        data = self.get_serializer(items, many=True).data
        # La plus utile d'abord ; à égalité, la plus récente (deux tris stables).
        data = sorted(data, key=lambda d: d['created_at'], reverse=True)
        data.sort(key=lambda d: -(d['vote_count'] or 0))
        return Response(data)

    def perform_create(self, serializer):
        file_ids = serializer.validated_data.pop('file_ids', [])
        solution = serializer.save(author=self.request.user)
        attach_own_files(solution, file_ids, self.request.user, allowed_types=['image', 'document'])

    def perform_update(self, serializer):
        file_ids = serializer.validated_data.pop('file_ids', [])
        solution = serializer.save()
        attach_own_files(solution, file_ids, self.request.user, allowed_types=['image', 'document'])

    def perform_destroy(self, instance):
        for attachment in instance.attachments.all():
            if attachment.file:
                attachment.file.delete(save=False)
            attachment.delete()
        instance.delete()
