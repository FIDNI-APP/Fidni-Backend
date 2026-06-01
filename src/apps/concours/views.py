"""
Concours views — exam CRUD, tip CRUD, simulation flow, comments, saves.

Public/student endpoints:

    GET    /api/concours/exams/                          list (filter by concours_type, year, year range)
    GET    /api/concours/exams/<id>/                     normal view (with solutions)
    GET    /api/concours/exams/<id>/?hide_solutions=1    student-safe view
    POST   /api/concours/exams/<id>/save/                save / unsave
    GET    /api/concours/exams/<id>/comments/            list comments
    POST   /api/concours/exams/<id>/comments/            create comment

    GET    /api/concours/tips/                           list (filter)
    GET    /api/concours/tips/<id>/                      detail
    POST   /api/concours/tips/<id>/save/
    POST   /api/concours/tips/<id>/vote/                 body {value: 1|-1|0}
    GET    /api/concours/tips/<id>/comments/
    POST   /api/concours/tips/<id>/comments/

    POST   /api/concours/sessions/start/                 start a simulation
                                                          body {mode, concours_type, exam_id?, n_questions?}
    GET    /api/concours/sessions/<uuid>/                resume / view
    POST   /api/concours/sessions/<uuid>/answer/         body {position, chosen_key}
    POST   /api/concours/sessions/<uuid>/submit/         finalise
    GET    /api/concours/sessions/                       my history

Superuser/admin endpoints:

    POST/PATCH/DELETE on /api/concours/exams/...
    PUT    /api/concours/exams/<id>/structure/           replace the QCM JSON

    POST/PATCH/DELETE on /api/concours/tips/...
"""

import random
import uuid as _uuid

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status, viewsets, mixins, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, IsAdminUser
from rest_framework.response import Response

from apps.interactions.models import Save, Vote

from .models import (
    ConcoursExam, ConcoursTip, ConcoursComment, ConcoursExamStats,
    SimulationSession, SimulationAnswer,
    CONCOURS_TYPE_CHOICES,
)
from .serializers import (
    ConcoursExamSerializer, ConcoursExamListSerializer, ConcoursExamWriteSerializer,
    ConcoursTipSerializer,
    ConcoursCommentSerializer,
    SimulationSessionListSerializer, SimulationSessionDetailSerializer,
)
from .content_store import (
    get_concours_structure, set_concours_structure, delete_concours_structure,
)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

class IsAdminOrReadOnly(permissions.BasePermission):
    """Read for everyone (including anonymous); write only for staff."""
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.is_staff


# ---------------------------------------------------------------------------
# ConcoursExam
# ---------------------------------------------------------------------------

