from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType

from apps.caracteristics.models import Subject, Subfield, Chapter
from apps.uploads.models import FileAttachment
from apps.interactions.models import Save

from .models import (
    ConcoursExam, ConcoursTip, ConcoursComment,
    SimulationSession, SimulationAnswer,
    CONCOURS_TYPE_CHOICES,
)


# -------------------------- helpers --------------------------

class _UserMiniSerializer(serializers.ModelSerializer):
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'avatar')

    def get_avatar(self, obj):
        prof = getattr(obj, 'profile', None)
        if not prof:
            return None
        if prof.avatar_file:
            req = self.context.get('request')
            url = prof.avatar_file.url
            return req.build_absolute_uri(url) if req else url
        return prof.avatar_url


def _request_user(context):
    req = context.get('request')
    return req.user if req and req.user and req.user.is_authenticated else None


# -------------------------- ConcoursExam --------------------------

def _strip_solutions(question: dict) -> dict:
    """Return a copy of a question without correct_key / explanation."""
    return {k: v for k, v in question.items() if k not in ('correct_key', 'explanation')}


class ConcoursExamSerializer(serializers.ModelSerializer):
    """Read serializer — includes JSON structure (with solutions for normal view)."""
    concours_type_display = serializers.CharField(source='get_concours_type_display', read_only=True)
    title = serializers.CharField(read_only=True, source='display_title')
    raw_title = serializers.CharField(source='title', required=False, allow_blank=True)
    structure = serializers.SerializerMethodField()
    question_count = serializers.IntegerField(read_only=True)
    is_saved = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()
    created_by = _UserMiniSerializer(read_only=True)

    class Meta:
        model = ConcoursExam
        fields = (
            'id', 'display_id', 'concours_type', 'concours_type_display',
            'year', 'title', 'raw_title', 'description', 'duration_minutes',
            'created_by', 'created_at', 'updated_at',
            'structure', 'question_count',
            'is_saved', 'comment_count',
        )
        read_only_fields = (
            'id', 'display_id', 'created_by', 'created_at', 'updated_at',
            'concours_type_display', 'title', 'structure', 'question_count',
            'is_saved', 'comment_count',
        )

    def get_structure(self, obj):
        # `hide_solutions=True` in context strips correct_key/explanation.
        s = obj.get_structure()
        if not s:
            return {}
        if self.context.get('hide_solutions'):
            qs = [_strip_solutions(q) for q in s.get('questions', [])]
            return {**s, 'questions': qs}
        return s

    def get_is_saved(self, obj):
        u = _request_user(self.context)
        if not u:
            return False
        ct = ContentType.objects.get_for_model(ConcoursExam)
        return Save.objects.filter(
            user=u, content_type=ct, object_id=str(obj.id)
        ).exists()

    def get_comment_count(self, obj):
        return ConcoursComment.objects.filter(
            target_type=ConcoursComment.TARGET_EXAM, target_id=obj.id
        ).count()


class ConcoursExamListSerializer(serializers.ModelSerializer):
    """Lightweight list serializer — no structure body."""
    concours_type_display = serializers.CharField(source='get_concours_type_display', read_only=True)
    title = serializers.CharField(read_only=True, source='display_title')
    question_count = serializers.IntegerField(read_only=True)
    is_saved = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()

    class Meta:
        model = ConcoursExam
        fields = (
            'id', 'display_id', 'concours_type', 'concours_type_display',
            'year', 'title', 'description', 'duration_minutes',
            'question_count', 'is_saved', 'comment_count',
            'created_at',
        )

    def get_is_saved(self, obj):
        u = _request_user(self.context)
        if not u:
            return False
        ct = ContentType.objects.get_for_model(ConcoursExam)
        return Save.objects.filter(
            user=u, content_type=ct, object_id=str(obj.id)
        ).exists()

    def get_comment_count(self, obj):
        return ConcoursComment.objects.filter(
            target_type=ConcoursComment.TARGET_EXAM, target_id=obj.id
        ).count()


class ConcoursExamWriteSerializer(serializers.ModelSerializer):
    """Used for admin create/update — does NOT touch the Mongo structure
    (separate endpoint handles questions)."""

    class Meta:
        model = ConcoursExam
        fields = (
            'id', 'concours_type', 'year', 'title', 'description',
            'duration_minutes',
        )
        read_only_fields = ('id',)


# -------------------------- ConcoursTip --------------------------

class _FileAttachmentMiniSerializer(serializers.ModelSerializer):
    url = serializers.CharField(read_only=True)

    class Meta:
        model = FileAttachment
        fields = ('id', 'url', 'file_name', 'mime_type', 'file_size', 'file_type')


class ConcoursTipSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    subfield_name = serializers.CharField(source='subfield.name', read_only=True)
    chapter_names = serializers.SerializerMethodField()
    created_by = _UserMiniSerializer(read_only=True)
    video_file = _FileAttachmentMiniSerializer(read_only=True)
    video_file_id = serializers.PrimaryKeyRelatedField(
        queryset=FileAttachment.objects.all(),
        source='video_file', write_only=True, required=False, allow_null=True,
    )
    subject_id = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(), source='subject',
        write_only=True, required=False, allow_null=True,
    )
    subfield_id = serializers.PrimaryKeyRelatedField(
        queryset=Subfield.objects.all(), source='subfield',
        write_only=True, required=False, allow_null=True,
    )
    chapter_ids = serializers.PrimaryKeyRelatedField(
        queryset=Chapter.objects.all(), source='chapters', many=True,
        write_only=True, required=False,
    )

    is_saved = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    vote_count = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()

    class Meta:
        model = ConcoursTip
        fields = (
            'id', 'title', 'description',
            'concours_types',
            'subject', 'subject_id', 'subject_name',
            'subfield', 'subfield_id', 'subfield_name',
            'chapters', 'chapter_ids', 'chapter_names',
            'video_url', 'video_file', 'video_file_id',
            'view_count',
            'created_by', 'created_at', 'updated_at',
            'is_saved', 'user_vote', 'vote_count', 'comment_count',
        )
        read_only_fields = (
            'id', 'created_by', 'created_at', 'updated_at',
            'subject_name', 'subfield_name', 'chapter_names',
            'video_file', 'view_count',
            'is_saved', 'user_vote', 'vote_count', 'comment_count',
            'subject', 'subfield', 'chapters',
        )

    def get_chapter_names(self, obj):
        return [c.name for c in obj.chapters.all()]

    def get_is_saved(self, obj):
        u = _request_user(self.context)
        if not u:
            return False
        ct = ContentType.objects.get_for_model(ConcoursTip)
        return Save.objects.filter(user=u, content_type=ct, object_id=str(obj.id)).exists()

    def get_vote_count(self, obj):
        return obj.votes.filter(value=1).count() - obj.votes.filter(value=-1).count()

    def get_user_vote(self, obj):
        u = _request_user(self.context)
        if not u:
            return 0
        v = obj.votes.filter(user=u).first()
        return v.value if v else 0

    def get_comment_count(self, obj):
        return ConcoursComment.objects.filter(
            target_type=ConcoursComment.TARGET_TIP, target_id=obj.id
        ).count()


# -------------------------- ConcoursComment --------------------------

class ConcoursCommentSerializer(serializers.ModelSerializer):
    author = _UserMiniSerializer(read_only=True)
    vote_count = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()

    class Meta:
        model = ConcoursComment
        fields = (
            'id', 'target_type', 'target_id',
            'author', 'content', 'parent',
            'created_at', 'updated_at',
            'vote_count', 'user_vote', 'replies',
        )
        read_only_fields = ('id', 'author', 'created_at', 'updated_at',
                            'vote_count', 'user_vote', 'replies')

    def get_vote_count(self, obj):
        return obj.votes.filter(value=1).count() - obj.votes.filter(value=-1).count()

    def get_user_vote(self, obj):
        u = _request_user(self.context)
        if not u:
            return 0
        v = obj.votes.filter(user=u).first()
        return v.value if v else 0

    def get_replies(self, obj):
        # Only top-level comments include nested replies (avoid recursion blowups)
        if obj.parent_id is not None:
            return []
        return ConcoursCommentSerializer(
            obj.replies.all().order_by('created_at'),
            many=True, context=self.context,
        ).data


# -------------------------- Simulation --------------------------

class SimulationAnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = SimulationAnswer
        fields = (
            'position', 'chosen_key', 'is_correct',
            'subject_id', 'subfield_id', 'chapter_id', 'tip_id',
            'answered_at',
        )
        read_only_fields = fields


class SimulationSessionListSerializer(serializers.ModelSerializer):
    """Light serializer for the history page."""
    score_percentage = serializers.FloatField(read_only=True)
    concours_type_display = serializers.CharField(source='get_concours_type_display', read_only=True)
    mode_display = serializers.CharField(source='get_mode_display', read_only=True)
    exam_title = serializers.CharField(source='exam.display_title', read_only=True, default=None)

    class Meta:
        model = SimulationSession
        fields = (
            'id', 'mode', 'mode_display',
            'concours_type', 'concours_type_display',
            'exam', 'exam_title',
            'duration_minutes', 'started_at', 'submitted_at', 'status',
            'total_questions', 'correct_count', 'score_percentage',
        )
        read_only_fields = fields


class SimulationSessionDetailSerializer(SimulationSessionListSerializer):
    """Full serializer including questions snapshot + answers."""
    answers = SimulationAnswerSerializer(many=True, read_only=True)
    questions_snapshot = serializers.JSONField(read_only=True)

    class Meta(SimulationSessionListSerializer.Meta):
        fields = SimulationSessionListSerializer.Meta.fields + ('questions_snapshot', 'answers')
