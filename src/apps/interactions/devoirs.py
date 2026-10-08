"""« Mon prochain DS » (08/10/2026) : /api/devoirs/ — devoirs annoncés, plan de révision, DS blanc.

L'élève annonce son devoir : matière, date, chapitres au programme. Le plan, recalculé à chaque visite :
- les chapitres du DS, les plus fragiles d'abord, avec la même maîtrise que « Ma progression »
  (users/progression.py) : notions à renforcer, contenus à revoir, quiz Skill IQ ;
- des exercices « Pour toi » de ces chapitres (things/for_you.py), jamais ceux déjà réussis ;
- un DS blanc : 2 ou 3 exercices de ces chapitres, un par chapitre en commençant par le plus fragile,
  pas encore ouverts de préférence, avec une durée (temps cible des questions, sinon la difficulté) ;
- la préparation depuis l'annonce : exercices travaillés, quiz passés, DS blanc fait.
La date passée, l'élève note sa note (sur 20).
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.caracteristics.models import Chapter, ClassLevel, Subject

from .models import Complete, QuestionProgress, UpcomingTest, Vote

MAX_TESTS = 100        # par élève (garde-fou)
MAX_CHAPTERS = 12
SOON_DAYS = 14         # rappel sur l'accueil : le prochain DS dans les 2 semaines
FOR_YOU = 6            # exercices proposés
STATUS_RANK = {'weak': 0, 'todo': 1, 'started': 2, 'good': 3, 'mastered': 4}
MINUTES = {'easy': 15, 'medium': 20, 'hard': 30}   # durée d'un exercice sans temps cible
DIFFICULTY_RANK = {'medium': 0, 'hard': 1, 'easy': 2}  # DS blanc : comme en vrai, plutôt moyen


def _level(user, test=None):
    if test is not None and test.class_level_id:
        return test.class_level
    return getattr(getattr(user, 'profile', None), 'class_level', None)


class _Ref(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class UpcomingTestSerializer(serializers.ModelSerializer):
    subject = _Ref(read_only=True)
    chapters = _Ref(many=True, read_only=True)
    subject_id = serializers.PrimaryKeyRelatedField(source='subject', queryset=Subject.objects.all(),
                                                    write_only=True, required=False, allow_null=True)
    class_level_id = serializers.PrimaryKeyRelatedField(source='class_level', queryset=ClassLevel.objects.all(),
                                                        write_only=True, required=False, allow_null=True)
    chapter_ids = serializers.PrimaryKeyRelatedField(source='chapters', queryset=Chapter.objects.all(),
                                                     many=True, write_only=True)
    days_left = serializers.SerializerMethodField()
    grade = serializers.DecimalField(max_digits=4, decimal_places=2, required=False, allow_null=True,
                                     min_value=Decimal('0'), max_value=Decimal('20'), coerce_to_string=False)

    class Meta:
        model = UpcomingTest
        fields = ['id', 'kind', 'subject', 'subject_id', 'class_level_id', 'chapters', 'chapter_ids', 'date',
                  'days_left', 'grade', 'mock_done_at', 'mock_seconds', 'created_at']
        read_only_fields = ['mock_done_at', 'mock_seconds', 'created_at']

    def get_days_left(self, obj):
        return (obj.date - timezone.localdate()).days

    def validate_chapter_ids(self, value):
        if not value:
            raise serializers.ValidationError('Choisis au moins un chapitre.')
        if len(value) > MAX_CHAPTERS:
            raise serializers.ValidationError(f'{MAX_CHAPTERS} chapitres au plus.')
        return value

    def validate_date(self, value):
        today = timezone.localdate()
        if not (today - timedelta(days=366) <= value <= today + timedelta(days=366)):
            raise serializers.ValidationError('Date hors de l’année scolaire.')
        return value

    def validate(self, attrs):
        subject = attrs.get('subject', getattr(self.instance, 'subject', None))
        chapters = attrs.get('chapters')
        if subject and chapters and any(c.subject_id and c.subject_id != subject.id for c in chapters):
            raise serializers.ValidationError({'chapter_ids': 'Ces chapitres ne sont pas tous de cette matière.'})
        return attrs


# ── Plan de révision ─────────────────────────────────────────────────────────────

def _chapter_ids_of(content_ids):
    from apps.things.models import Content
    out = {}
    for cid, ch in Content.chapters.through.objects.filter(content_id__in=content_ids).values_list('content_id', 'chapter_id'):
        out.setdefault(cid, []).append(ch)
    return out


def _exercises_in(chapter_ids):
    from apps.things.models import Content
    ids = Content.chapters.through.objects.filter(chapter_id__in=chapter_ids).values('content_id')
    return Content.objects.filter(id__in=ids, type='exercise')


def _statuses(user, ids):
    """Statut de chaque contenu pour l'élève : 'success', 'review', 'seen' (ouvert ou évalué en partie)."""
    from apps.things.models import Content
    from apps.users.models import ViewHistory
    ct = ContentType.objects.get_for_model(Content)
    out = {}
    for oid in ViewHistory.objects.filter(user=user, content_type=ct, object_id__in=ids).values_list('object_id', flat=True):
        out[oid] = 'seen'
    for oid in QuestionProgress.objects.filter(user=user, content_type=ct, object_id__in=ids).values_list('object_id', flat=True):
        out[oid] = 'seen'
    for oid, st in Complete.objects.filter(user=user, content_type=ct, object_id__in=[str(i) for i in ids]).values_list('object_id', 'status'):
        if str(oid).isdigit() and st in ('success', 'review'):
            out[int(oid)] = st
    return out