class ConcoursExamViewSet(viewsets.ModelViewSet):
    queryset = ConcoursExam.objects.all().select_related('created_by')
    permission_classes = [IsAdminOrReadOnly]

    def get_serializer_class(self):
        if self.action == 'list':
            return ConcoursExamListSerializer
        if self.action in ('create', 'update', 'partial_update'):
            return ConcoursExamWriteSerializer
        return ConcoursExamSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        # `?hide_solutions=1` strips correct_key/explanation in the response.
        if self.request.query_params.get('hide_solutions') in ('1', 'true', 'yes'):
            ctx['hide_solutions'] = True
        return ctx

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get('concours_type'):
            qs = qs.filter(concours_type=params['concours_type'])
        if params.get('year'):
            try:
                qs = qs.filter(year=int(params['year']))
            except ValueError:
                pass
        if params.get('year_min'):
            try:
                qs = qs.filter(year__gte=int(params['year_min']))
            except ValueError:
                pass
        if params.get('year_max'):
            try:
                qs = qs.filter(year__lte=int(params['year_max']))
            except ValueError:
                pass
        return qs

    def perform_create(self, serializer):
        exam = serializer.save(created_by=self.request.user)
        # Initialise an empty Mongo doc.
        set_concours_structure(exam.concours_type, exam.display_id,
                               {'version': '1.0', 'questions': []})

    def perform_destroy(self, instance):
        delete_concours_structure(instance.concours_type, instance.display_id)
        super().perform_destroy(instance)

    # ----- Custom actions -----

    @action(detail=True, methods=['get', 'put'], url_path='structure',
            permission_classes=[IsAuthenticated])
    def structure(self, request, pk=None):
        """GET returns the full structure (admins only get correct_key + explanation
        when not adding ?hide_solutions=1). PUT replaces it (staff only)."""
        exam = self.get_object()

        if request.method == 'GET':
            s = get_concours_structure(exam.concours_type, exam.display_id) or {}
            if not request.user.is_staff and request.query_params.get('hide_solutions'):
                qs = [{k: v for k, v in q.items()
                       if k not in ('correct_key', 'explanation')}
                      for q in s.get('questions', [])]
                s = {**s, 'questions': qs}
            return Response(s)

        # PUT
        if not request.user.is_staff:
            return Response({'detail': 'Réservé aux administrateurs.'},
                            status=status.HTTP_403_FORBIDDEN)
        payload = request.data
        if not isinstance(payload, dict):
            return Response({'detail': 'Body must be a JSON object.'},
                            status=status.HTTP_400_BAD_REQUEST)
        # Light validation
        questions = payload.get('questions', [])
        if not isinstance(questions, list):
            return Response({'detail': '`questions` must be a list.'},
                            status=status.HTTP_400_BAD_REQUEST)
        for i, q in enumerate(questions):
            if not isinstance(q, dict):
                return Response({'detail': f'questions[{i}] must be an object.'},
                                status=status.HTTP_400_BAD_REQUEST)
            if 'id' not in q or not q['id']:
                q['id'] = f'q{i + 1}'
            if not isinstance(q.get('options', []), list):
                return Response({'detail': f'questions[{i}].options must be a list.'},
                                status=status.HTTP_400_BAD_REQUEST)
            if not q.get('correct_key'):
                return Response({'detail': f'questions[{i}].correct_key is required.'},
                                status=status.HTTP_400_BAD_REQUEST)
        payload.setdefault('version', '1.0')

        set_concours_structure(exam.concours_type, exam.display_id, payload)
        return Response({'ok': True, 'question_count': len(questions)})

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save(self, request, pk=None):
        exam = self.get_object()
        ct = ContentType.objects.get_for_model(ConcoursExam)
        existing = Save.objects.filter(
            user=request.user, content_type=ct, object_id=str(exam.id)
        ).first()
        if existing:
            existing.delete()
            return Response({'is_saved': False})
        Save.objects.create(user=request.user, content_type=ct, object_id=str(exam.id))
        return Response({'is_saved': True})


# ---------------------------------------------------------------------------
# ConcoursTip
# ---------------------------------------------------------------------------

