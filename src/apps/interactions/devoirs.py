"""« Mon prochain DS » (08/10/2026) : /api/devoirs/ — devoirs annoncés, plan de révision, DS blanc.

L'élève annonce son devoir : matière, date, chapitres au programme. Le plan, recalculé à chaque visite :
- les chapitres du DS, les plus fragiles d'abord, avec la même maîtrise que « Ma progression »
  (users/progression.py) : théorèmes à renforcer, contenus à revoir, quiz Skill IQ ;
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
# États de « Ma progression » (apps/users/maitrise.py) : les plus à travailler d'abord, comme sur la page.
ETAT_RANK = {'a_renforcer': 0, 'a_consolider': 0, 'bonne_voie': 3, 'maitrise': 4}
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


def _forget_maitrise(user):
    """Un DS annoncé oriente l'objectif de « Ma progression » (apps/users/objectif.py) : recalcul."""
    from apps.users.maitrise import forget
    forget(user.id)


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


def _for_you(user, chapter_ids, names, difficulties=None, limit=FOR_YOU, level=None, exclude_seen=False,
             prefer_ids=(), only_ids=None, exclude_ids=(), soon_ids=()):
    """Exercices « Pour toi » des chapitres (plan d'un DS, objectif de « Ma progression »), jamais ceux déjà réussis.
    difficulties : difficultés voulues, dans l'ordre de préférence (les autres viennent après) ; level : ceux du niveau
    s'il en a ; exclude_seen : seulement des exercices jamais ouverts ni évalués (vérification « sur d'autres
    questions ») ; prefer_ids : en premier (les « à revoir ») ; only_ids : parmi ceux-là (un théorème à travailler) ;
    soon_ids : à difficulté égale, ceux-là d'abord (les théorèmes les moins réussis)."""
    from apps.things import for_you
    likes = Count('votes', filter=Q(votes__value=Vote.UP), distinct=True)
    dislikes = Count('votes', filter=Q(votes__value=Vote.DOWN), distinct=True)
    base = _exercises_in(chapter_ids).exclude(id__in=list(exclude_ids))
    if level is not None and base.filter(class_levels=level).exists():
        base = base.filter(class_levels=level)
    if only_ids is not None:
        base = base.filter(id__in=list(only_ids))
    qs = base.annotate(like_count_annotation=likes, dislike_count_annotation=dislikes)
    ranked = for_you.rank(qs, user)
    status_of = _statuses(user, [cid for cid, _ in ranked])
    skip = {'success', 'review', 'seen'} if exclude_seen else {'success'}
    ranked = [(cid, label) for cid, label in ranked if status_of.get(cid) not in skip]
    soon = set(soon_ids)
    if difficulties:
        level_of = dict(base.filter(id__in=[cid for cid, _ in ranked]).values_list('id', 'difficulty'))
        order = {d: i for i, d in enumerate(difficulties)}
        ranked.sort(key=lambda x: (order.get(level_of.get(x[0]), len(order)), x[0] not in soon))
    elif soon:
        ranked.sort(key=lambda x: x[0] not in soon)
    if prefer_ids:
        first = {cid: i for i, cid in enumerate(prefer_ids)}
        ranked.sort(key=lambda x: first.get(x[0], len(first)))
    picked = ranked[:limit]
    contents = {c.id: c for c in base.filter(id__in=[cid for cid, _ in picked])}
    chapters_of = _chapter_ids_of([cid for cid, _ in picked])
    rows = []
    for cid, label in picked:
        c = contents.get(cid)
        if not c:
            continue
        chapter = next((names[ch] for ch in chapters_of.get(cid, []) if ch in names), None)
        rows.append({'id': c.id, 'title': c.title, 'difficulty': c.difficulty, 'chapter': chapter,
                     'status': status_of.get(cid), 'reason': label, 'minutes': _minutes(c),
                     'url': f'/exercises/{c.id}'})
    return rows


MOCK_MINUTES = (30, 60, 90, 120)      # durées proposées pour le DS blanc
MOCK_DIFFICULTIES = ('', 'easy', 'medium', 'hard')  # '' : mélangée (plutôt moyen, comme un vrai DS)
MOCK_MIN_QUESTIONS = 3                 # DS blanc : seulement des exercices « longs » (3 questions au moins)
MOCK_MAX_EXERCISES = 6


