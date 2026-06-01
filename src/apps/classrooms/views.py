"""
Classroom REST API.

Endpoints:
    GET    /api/classrooms/                  list classrooms (mine: owned + joined)
    POST   /api/classrooms/                  create classroom (teacher only)
    GET    /api/classrooms/<id>/             retrieve
    PATCH  /api/classrooms/<id>/             owner can rename / change description
    DELETE /api/classrooms/<id>/             owner deletes
    POST   /api/classrooms/<id>/regenerate_code/   owner regenerates join code
    GET    /api/classrooms/<id>/members/     owner lists members
    DELETE /api/classrooms/<id>/members/<student_id>/   owner removes a student
    POST   /api/classrooms/<id>/subjects/    owner adds subject + teacher
    DELETE /api/classrooms/<id>/subjects/<sub_id>/      owner removes a subject
    POST   /api/classrooms/join/             student joins by code  body: {code}
    POST   /api/classrooms/<id>/leave/       student leaves a classroom
    GET    /api/classrooms/progress/weekly/  student weekly success vs classroom avg
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status, viewsets, mixins
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.interactions.models import Complete, StudyTimeTracker
from apps.things.models import Content
from apps.caracteristics.models import Subject
from apps.users.models import UserProfile

from .models import (
    Classroom, ClassroomSubject, ClassroomMembership,
    TDList, TDListItem,
)
from .serializers import (
    ClassroomSerializer,
    ClassroomSubjectSerializer,
    ClassroomMembershipSerializer,
    TDListSerializer,
    TDListItemSerializer,
)


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def _is_teacher(user) -> bool:
    prof = getattr(user, 'profile', None)
    return bool(prof and prof.user_type == 'teacher')


def _classrooms_for_user(user):
    """Classrooms the user owns OR is a member of."""
    return (
        Classroom.objects
        .filter(Q(owner=user) | Q(memberships__student=user))
        .distinct()
    )


# ────────────────────────────────────────────────────────────────────
# ViewSet
# ────────────────────────────────────────────────────────────────────

class ClassroomViewSet(viewsets.ModelViewSet):
    serializer_class = ClassroomSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _classrooms_for_user(self.request.user).order_by('-created_at')

    def perform_create(self, serializer):
        if not _is_teacher(self.request.user):
            raise PermissionError("Seuls les enseignants peuvent créer une classe.")
        serializer.save(owner=self.request.user)

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.owner_id != request.user.id:
            return Response({'detail': "Seul le propriétaire peut modifier la classe."},
                            status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.owner_id != request.user.id:
            return Response({'detail': "Seul le propriétaire peut supprimer la classe."},
                            status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    # ── Custom actions ──────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='regenerate_code')
    def regenerate_code(self, request, pk=None):
        classroom = self.get_object()
        if classroom.owner_id != request.user.id:
            return Response({'detail': 'Action réservée au propriétaire.'},
                            status=status.HTTP_403_FORBIDDEN)
        new_code = classroom.regenerate_join_code()
        return Response({'join_code': new_code})

    @action(detail=True, methods=['get'], url_path='members')
    def members(self, request, pk=None):
        classroom = self.get_object()
        # Owner sees all; members see at least themselves + count via classroom serializer
        if classroom.owner_id != request.user.id and not classroom.memberships.filter(student=request.user).exists():
            return Response({'detail': 'Accès refusé.'}, status=status.HTTP_403_FORBIDDEN)
        qs = classroom.memberships.select_related('student', 'student__profile').all()
        return Response(ClassroomMembershipSerializer(qs, many=True, context={'request': request}).data)

    @action(detail=True, methods=['delete'], url_path=r'members/(?P<student_id>\d+)')
    def remove_member(self, request, pk=None, student_id=None):
        classroom = self.get_object()
        if classroom.owner_id != request.user.id:
            return Response({'detail': 'Action réservée au propriétaire.'},
                            status=status.HTTP_403_FORBIDDEN)
        deleted, _ = classroom.memberships.filter(student_id=student_id).delete()
        if not deleted:
            return Response({'detail': 'Élève introuvable dans la classe.'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='subjects')
    def add_subject(self, request, pk=None):
        classroom = self.get_object()
        if classroom.owner_id != request.user.id:
            return Response({'detail': 'Action réservée au propriétaire.'},
                            status=status.HTTP_403_FORBIDDEN)

        # default the teacher to the owner if not provided
        data = dict(request.data)
        if 'teacher_id' not in data or not data.get('teacher_id'):
            data['teacher_id'] = request.user.id

        serializer = ClassroomSubjectSerializer(data=data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        # Ensure that the teacher_id refers to a teacher account
        teacher = serializer.validated_data['teacher']
        if not _is_teacher(teacher):
            return Response({'detail': "L'utilisateur désigné n'est pas un enseignant."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Block duplicates (subject already in classroom)
        if classroom.subjects.filter(subject=serializer.validated_data['subject']).exists():
            return Response({'detail': "Cette matière est déjà dans la classe."},
                            status=status.HTTP_400_BAD_REQUEST)

        cs = serializer.save(classroom=classroom)
        return Response(ClassroomSubjectSerializer(cs, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path=r'subjects/(?P<sub_id>\d+)')
    def remove_subject(self, request, pk=None, sub_id=None):
        classroom = self.get_object()
        if classroom.owner_id != request.user.id:
            return Response({'detail': 'Action réservée au propriétaire.'},
                            status=status.HTTP_403_FORBIDDEN)
        deleted, _ = classroom.subjects.filter(id=sub_id).delete()
        if not deleted:
            return Response({'detail': 'Matière introuvable.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='leave')
    def leave(self, request, pk=None):
        classroom = self.get_object()
        if classroom.owner_id == request.user.id:
            return Response({'detail': "Le propriétaire ne peut pas quitter sa propre classe."},
                            status=status.HTTP_400_BAD_REQUEST)
        ClassroomMembership.objects.filter(classroom=classroom, student=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ────────────────────────────────────────────────────────────────────
# Standalone endpoints
# ────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def join_classroom(request):
    """Body: { code: 'ABCDEF' }"""
    code = (request.data.get('code') or '').strip().upper()
    if not code:
        return Response({'detail': 'Code requis.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        classroom = Classroom.objects.get(join_code=code)
    except Classroom.DoesNotExist:
        return Response({'detail': 'Code invalide.'}, status=status.HTTP_404_NOT_FOUND)

    if classroom.owner_id == request.user.id:
        return Response({'detail': "Tu es déjà propriétaire de cette classe."},
                        status=status.HTTP_400_BAD_REQUEST)

    membership, created = ClassroomMembership.objects.get_or_create(
        classroom=classroom, student=request.user
    )
    serializer = ClassroomSerializer(classroom, context={'request': request})
    return Response(
        serializer.data,
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


# ────────────────────────────────────────────────────────────────────
# Weekly progress vs classroom average
# ────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def weekly_progress(request):
    """
    For the requesting student: return 8 weeks of data.
    Each point = % of started exercises (Complete entries) marked 'success'
    in that week.
    Compared against the average of the same metric across all students
    in the same classroom(s).
    Optional ?classroom_id=<id> to scope to one classroom.

    Response:
    {
      "labels": ["S-7", "S-6", ..., "S0"],
      "you":    [62, 71, 58, 80, 74, 88, 91, 83],
      "average":[55, 60, 62, 65, 66, 68, 70, 71],
      "classroom": { "id": 12, "name": "..." } | null,
      "has_classroom": true
    }
    """
    user = request.user
    classroom_id = request.query_params.get('classroom_id')

    # Determine peer student set
    classroom = None
    if classroom_id:
        try:
            classroom = Classroom.objects.get(pk=classroom_id)
        except Classroom.DoesNotExist:
            return Response({'detail': 'Classe introuvable.'}, status=status.HTTP_404_NOT_FOUND)
        # Must be owner or member
        is_member = classroom.memberships.filter(student=user).exists()
        if not (classroom.owner_id == user.id or is_member):
            return Response({'detail': 'Accès refusé.'}, status=status.HTTP_403_FORBIDDEN)
        peer_user_ids = list(classroom.memberships.values_list('student_id', flat=True))
    else:
        # Default: union of all classrooms the user is in (as student)
        memberships = ClassroomMembership.objects.filter(student=user).select_related('classroom')
        if not memberships.exists():
            return Response({
                'labels': [],
                'you': [],
                'average': [],
                'classroom': None,
                'has_classroom': False,
            })
        # Pick first classroom for naming context
        classroom = memberships.first().classroom
        classroom_ids = list(memberships.values_list('classroom_id', flat=True))
        peer_user_ids = list(
            ClassroomMembership.objects
            .filter(classroom_id__in=classroom_ids)
            .values_list('student_id', flat=True)
            .distinct()
        )

    # Always include the requesting user in the peer set so the average
    # makes sense even in a classroom of one.
    if user.id not in peer_user_ids:
        peer_user_ids.append(user.id)

    # Build week buckets (last 8 weeks ending today)
    now = timezone.now()
    weeks = []
    for i in range(7, -1, -1):
        end = now - timedelta(days=i * 7)
        start = end - timedelta(days=7)
        weeks.append((start, end, f"S-{i}" if i > 0 else "S0"))

    content_ct = ContentType.objects.get_for_model(Content)
    exercise_ids = Content.objects.filter(type='exercise').values_list('id', flat=True)

    def success_rate(user_ids, start, end):
        qs = Complete.objects.filter(
            user_id__in=user_ids,
            content_type=content_ct,
            object_id__in=exercise_ids,
            updated_at__gte=start,
            updated_at__lt=end,
        )
        total = qs.count()
        if total == 0:
            return 0
        success = qs.filter(status='success').count()
        return round(success * 100 / total)

    labels = []
    you = []
    average = []
    for start, end, label in weeks:
        labels.append(label)
        you.append(success_rate([user.id], start, end))
        average.append(success_rate(peer_user_ids, start, end))

    return Response({
        'labels': labels,
        'you': you,
        'average': average,
        'classroom': {
            'id': classroom.id,
            'name': classroom.name,
        } if classroom else None,
        'has_classroom': True,
    })


# ────────────────────────────────────────────────────────────────────
# TDList ViewSet (nested under classroom)
# ────────────────────────────────────────────────────────────────────

class TDListViewSet(viewsets.ModelViewSet):
    """
    Endpoints (mounted at /api/classrooms/<classroom_pk>/td-lists/):
        GET    /                          list TD lists for the classroom (must be member or owner)
        POST   /                          owner creates a TD list
        GET    /<pk>/                     retrieve
        PATCH  /<pk>/                     owner updates
        DELETE /<pk>/                     owner deletes
        POST   /<pk>/items/               owner adds item   body: {content_id}
        DELETE /<pk>/items/<item_id>/     owner removes item
    """
    serializer_class = TDListSerializer
    permission_classes = [IsAuthenticated]

    def _get_classroom(self):
        classroom = get_object_or_404(Classroom, pk=self.kwargs['classroom_pk'])
        # Must be owner or member
        is_member = classroom.memberships.filter(student=self.request.user).exists()
        if classroom.owner_id != self.request.user.id and not is_member:
            self.permission_denied(self.request, message='Accès refusé.')
        return classroom

    def get_queryset(self):
        classroom = self._get_classroom()
        return classroom.td_lists.select_related('subject', 'created_by').prefetch_related('items', 'items__content').order_by('-created_at')

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

    def perform_create(self, serializer):
        classroom = self._get_classroom()
        if classroom.owner_id != self.request.user.id:
            raise PermissionError("Seul le propriétaire de la classe peut créer un TD.")
        serializer.save(classroom=classroom, created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except PermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.classroom.owner_id != request.user.id:
            return Response({'detail': "Action réservée au propriétaire."},
                            status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.classroom.owner_id != request.user.id:
            return Response({'detail': "Action réservée au propriétaire."},
                            status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'], url_path='items')
    def add_item(self, request, classroom_pk=None, pk=None):
        td_list = self.get_object()
        if td_list.classroom.owner_id != request.user.id:
            return Response({'detail': "Action réservée au propriétaire."},
                            status=status.HTTP_403_FORBIDDEN)

        # Default position to end of list
        next_pos = (td_list.items.aggregate(m=Count('id'))['m'] or 0)
        data = dict(request.data)
        data.setdefault('position', next_pos)

        serializer = TDListItemSerializer(data=data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        # Refuse non-exercise content (TDs are exercises only)
        if serializer.validated_data['content'].type != 'exercise':
            return Response({'detail': 'Seuls les exercices peuvent être ajoutés à un TD.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if td_list.items.filter(content=serializer.validated_data['content']).exists():
            return Response({'detail': 'Cet exercice est déjà dans le TD.'},
                            status=status.HTTP_400_BAD_REQUEST)

        item = serializer.save(td_list=td_list)
        return Response(TDListItemSerializer(item, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path=r'items/(?P<item_id>\d+)')
    def remove_item(self, request, classroom_pk=None, pk=None, item_id=None):
        td_list = self.get_object()
        if td_list.classroom.owner_id != request.user.id:
            return Response({'detail': "Action réservée au propriétaire."},
                            status=status.HTTP_403_FORBIDDEN)
        deleted, _ = td_list.items.filter(id=item_id).delete()
        if not deleted:
            return Response({'detail': 'Élément introuvable.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ────────────────────────────────────────────────────────────────────
# FIFA-style skill stats per student per subject
# ────────────────────────────────────────────────────────────────────

# Difficulty weights for the "Difficulté" axis
DIFFICULTY_SCORE = {'hard': 100, 'medium': 66, 'easy': 33}

# Caps used to normalize raw counts/durations to a 0-100 score
PERSEVERANCE_CAP = 50           # 50 successful exercises = max
ENGAGEMENT_MIN_CAP = 600 * 60   # 10 hours = max
SPEED_REFERENCE_SECONDS = 25 * 60  # 25 min per exercise = baseline (lower is faster)


def _compute_skill_axes(user_id: int, subject_id, weeks: int = 8) -> dict:
    """Compute the 6 FIFA-style skill axes (0-100) for a user, scoped to a subject if given."""
    now = timezone.now()
    cutoff = now - timedelta(weeks=weeks)

    content_ct = ContentType.objects.get_for_model(Content)

    # Exercises in the (subject) scope
    content_qs = Content.objects.filter(type='exercise')
    if subject_id:
        content_qs = content_qs.filter(subject_id=subject_id)
    content_ids = list(content_qs.values_list('id', flat=True))
    content_id_strs = [str(i) for i in content_ids]

    if not content_ids:
        return {
            'precision': 0, 'regularite': 0, 'vitesse': 0,
            'difficulte': 0, 'perseverance': 0, 'engagement': 0,
        }

    # User's Complete entries in scope
    completes = Complete.objects.filter(
        user_id=user_id,
        content_type=content_ct,
        object_id__in=content_id_strs,
    )
    total = completes.count()
    success_qs = completes.filter(status='success')
    success_count = success_qs.count()

    # Précision
    precision = round(success_count * 100 / total) if total else 0

    # Régularité — active weeks (week with ≥1 success) / weeks window
    active_weeks = 0
    for i in range(weeks):
        end = now - timedelta(days=i * 7)
        start = end - timedelta(days=7)
        if success_qs.filter(updated_at__gte=start, updated_at__lt=end).exists():
            active_weeks += 1
    regularite = round(active_weeks * 100 / weeks)

    # Vitesse — average StudyTimeTracker per successful exercise. Lower is better.
    success_obj_ids = list(success_qs.values_list('object_id', flat=True))
    avg_seconds = 0
    if success_obj_ids:
        time_qs = StudyTimeTracker.objects.filter(
            user_id=user_id,
            content_type=content_ct,
            object_id__in=[int(i) for i in success_obj_ids if i.isdigit()],
        )
        agg = time_qs.aggregate(total=Sum('time_spent_seconds'), n=Count('id'))
        if agg['n']:
            avg_seconds = (agg['total'] or 0) / agg['n']
    if avg_seconds <= 0:
        vitesse = 50 if success_count > 0 else 0  # neutral if no time data
    else:
        # 0s → 100, SPEED_REFERENCE → 50, 2*ref → ~0
        ratio = SPEED_REFERENCE_SECONDS / max(avg_seconds, 1)
        vitesse = max(0, min(100, round(ratio * 50)))

    # Difficulté — weighted avg of difficulty of successful exercises
    if success_obj_ids:
        diffs = (
            Content.objects
            .filter(id__in=[int(i) for i in success_obj_ids if i.isdigit()])
            .values_list('difficulty', flat=True)
        )
        scored = [DIFFICULTY_SCORE.get(d or 'easy', 33) for d in diffs]
        difficulte = round(sum(scored) / len(scored)) if scored else 0
    else:
        difficulte = 0

    # Persévérance — successful exercises capped
    perseverance = min(100, round(success_count * 100 / PERSEVERANCE_CAP))

    # Engagement — total study time spent on subject
    eng_qs = StudyTimeTracker.objects.filter(
        user_id=user_id,
        content_type=content_ct,
        object_id__in=[i for i in content_ids],  # int ids, StudyTimeTracker.object_id is int
        recorded_at__gte=cutoff,
    )
    total_seconds = eng_qs.aggregate(t=Sum('time_spent_seconds'))['t'] or 0
    engagement = min(100, round(total_seconds * 100 / ENGAGEMENT_MIN_CAP))

    return {
        'precision': precision,
        'regularite': regularite,
        'vitesse': vitesse,
        'difficulte': difficulte,
        'perseverance': perseverance,
        'engagement': engagement,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def classroom_student_stats(request, pk):
    """
    GET /api/classrooms/<pk>/student-stats/?student_id=<id>&subject_id=<id>

    Returns FIFA-style skill stats for one student, scoped to a subject.
    Caller must be the classroom owner or the student themselves.
    Defaults to request.user if no student_id given.
    Defaults to overall (no subject) if no subject_id given.
    """
    classroom = get_object_or_404(Classroom, pk=pk)
    is_member = classroom.memberships.filter(student=request.user).exists()
    if classroom.owner_id != request.user.id and not is_member:
        return Response({'detail': 'Accès refusé.'}, status=status.HTTP_403_FORBIDDEN)

    student_id = request.query_params.get('student_id')
    if student_id:
        student_id = int(student_id)
        if classroom.owner_id != request.user.id and student_id != request.user.id:
            return Response({'detail': 'Accès refusé.'}, status=status.HTTP_403_FORBIDDEN)
    else:
        student_id = request.user.id

    subject_id = request.query_params.get('subject_id')
    subject_id = int(subject_id) if subject_id else None

    axes = _compute_skill_axes(student_id, subject_id)

    # Overall = arithmetic mean rounded
    overall = round(sum(axes.values()) / len(axes)) if axes else 0

    # Subject context
    subject_payload = None
    if subject_id:
        try:
            s = Subject.objects.get(pk=subject_id)
            subject_payload = {'id': s.id, 'name': s.name}
        except Subject.DoesNotExist:
            pass

    student = User.objects.get(pk=student_id)
    return Response({
        'student': {'id': student.id, 'username': student.username},
        'subject': subject_payload,
        'axes': axes,
        'overall': overall,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def classroom_roster_stats(request, pk):
    """
    GET /api/classrooms/<pk>/roster-stats/?subject_id=<id>

    Returns one summary card per student (overall score + axes) scoped to a subject.
    Owner-or-member only.
    """
    classroom = get_object_or_404(Classroom, pk=pk)
    is_member = classroom.memberships.filter(student=request.user).exists()
    if classroom.owner_id != request.user.id and not is_member:
        return Response({'detail': 'Accès refusé.'}, status=status.HTTP_403_FORBIDDEN)

    subject_id = request.query_params.get('subject_id')
    subject_id = int(subject_id) if subject_id else None

    members = (
        ClassroomMembership.objects
        .filter(classroom=classroom)
        .select_related('student', 'student__profile')
        .order_by('student__username')
    )
    cards = []
    for m in members:
        axes = _compute_skill_axes(m.student_id, subject_id)
        overall = round(sum(axes.values()) / len(axes)) if axes else 0
        prof = getattr(m.student, 'profile', None)
        avatar = None
        if prof:
            if prof.avatar_file:
                avatar = request.build_absolute_uri(prof.avatar_file.url)
            else:
                avatar = prof.avatar_url
        cards.append({
            'student': {
                'id': m.student.id,
                'username': m.student.username,
                'avatar': avatar,
            },
            'overall': overall,
            'axes': axes,
        })

    return Response({
        'classroom_id': classroom.id,
        'subject_id': subject_id,
        'students': cards,
    })