class ConcoursTipViewSet(viewsets.ModelViewSet):
    serializer_class = ConcoursTipSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = (ConcoursTip.objects
              .all()
              .select_related('subject', 'subfield', 'created_by', 'video_file')
              .prefetch_related('chapters'))
        params = self.request.query_params
        if params.get('subject'):
            try:
                qs = qs.filter(subject_id=int(params['subject']))
            except ValueError:
                pass
        if params.get('subfield'):
            try:
                qs = qs.filter(subfield_id=int(params['subfield']))
            except ValueError:
                pass
        if params.get('chapter'):
            try:
                qs = qs.filter(chapters__id=int(params['chapter']))
            except ValueError:
                pass
        if params.get('concours_type'):
            ct = params['concours_type']
            qs = qs.filter(concours_types__contains=[ct])
        if params.get('search'):
            qs = qs.filter(title__icontains=params['search'])
        return qs.distinct()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save(self, request, pk=None):
        tip = self.get_object()
        ct = ContentType.objects.get_for_model(ConcoursTip)
        existing = Save.objects.filter(
            user=request.user, content_type=ct, object_id=str(tip.id)
        ).first()
        if existing:
            existing.delete()
            return Response({'is_saved': False})
        Save.objects.create(user=request.user, content_type=ct, object_id=str(tip.id))
        return Response({'is_saved': True})

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def vote(self, request, pk=None):
        tip = self.get_object()
        try:
            value = int(request.data.get('value', 0))
        except (TypeError, ValueError):
            return Response({'detail': 'value must be -1, 0, or 1.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if value not in (-1, 0, 1):
            return Response({'detail': 'value must be -1, 0, or 1.'},
                            status=status.HTTP_400_BAD_REQUEST)
        ct = ContentType.objects.get_for_model(ConcoursTip)
        Vote.objects.filter(
            user=request.user, content_type=ct, object_id=str(tip.id)
        ).delete()
        if value != 0:
            Vote.objects.create(
                user=request.user, content_type=ct, object_id=str(tip.id), value=value,
            )
        agg = tip.votes.filter(value=1).count() - tip.votes.filter(value=-1).count()
        return Response({'vote_count': agg, 'user_vote': value})


# ---------------------------------------------------------------------------
# Comments (on exams or tips)
# ---------------------------------------------------------------------------

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedOrReadOnly])
def exam_comments(request, exam_id):
    exam = get_object_or_404(ConcoursExam, pk=exam_id)
    if request.method == 'GET':
        qs = ConcoursComment.objects.filter(
            target_type=ConcoursComment.TARGET_EXAM, target_id=exam.id, parent__isnull=True,
        ).select_related('author').order_by('-created_at')
        return Response(ConcoursCommentSerializer(qs, many=True, context={'request': request}).data)
    # POST
    if not request.user.is_authenticated:
        return Response({'detail': 'Authentication required.'}, status=status.HTTP_401_UNAUTHORIZED)
    content = (request.data.get('content') or '').strip()
    parent_id = request.data.get('parent')
    if not content:
        return Response({'detail': 'content is required.'}, status=status.HTTP_400_BAD_REQUEST)
    c = ConcoursComment.objects.create(
        target_type=ConcoursComment.TARGET_EXAM, target_id=exam.id,
        author=request.user, content=content,
        parent_id=parent_id if parent_id else None,
    )
    return Response(ConcoursCommentSerializer(c, context={'request': request}).data,
                    status=status.HTTP_201_CREATED)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedOrReadOnly])
def tip_comments(request, tip_id):
    tip = get_object_or_404(ConcoursTip, pk=tip_id)
    if request.method == 'GET':
        qs = ConcoursComment.objects.filter(
            target_type=ConcoursComment.TARGET_TIP, target_id=tip.id, parent__isnull=True,
        ).select_related('author').order_by('-created_at')
        return Response(ConcoursCommentSerializer(qs, many=True, context={'request': request}).data)
    if not request.user.is_authenticated:
        return Response({'detail': 'Authentication required.'}, status=status.HTTP_401_UNAUTHORIZED)
    content = (request.data.get('content') or '').strip()
    parent_id = request.data.get('parent')
    if not content:
        return Response({'detail': 'content is required.'}, status=status.HTTP_400_BAD_REQUEST)
    c = ConcoursComment.objects.create(
        target_type=ConcoursComment.TARGET_TIP, target_id=tip.id,
        author=request.user, content=content,
        parent_id=parent_id if parent_id else None,
    )
    return Response(ConcoursCommentSerializer(c, context={'request': request}).data,
                    status=status.HTTP_201_CREATED)