def _question_count(content):
    """Questions d'un exercice : chaque sous-question compte (1. a) b) c) = 3), une question seule aussi."""
    return sum(len(b.get('subQuestions') or []) or 1
               for b in (content.json_content or {}).get('blocks', []) if b.get('type') == 'question')


def _pick_mock(user, ordered_chapter_ids, level, exclude=(), minutes=60, difficulty=''):
    """DS blanc : des exercices d'au moins 3 questions, pris chapitre après chapitre (le plus fragile d'abord)
    jusqu'à remplir la durée choisie. → (ids, difficulté respectée ?)

    Dans un chapitre : pas encore ouvert > ouvert > à revoir ; la difficulté choisie (sinon moyen > difficile >
    facile) ; du niveau de l'élève ; puis le plus apprécié. Ce qu'il a réussi ne vient qu'en dernier recours."""
    qs = _exercises_in(ordered_chapter_ids).exclude(id__in=list(exclude))
    if level is not None and qs.filter(class_levels=level).exists():
        qs = qs.filter(class_levels=level)
    contents = {c.id: c for c in qs if _question_count(c) >= MOCK_MIN_QUESTIONS}
    respected = True
    if difficulty:
        same = {i: c for i, c in contents.items() if c.difficulty == difficulty}
        if same:
            contents = same
        else:
            respected = False  # aucun exercice long de cette difficulté : on garde les autres, et on le dit
    likes = dict(_likes(contents))
    status_of = _statuses(user, list(contents))
    chapters_of = _chapter_ids_of(list(contents))
    seen_rank = {None: 0, 'seen': 1, 'review': 2, 'success': 9}

    def key(c):
        return (seen_rank[status_of.get(c.id)], DIFFICULTY_RANK.get(c.difficulty, 1), -likes.get(c.id, 0), -c.id)

    picked, total = [], 0
    # Tours successifs : le meilleur exercice de chaque chapitre, tant que la durée n'est pas atteinte. S'il
    # ferait dépasser de plus de 10 minutes, le chapitre passe son tour (pas de repli sur un exercice moins
    # pertinent, déjà réussi par exemple) ; il en faut au moins un.
    for _ in range(MOCK_MAX_EXERCISES):
        added = False
        for ch in ordered_chapter_ids:
            if len(picked) >= MOCK_MAX_EXERCISES or total >= minutes:
                break
            pool = sorted((c for c in contents.values() if ch in chapters_of.get(c.id, []) and c.id not in picked), key=key)
            if not pool:
                continue
            m = _minutes(pool[0])
            if not picked or total + m <= minutes + 10:
                picked.append(pool[0].id)
                total += m
                added = True
        if not added or total >= minutes:
            break
    return picked, respected


def _likes(contents):
    """{id: nombre de « j'aime »} des exercices candidats."""
    from apps.things.models import Content
    return Content.objects.filter(id__in=list(contents)).annotate(
        n=Count('votes', filter=Q(votes__value=Vote.UP), distinct=True)).values_list('id', 'n')


def _mock_payload(test, user, names, ordered_ids, with_structure=False):
    from apps.things.models import Content
    respected = True
    if test.mock_ids:
        ids = list(test.mock_ids)
    else:
        ids, respected = _pick_mock(user, ordered_ids, _level(user, test),
                                    minutes=test.mock_minutes, difficulty=test.mock_difficulty)
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
        # Réglages de l'élève, et si la difficulté choisie a pu être tenue (sinon : pas assez d'exercices longs).
        'settings': {'minutes': test.mock_minutes, 'difficulty': test.mock_difficulty, 'choices': list(MOCK_MINUTES)},
        'difficulty_respected': respected,
        'min_questions': MOCK_MIN_QUESTIONS,
    }


def _ordered_chapters(test, user):
    """Entrées « chapitre » de Ma progression pour les chapitres du DS, les plus fragiles d'abord."""
    from apps.users.progression import chapter_progress
    chapters = list(test.chapters.select_related('subfield'))
    entries = chapter_progress(user, chapters, _level(user, test))
    entries.sort(key=lambda c: (_rank(c), c['mastery'] if c['mastery'] is not None else 101, c['name']))
    return entries