def _minutes(content):
    """Durée d'un exercice : temps cible de ses questions, sinon selon sa difficulté (multiple de 5)."""
    seconds = 0
    for block in (content.json_content or {}).get('blocks', []):
        if block.get('type') != 'question':
            continue
        for q in (block.get('subQuestions') or [block]):
            seconds += (q.get('meta') or {}).get('expected_seconds') or 0
    if seconds:
        return max(5, int(round(seconds / 300.0)) * 5)
    return MINUTES.get(content.difficulty, 20)


def _for_you(user, chapter_ids, names):
    """Exercices « Pour toi » des chapitres du DS, jamais ceux déjà réussis."""
    from apps.things import for_you
    likes = Count('votes', filter=Q(votes__value=Vote.UP), distinct=True)
    dislikes = Count('votes', filter=Q(votes__value=Vote.DOWN), distinct=True)
    qs = _exercises_in(chapter_ids).annotate(like_count_annotation=likes, dislike_count_annotation=dislikes)
    ranked = for_you.rank(qs, user)
    status_of = _statuses(user, [cid for cid, _ in ranked])
    picked = [(cid, label) for cid, label in ranked if status_of.get(cid) != 'success'][:FOR_YOU]
    contents = {c.id: c for c in _exercises_in(chapter_ids).filter(id__in=[cid for cid, _ in picked])}
    chapters_of = _chapter_ids_of([cid for cid, _ in picked])
    rows = []
    for cid, label in picked:
        c = contents.get(cid)
        if not c:
            continue
        chapter = next((names[ch] for ch in chapters_of.get(cid, []) if ch in names), None)
        rows.append({'id': c.id, 'title': c.title, 'difficulty': c.difficulty, 'chapter': chapter,
                     'status': status_of.get(cid), 'reason': label, 'minutes': _minutes(c)})
    return rows


def _pick_mock(user, ordered_chapter_ids, level, exclude=()):
    """DS blanc : un exercice par chapitre (le plus fragile d'abord), 2 ou 3 en tout.

    Pas encore ouvert > ouvert > à revoir ; moyen > difficile > facile ; du niveau de l'élève ;
    puis le plus apprécié. Ce qu'il a réussi ne vient qu'en dernier recours."""
    want = min(3, max(2, len(ordered_chapter_ids)))
    qs = _exercises_in(ordered_chapter_ids).exclude(id__in=list(exclude))
    if level is not None and qs.filter(class_levels=level).count() >= want:
        qs = qs.filter(class_levels=level)
    likes = dict(qs.annotate(n=Count('votes', filter=Q(votes__value=Vote.UP), distinct=True)).values_list('id', 'n'))
    contents = {c.id: c for c in qs}
    status_of = _statuses(user, list(contents))
    chapters_of = _chapter_ids_of(list(contents))
    seen_rank = {None: 0, 'seen': 1, 'review': 2, 'success': 9}

    def key(c):
        return (seen_rank[status_of.get(c.id)], DIFFICULTY_RANK.get(c.difficulty, 1), -likes.get(c.id, 0), -c.id)

    picked = []
    for _ in range(want):  # tours successifs : un exercice par chapitre, tant qu'il en manque
        for ch in ordered_chapter_ids:
            if len(picked) == want:
                break
            pool = sorted((c for c in contents.values() if ch in chapters_of.get(c.id, []) and c.id not in picked), key=key)
            if pool:
                picked.append(pool[0].id)
        if len(picked) == want or len(picked) == len(contents):
            break
    return picked