@api_view(['DELETE', 'PATCH'])
@permission_classes([IsAuthenticated])
def comment_detail(request, comment_id):
    c = get_object_or_404(ConcoursComment, pk=comment_id)
    if c.author_id != request.user.id and not request.user.is_staff:
        return Response({'detail': 'Forbidden.'}, status=status.HTTP_403_FORBIDDEN)
    if request.method == 'DELETE':
        c.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    new_content = (request.data.get('content') or '').strip()
    if not new_content:
        return Response({'detail': 'content is required.'}, status=status.HTTP_400_BAD_REQUEST)
    c.content = new_content
    c.save(update_fields=['content', 'updated_at'])
    return Response(ConcoursCommentSerializer(c, context={'request': request}).data)


# ---------------------------------------------------------------------------
# Simulation flow
# ---------------------------------------------------------------------------

def _build_exam_questions_snapshot(exam: ConcoursExam) -> list:
    """Return [{exam_id, exam_display_id, question, position}, ...] for one exam."""
    s = exam.get_structure() or {}
    qs = s.get('questions', []) or []
    return [
        {
            'exam_id': exam.id,
            'exam_display_id': exam.display_id,
            'question': q,
            'position': i,
        }
        for i, q in enumerate(qs)
    ]


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def start_simulation(request):
    """
    Body:
      {
        "mode": "exam" | "random_year" | "random_mix",
        "concours_type": "ensa" | ...,
        "exam_id": <int>,            # required for mode="exam"
        "n_questions": <int>,        # for mode="random_mix"
        "duration_minutes": <int>    # optional override
      }
    """
    user = request.user
    mode = request.data.get('mode')
    concours_type = request.data.get('concours_type')
    if mode not in (SimulationSession.MODE_EXAM,
                    SimulationSession.MODE_RANDOM_YEAR,
                    SimulationSession.MODE_RANDOM_MIX):
        return Response({'detail': 'Invalid mode.'}, status=status.HTTP_400_BAD_REQUEST)
    if concours_type not in dict(CONCOURS_TYPE_CHOICES):
        return Response({'detail': 'Invalid concours_type.'}, status=status.HTTP_400_BAD_REQUEST)

    snapshot: list[dict] = []
    exam_obj: ConcoursExam | None = None
    duration: int | None = None

    if mode == SimulationSession.MODE_EXAM:
        exam_id = request.data.get('exam_id')
        if not exam_id:
            return Response({'detail': 'exam_id required.'}, status=status.HTTP_400_BAD_REQUEST)
        exam_obj = get_object_or_404(ConcoursExam, pk=exam_id, concours_type=concours_type)
        snapshot = _build_exam_questions_snapshot(exam_obj)
        duration = exam_obj.duration_minutes

    elif mode == SimulationSession.MODE_RANDOM_YEAR:
        all_exams = list(ConcoursExam.objects.filter(concours_type=concours_type))
        if not all_exams:
            return Response({'detail': 'No exam available for this concours.'},
                            status=status.HTTP_404_NOT_FOUND)
        exam_obj = random.choice(all_exams)
        snapshot = _build_exam_questions_snapshot(exam_obj)
        duration = exam_obj.duration_minutes

    else:  # random_mix
        n = int(request.data.get('n_questions') or 30)
        n = max(5, min(200, n))
        all_exams = ConcoursExam.objects.filter(concours_type=concours_type)
        pool: list[dict] = []
        for ex in all_exams:
            pool.extend(_build_exam_questions_snapshot(ex))
        if not pool:
            return Response({'detail': 'No question available.'}, status=status.HTTP_404_NOT_FOUND)
        random.shuffle(pool)
        snapshot = pool[:n]
        # Re-position
        for i, item in enumerate(snapshot):
            item['position'] = i
        duration = max(15, int(round(n * 1.5)))  # ~1.5 minutes per question

    if not snapshot:
        return Response({'detail': 'No question available for this exam.'},
                        status=status.HTTP_404_NOT_FOUND)

    duration = int(request.data.get('duration_minutes') or duration or 60)

    sess = SimulationSession.objects.create(
        user=user, mode=mode, concours_type=concours_type,
        exam=exam_obj, duration_minutes=duration,
        questions_snapshot=snapshot, total_questions=len(snapshot),
    )

    # Build student-safe response (no correct_key / explanation)
    safe_snapshot = [
        {**item,
         'question': {k: v for k, v in item['question'].items()
                      if k not in ('correct_key', 'explanation')}}
        for item in snapshot
    ]
    return Response({
        'session_id': str(sess.id),
        'mode': sess.mode,
        'concours_type': sess.concours_type,
        'exam': sess.exam_id,
        'duration_minutes': sess.duration_minutes,
        'started_at': sess.started_at,
        'total_questions': sess.total_questions,
        'questions_snapshot': safe_snapshot,
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_session(request, session_id):
    sess = get_object_or_404(SimulationSession, pk=session_id, user=request.user)
    if sess.status == SimulationSession.STATUS_SUBMITTED:
        return Response(SimulationSessionDetailSerializer(sess).data)
    # In-progress: hide solutions
    safe_snapshot = [
        {**item,
         'question': {k: v for k, v in item['question'].items()
                      if k not in ('correct_key', 'explanation')}}
        for item in (sess.questions_snapshot or [])
    ]
    answered = {a.position: a.chosen_key for a in sess.answers.all()}
    return Response({
        'session_id': str(sess.id),
        'mode': sess.mode,
        'concours_type': sess.concours_type,
        'exam': sess.exam_id,
        'duration_minutes': sess.duration_minutes,
        'started_at': sess.started_at,
        'status': sess.status,
        'total_questions': sess.total_questions,
        'questions_snapshot': safe_snapshot,
        'answers': answered,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def answer_question(request, session_id):
    sess = get_object_or_404(SimulationSession, pk=session_id, user=request.user)
    if sess.status != SimulationSession.STATUS_IN_PROGRESS:
        return Response({'detail': 'Session not in progress.'},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        position = int(request.data.get('position'))
    except (TypeError, ValueError):
        return Response({'detail': 'position required.'}, status=status.HTTP_400_BAD_REQUEST)
    chosen_key = (request.data.get('chosen_key') or '').strip()

    snapshot = sess.questions_snapshot or []
    if position < 0 or position >= len(snapshot):
        return Response({'detail': 'position out of range.'}, status=status.HTTP_400_BAD_REQUEST)
    q = snapshot[position]['question']

    SimulationAnswer.objects.update_or_create(
        session=sess, position=position,
        defaults={
            'chosen_key': chosen_key,
            'is_correct': bool(chosen_key) and chosen_key == q.get('correct_key'),
            'subject_id':  q.get('subject_id'),
            'subfield_id': q.get('subfield_id'),
            'chapter_id':  q.get('chapter_id'),
            'tip_id':      q.get('tip_id'),
        },
    )
    return Response({'ok': True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_session(request, session_id):
    sess = get_object_or_404(SimulationSession, pk=session_id, user=request.user)
    if sess.status == SimulationSession.STATUS_SUBMITTED:
        return Response(_build_session_recap(sess))

    snapshot = sess.questions_snapshot or []
    answers = {a.position: a for a in sess.answers.all()}
    correct_count = 0
    with transaction.atomic():
        # Fill in any missing positions as "unanswered"
        for i, item in enumerate(snapshot):
            q = item['question']
            a = answers.get(i)
            chosen = a.chosen_key if a else ''
            is_correct = bool(chosen) and chosen == q.get('correct_key')
            if a:
                a.is_correct = is_correct
                a.save(update_fields=['is_correct', 'chosen_key', 'subject_id',
                                      'subfield_id', 'chapter_id', 'tip_id'])
            else:
                SimulationAnswer.objects.create(
                    session=sess, position=i, chosen_key='',
                    is_correct=False,
                    subject_id=q.get('subject_id'), subfield_id=q.get('subfield_id'),
                    chapter_id=q.get('chapter_id'), tip_id=q.get('tip_id'),
                )
            if is_correct:
                correct_count += 1
        sess.correct_count = correct_count
        sess.total_questions = len(snapshot)
        sess.status = SimulationSession.STATUS_SUBMITTED
        sess.submitted_at = timezone.now()
        sess.save(update_fields=['correct_count', 'total_questions', 'status', 'submitted_at'])

    return Response(_build_session_recap(sess))


def _build_session_recap(sess: SimulationSession) -> dict:
    """Build the result-page payload — full snapshot + answers + breakdown."""
    from apps.caracteristics.models import Subject, Subfield

    answers = {a.position: a for a in sess.answers.all()}
    snapshot = sess.questions_snapshot or []

    # Per-(subject, subfield) breakdown
    breakdown_map: dict[tuple, dict] = {}
    for i, item in enumerate(snapshot):
        q = item['question']
        a = answers.get(i)
        sid = q.get('subject_id')
        fid = q.get('subfield_id')
        key = (sid, fid)
        bd = breakdown_map.setdefault(key, {
            'subject_id': sid,
            'subject_name': None,
            'subfield_id': fid,
            'subfield_name': None,
            'total': 0,
            'correct': 0,
            'positions': [],
        })
        bd['total'] += 1
        bd['positions'].append(i)
        if a and a.is_correct:
            bd['correct'] += 1

    # Hydrate names
    sids = {b['subject_id'] for b in breakdown_map.values() if b['subject_id']}
    fids = {b['subfield_id'] for b in breakdown_map.values() if b['subfield_id']}
    s_names = dict(Subject.objects.filter(id__in=sids).values_list('id', 'name'))
    f_names = dict(Subfield.objects.filter(id__in=fids).values_list('id', 'name'))
    breakdown = []
    for b in breakdown_map.values():
        if b['subject_id']:
            b['subject_name'] = s_names.get(b['subject_id'])
        if b['subfield_id']:
            b['subfield_name'] = f_names.get(b['subfield_id'])
        breakdown.append(b)

    breakdown.sort(key=lambda b: ((b['subject_name'] or 'zzz'), (b['subfield_name'] or 'zzz')))

    return {
        'session_id': str(sess.id),
        'mode': sess.mode,
        'concours_type': sess.concours_type,
        'exam_id': sess.exam_id,
        'duration_minutes': sess.duration_minutes,
        'started_at': sess.started_at,
        'submitted_at': sess.submitted_at,
        'status': sess.status,
        'total_questions': sess.total_questions,
        'correct_count': sess.correct_count,
        'score_percentage': sess.score_percentage,
        'questions_snapshot': sess.questions_snapshot,  # FULL — with solutions, OK now
        'answers': {
            i: {'chosen_key': a.chosen_key, 'is_correct': a.is_correct}
            for i, a in answers.items()
        },
        'breakdown': breakdown,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def session_recap(request, session_id):
    sess = get_object_or_404(SimulationSession, pk=session_id, user=request.user)
    return Response(_build_session_recap(sess))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_sessions(request):
    qs = (SimulationSession.objects
          .filter(user=request.user)
          .order_by('-started_at'))
    params = request.query_params
    if params.get('concours_type'):
        qs = qs.filter(concours_type=params['concours_type'])
    if params.get('status'):
        qs = qs.filter(status=params['status'])
    if params.get('mode'):
        qs = qs.filter(mode=params['mode'])
    return Response(SimulationSessionListSerializer(qs[:200], many=True).data)


# ---------------------------------------------------------------------------
# Exam statistics (auto distribution + admin-curated comparison)
# ---------------------------------------------------------------------------

def _exam_question_distribution(exam: ConcoursExam) -> dict:
    """
    Compute how this exam's questions split across subject / subfield / chapter,
    auto-derived from each question's tagged metadata.

    Returns {'subject': [...], 'subfield': [...], 'chapter': [...]} where each
    list holds {id, name, count, pct} entries sorted by count desc. An untagged
    bucket (id=None, name='Non classé') captures questions missing that tag.
    """
    from apps.caracteristics.models import Subject, Subfield, Chapter

    s = exam.get_structure() or {}
    questions = s.get('questions', []) or []
    total = len(questions)

    levels = {
        'subject': ('subject_id', Subject),
        'subfield': ('subfield_id', Subfield),
        'chapter': ('chapter_id', Chapter),
    }
    out: dict[str, list] = {}
    for level, (field, model) in levels.items():
        counts: dict = {}
        for q in questions:
            counts[q.get(field)] = counts.get(q.get(field), 0) + 1
        ids = {k for k in counts if k}
        names = dict(model.objects.filter(id__in=ids).values_list('id', 'name'))
        rows = []
        for key, count in counts.items():
            rows.append({
                'id': key,
                'name': names.get(key, 'Non classé') if key else 'Non classé',
                'count': count,
                'pct': round(count * 100 / total, 1) if total else 0,
            })
        rows.sort(key=lambda r: (-r['count'], r['name']))
        out[level] = rows
    return out


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticatedOrReadOnly])
def exam_stats(request, exam_id):
    """
    GET (public): auto distribution + admin-curated comparison block.
    PUT (staff):  save comparison_html + insight_cards.
    """
    exam = get_object_or_404(ConcoursExam, pk=exam_id)

    if request.method == 'GET':
        stats = getattr(exam, 'stats', None)
        return Response({
            'exam_id': exam.id,
            'total_questions': exam.question_count,
            'distribution': _exam_question_distribution(exam),
            'comparison_html': stats.comparison_html if stats else '',
            'insight_cards': stats.insight_cards if stats else [],
            'updated_at': stats.updated_at if stats else None,
        })

    # PUT — staff only
    if not (request.user and request.user.is_staff):
        return Response({'detail': 'Réservé aux administrateurs.'},
                        status=status.HTTP_403_FORBIDDEN)
    comparison_html = request.data.get('comparison_html', '')
    cards = request.data.get('insight_cards', [])
    if not isinstance(cards, list):
        return Response({'detail': 'insight_cards must be a list.'},
                        status=status.HTTP_400_BAD_REQUEST)
    clean_cards = []
    for c in cards:
        if not isinstance(c, dict):
            continue
        clean_cards.append({
            'title': str(c.get('title', '')).strip(),
            'text': str(c.get('text', '')).strip(),
        })
    stats, _ = ConcoursExamStats.objects.update_or_create(
        exam=exam,
        defaults={
            'comparison_html': comparison_html,
            'insight_cards': clean_cards,
            'updated_by': request.user,
        },
    )
    return Response({
        'exam_id': exam.id,
        'comparison_html': stats.comparison_html,
        'insight_cards': stats.insight_cards,
        'updated_at': stats.updated_at,
    })


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def exam_activity(request, exam_id):
    """
    Activity for one exam:
      - community: last 10 *submitted* exam-mode sessions on this exam, anonymised.
      - mine:      the current user's sessions on this exam (null if anonymous).
    """
    exam = get_object_or_404(ConcoursExam, pk=exam_id)

    community_qs = (SimulationSession.objects
                    .filter(exam=exam,
                            mode=SimulationSession.MODE_EXAM,
                            status=SimulationSession.STATUS_SUBMITTED)
                    .order_by('-submitted_at')[:10])
    community = [{
        'score_percentage': s.score_percentage,
        'correct_count': s.correct_count,
        'total_questions': s.total_questions,
        'submitted_at': s.submitted_at,
    } for s in community_qs]

    mine = None
    if request.user and request.user.is_authenticated:
        mine_qs = (SimulationSession.objects
                   .filter(exam=exam, mode=SimulationSession.MODE_EXAM,
                           user=request.user)
                   .order_by('-started_at')[:50])
        mine = SimulationSessionListSerializer(mine_qs, many=True).data

    return Response({
        'exam_id': exam.id,
        'community': community,
        'mine': mine,
    })