def _rank(c):
    """Rang d'un chapitre du DS : l'état de « Ma progression » ; pas encore évalué (moins de 4 questions) : l'ancien
    état, qui distingue déjà « 3 questions ratées » de « 3 questions réussies »."""
    etat = c.get('etat')
    if etat and etat != 'non_evalue':
        return ETAT_RANK.get(etat, 2)
    return STATUS_RANK.get(c['status'], 2)


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
        _forget_maitrise(user)

    def perform_update(self, serializer):
        # Chapitres changés : le DS blanc tiré pour les anciens chapitres ne vaut plus.
        if 'chapters' in serializer.validated_data:
            serializer.save(mock_ids=[], mock_started_at=None, mock_done_at=None, mock_seconds=None)
        else:
            serializer.save()
        _forget_maitrise(self.request.user)

    def perform_destroy(self, instance):
        instance.delete()
        _forget_maitrise(self.request.user)

    @action(detail=False, methods=['get'], url_path='prochain')
    def prochain(self, request):
        """Rappel de l'accueil : le prochain DS dans les deux semaines (ou rien)."""
        today = timezone.localdate()
        test = self.get_queryset().filter(date__gte=today, date__lte=today + timedelta(days=SOON_DAYS)).order_by('date', 'id').first()
        return Response({'test': self.get_serializer(test).data if test else None})

    @action(detail=True, methods=['get'])
    def plan(self, request, pk=None):
        """Plan de révision. Chaque chapitre porte `hub_url` (users/progression.py) : sa page d'exercices
        au niveau de l'élève, où mène « S'entraîner »."""
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
        finish (seconds), new (en tirer un autre, sans reprendre les mêmes exercices), settings (minutes,
        difficulty : enregistre les réglages et tire un nouveau DS blanc)."""
        test = self.get_object()
        entries = _ordered_chapters(test, request.user)
        names = {c['id']: c['name'] for c in entries}
        ordered_ids = [c['id'] for c in entries]
        if request.method == 'POST':
            what = request.data.get('action')
            now = timezone.now()
            if what == 'start':
                if not test.mock_ids:
                    test.mock_ids, _ = _pick_mock(request.user, ordered_ids, _level(request.user, test),
                                                  minutes=test.mock_minutes, difficulty=test.mock_difficulty)
                if not test.mock_ids:
                    return Response({'error': 'Pas encore d’exercices assez longs (3 questions au moins) dans ces chapitres.'},
                                    status=status.HTTP_400_BAD_REQUEST)
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
                _forget_maitrise(request.user)
            elif what == 'new':
                previous = list(test.mock_ids)
                test.mock_ids = _pick_mock(request.user, ordered_ids, _level(request.user, test), exclude=previous,
                                           minutes=test.mock_minutes, difficulty=test.mock_difficulty)[0] or previous
                test.mock_started_at = test.mock_done_at = test.mock_seconds = None
                test.save(update_fields=['mock_ids', 'mock_started_at', 'mock_done_at', 'mock_seconds', 'updated_at'])
            elif what == 'settings':
                try:
                    minutes = int(request.data.get('minutes', test.mock_minutes))
                except (TypeError, ValueError):
                    minutes = -1
                difficulty = request.data.get('difficulty', test.mock_difficulty) or ''
                if minutes not in MOCK_MINUTES or difficulty not in MOCK_DIFFICULTIES:
                    return Response({'error': f'minutes : {list(MOCK_MINUTES)} ; difficulty : easy, medium, hard ou vide.'},
                                    status=status.HTTP_400_BAD_REQUEST)
                test.mock_minutes, test.mock_difficulty = minutes, difficulty
                # Nouveaux réglages : un nouveau DS blanc (celui tiré pour les anciens réglages ne vaut plus).
                test.mock_ids, test.mock_started_at, test.mock_done_at, test.mock_seconds = [], None, None, None
                test.save(update_fields=['mock_minutes', 'mock_difficulty', 'mock_ids', 'mock_started_at',
                                         'mock_done_at', 'mock_seconds', 'updated_at'])
            else:
                return Response({'error': 'action : start, finish, new ou settings.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'test': self.get_serializer(test).data,
            **_mock_payload(test, request.user, names, ordered_ids, with_structure=True),
        })