def _mock_payload(test, user, names, ordered_ids, with_structure=False):
    from apps.things.models import Content
    ids = list(test.mock_ids) if test.mock_ids else _pick_mock(user, ordered_ids, _level(user, test))
    contents = {c.id: c for c in Content.objects.filter(id__in=ids)}
    chapters_of = _chapter_ids_of(ids)
    rows = []
    for cid in ids:
        c = contents.get(cid)
        if not c:
            continue
        row = {'id': c.id, 'title': c.title, 'difficulty': c.difficulty, 'minutes': _minutes(c),
               'chapter': next((names[ch] for ch in chapters_of.get(cid, []) if ch in names), None)}
        if with_structure:
            row['structure'] = c.json_content
        rows.append(row)
    return {
        'exercises': rows,
        'minutes': sum(r['minutes'] for r in rows),
        'started_at': test.mock_started_at,
        'done_at': test.mock_done_at,
        'seconds': test.mock_seconds,
    }


def _ordered_chapters(test, user):
    """Entrées « chapitre » de Ma progression pour les chapitres du DS, les plus fragiles d'abord."""
    from apps.users.progression import chapter_progress
    chapters = list(test.chapters.select_related('subfield'))
    entries = chapter_progress(user, chapters, _level(user, test))
    entries.sort(key=lambda c: (STATUS_RANK.get(c['status'], 2), c['mastery'] if c['mastery'] is not None else 101, c['name']))
    return entries


def _readiness(entries):
    known = [c['mastery'] for c in entries if c['mastery'] is not None]
    return round(sum(known) / len(known)) if known else None


def _preparation(test, user, entries):
    """Ce qu'il a fait depuis l'annonce du DS, dans ses chapitres."""
    from apps.skilliq.models import SkillAssessment
    from apps.things.models import Content
    ct = ContentType.objects.get_for_model(Content)
    chapter_ids = [c['id'] for c in entries]
    in_test = set(_exercises_in(chapter_ids).values_list('id', flat=True)) | set(
        Content.objects.filter(type='exam', chapters__in=chapter_ids).values_list('id', flat=True))
    since = test.created_at
    worked = set(QuestionProgress.objects.filter(user=user, content_type=ct, object_id__in=in_test, assessed_at__gte=since)
                 .values_list('object_id', flat=True))
    worked |= {int(o) for o in Complete.objects.filter(user=user, content_type=ct, updated_at__gte=since,
                                                        object_id__in=[str(i) for i in in_test]).values_list('object_id', flat=True)
               if str(o).isdigit()}
    quizzes = set(SkillAssessment.objects.filter(user=user, chapter_id__in=chapter_ids, completed_at__gte=since)
                  .values_list('chapter_id', flat=True))
    with_quiz = [c['id'] for c in entries if c['quiz_ready']]
    return {
        'exercises': len(worked),
        'exercises_goal': max(3, min(2 * len(entries), 8)),
        'quizzes': len([c for c in with_quiz if c in quizzes]),
        'quizzes_total': len(with_quiz),
        'quiz_done': sorted(quizzes),
        'mock': test.mock_done_at is not None,
    }


class UpcomingTestViewSet(viewsets.ModelViewSet):
    """Les DS annoncés de l'élève connecté (les siens seulement)."""
    serializer_class = UpcomingTestSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return (UpcomingTest.objects.filter(user=self.request.user).select_related('subject', 'class_level')
                .prefetch_related(Prefetch('chapters', queryset=Chapter.objects.select_related('subfield'))))

    def list(self, request, *args, **kwargs):
        """À venir (du plus proche au plus lointain), avec la préparation ; puis les passés (récents d'abord)."""
        from apps.users.progression import _chapter_entries, _collect, _per_chapter
        today = timezone.localdate()
        tests = list(self.get_queryset())
        upcoming = [t for t in tests if t.date >= today]
        past = sorted((t for t in tests if t.date < today), key=lambda t: (t.date, t.id), reverse=True)
        data = []
        chap = quizzes = None
        if upcoming:
            d = _collect(request.user)
            chap, _ = _per_chapter(d)
            quizzes = d.quizzes
        for t in upcoming:
            row = self.get_serializer(t).data
            entries = _chapter_entries(list(t.chapters.all()), chap, quizzes, _level(request.user, t))
            row['readiness'] = _readiness(entries)
            row['weak_chapters'] = [c['name'] for c in sorted(entries, key=lambda c: (STATUS_RANK.get(c['status'], 2), c['mastery'] or 0))
                                    if c['status'] in ('weak', 'todo')][:3]
            data.append(row)
        data += [self.get_serializer(t).data for t in past]
        return Response(data)

    def perform_create(self, serializer):
        user = self.request.user
        if UpcomingTest.objects.filter(user=user).count() >= MAX_TESTS:
            raise serializers.ValidationError({'detail': 'Tu as déjà beaucoup de DS enregistrés : supprime les anciens.'})
        level = serializer.validated_data.get('class_level') or _level(user)
        serializer.save(user=user, class_level=level)

    def perform_update(self, serializer):
        # Chapitres changés : le DS blanc tiré pour les anciens chapitres ne vaut plus.
        if 'chapters' in serializer.validated_data:
            serializer.save(mock_ids=[], mock_started_at=None, mock_done_at=None, mock_seconds=None)
        else:
            serializer.save()

    @action(detail=False, methods=['get'], url_path='prochain')
    def prochain(self, request):
        """Rappel de l'accueil : le prochain DS dans les deux semaines (ou rien)."""
        today = timezone.localdate()
        test = self.get_queryset().filter(date__gte=today, date__lte=today + timedelta(days=SOON_DAYS)).order_by('date', 'id').first()
        return Response({'test': self.get_serializer(test).data if test else None})

    @action(detail=True, methods=['get'])
    def plan(self, request, pk=None):
        test = self.get_object()
        entries = _ordered_chapters(test, request.user)
        names = {c['id']: c['name'] for c in entries}
        ordered_ids = [c['id'] for c in entries]
        return Response({
            'test': self.get_serializer(test).data,
            'readiness': _readiness(entries),
            'chapters': entries,
            'exercises': _for_you(request.user, ordered_ids, names) if ordered_ids else [],
            'mock': _mock_payload(test, request.user, names, ordered_ids) if ordered_ids else None,
            'preparation': _preparation(test, request.user, entries),
        })

    @action(detail=True, methods=['get', 'post'], url_path='ds-blanc')
    def ds_blanc(self, request, pk=None):
        """GET : le DS blanc (énoncés compris). POST action=start (fige les exercices et lance l'horloge),
        finish (seconds), new (en tirer un autre, sans reprendre les mêmes exercices)."""
        test = self.get_object()
        entries = _ordered_chapters(test, request.user)
        names = {c['id']: c['name'] for c in entries}
        ordered_ids = [c['id'] for c in entries]
        if request.method == 'POST':
            what = request.data.get('action')
            now = timezone.now()
            if what == 'start':
                if not test.mock_ids:
                    test.mock_ids = _pick_mock(request.user, ordered_ids, _level(request.user, test))
                if not test.mock_ids:
                    return Response({'error': 'Pas encore d’exercices dans ces chapitres.'}, status=status.HTTP_400_BAD_REQUEST)
                if test.mock_started_at is None or test.mock_done_at is not None:
                    test.mock_started_at, test.mock_done_at, test.mock_seconds = now, None, None
                test.save(update_fields=['mock_ids', 'mock_started_at', 'mock_done_at', 'mock_seconds', 'updated_at'])
            elif what == 'finish':
                if test.mock_started_at is None:
                    return Response({'error': 'Le DS blanc n’a pas commencé.'}, status=status.HTTP_400_BAD_REQUEST)
                try:
                    seconds = int(request.data.get('seconds'))
                except (TypeError, ValueError):
                    seconds = int((now - test.mock_started_at).total_seconds())
                test.mock_seconds = max(0, min(seconds, 6 * 3600))
                test.mock_done_at = now
                test.save(update_fields=['mock_seconds', 'mock_done_at', 'updated_at'])
            elif what == 'new':
                previous = list(test.mock_ids)
                test.mock_ids = _pick_mock(request.user, ordered_ids, _level(request.user, test), exclude=previous) or previous
                test.mock_started_at = test.mock_done_at = test.mock_seconds = None
                test.save(update_fields=['mock_ids', 'mock_started_at', 'mock_done_at', 'mock_seconds', 'updated_at'])
            else:
                return Response({'error': 'action : start, finish ou new.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'test': self.get_serializer(test).data,
            **_mock_payload(test, request.user, names, ordered_ids, with_structure=True),
        })
