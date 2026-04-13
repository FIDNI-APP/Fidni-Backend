from rest_framework import serializers
from .models import Solution, Comment, Content
from apps.caracteristics.models import ClassLevel, Chapter, Subfield, Theorem, Subject
from apps.users.serializers import UserSerializer
from apps.users.models import ViewHistory
from apps.caracteristics.serializers import ChapterSerializer, ClassLevelSerializer, SubjectSerializer, SubfieldSerializer, TheoremSerializer
from apps.uploads.serializers import FileAttachmentSerializer
from .content_store import get_structure, upsert_structure, get_structures_batch
from .structure_utils import get_total_points, get_item_count, get_section_count
import logging

logger = logging.getLogger('django')


# =====================
# SOLUTION
# =====================

class SolutionSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    vote_count = serializers.IntegerField(read_only=True)
    user_vote = serializers.SerializerMethodField()
    content = serializers.CharField(source='solution_text', required=True, allow_blank=False)

    class Meta:
        model = Solution
        fields = ['id', 'content', 'author', 'created_at', 'updated_at', 'vote_count', 'user_vote']

    def get_user_vote(self, obj):
        user = self.context.get('request').user if self.context.get('request') else None
        if user and user.is_authenticated:
            vote = obj.votes.filter(user=user).first()
            return vote.value if vote else None
        return None


# =====================
# COMMENT
# =====================

class CommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    replies = serializers.SerializerMethodField()
    vote_count = serializers.IntegerField(read_only=True)
    user_vote = serializers.SerializerMethodField()
    attachments = FileAttachmentSerializer(many=True, read_only=True)
    parent_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Comment
        fields = ['id', 'author', 'content', 'created_at', 'replies',
                  'vote_count', 'user_vote', 'parent_id', 'attachments']

    def get_replies(self, obj):
        if obj.replies.exists():
            return CommentSerializer(obj.replies.all(), many=True, context=self.context).data
        return []

    def get_user_vote(self, obj):
        user = self.context.get('request').user if self.context.get('request') else None
        if user and user.is_authenticated:
            vote = obj.votes.filter(user=user).first()
            return vote.value if vote else None
        return None


# =====================
# CONTENT — detail serializer
# =====================

class ContentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    chapters = ChapterSerializer(many=True, read_only=True)
    comments = serializers.SerializerMethodField()
    solution = SolutionSerializer(read_only=True)
    vote_count = serializers.IntegerField(read_only=True)
    user_vote = serializers.SerializerMethodField()
    view_count = serializers.IntegerField(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)
    subject = SubjectSerializer(read_only=True)
    theorems = TheoremSerializer(many=True, read_only=True)
    subfields = SubfieldSerializer(many=True, read_only=True)
    user_save = serializers.SerializerMethodField()
    user_complete = serializers.SerializerMethodField()
    user_timespent = serializers.SerializerMethodField()
    total_points = serializers.IntegerField(read_only=True)
    item_count = serializers.IntegerField(read_only=True)
    section_count = serializers.IntegerField(read_only=True)
    json_content = serializers.JSONField(required=False)

    class Meta:
        model = Content
        fields = [
            'id', 'display_id', 'type', 'title', 'content', 'json_content',
            'difficulty', 'chapters', 'author', 'created_at', 'updated_at',
            'view_count', 'comments', 'solution', 'vote_count', 'user_vote',
            'class_levels', 'subject', 'subfields', 'theorems',
            'user_save', 'user_complete', 'user_timespent',
            'total_points', 'item_count', 'section_count',
            # exam fields
            'is_national_exam', 'national_year', 'duration_minutes',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        json_content = get_structure(instance.type, instance.display_id)
        data['json_content'] = json_content
        data['total_points'] = get_total_points(json_content)
        data['item_count'] = get_item_count(json_content)
        data['section_count'] = get_section_count(json_content)
        return data

    def get_comments(self, obj):
        return CommentSerializer(
            obj.comments.filter(parent=None), many=True, context=self.context
        ).data

    def get_user_vote(self, obj):
        user = self.context.get('request').user if self.context.get('request') else None
        if user and user.is_authenticated:
            vote = obj.votes.filter(user=user).first()
            return vote.value if vote else None
        return None

    def get_user_save(self, obj):
        user = self.context.get('request').user if self.context.get('request') else None
        if user and user.is_authenticated:
            return obj.saved.filter(user=user).exists()
        return False

    def get_user_complete(self, obj):
        user = self.context.get('request').user if self.context.get('request') else None
        if user and user.is_authenticated:
            c = obj.completed.filter(user=user).first()
            return c.status if c else None
        return None

    def get_user_timespent(self, obj):
        user = self.context.get('request').user if self.context.get('request') else None
        if user and user.is_authenticated:
            from django.contrib.contenttypes.models import ContentType
            from apps.interactions.models import StudyTimeTracker
            ct = ContentType.objects.get_for_model(obj)
            tracker = StudyTimeTracker.objects.filter(
                user=user, content_type=ct, object_id=obj.id
            ).first()
            return tracker.time_spent_seconds if tracker else 0
        return 0


# =====================
# CONTENT — list serializer
# =====================

class ContentListSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    subject = SubjectSerializer(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)
    chapters = serializers.SerializerMethodField()
    theorems = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()
    vote_count = serializers.IntegerField(read_only=True)
    user_vote = serializers.SerializerMethodField()
    user_save = serializers.SerializerMethodField()
    user_complete = serializers.SerializerMethodField()
    total_points = serializers.IntegerField(read_only=True)
    item_count = serializers.IntegerField(read_only=True)
    json_content = serializers.JSONField(required=False)

    class Meta:
        model = Content
        fields = [
            'id', 'display_id', 'type', 'title', 'json_content', 'difficulty',
            'author', 'subject', 'class_levels', 'chapters', 'theorems',
            'comment_count', 'created_at', 'view_count', 'vote_count',
            'user_vote', 'user_save', 'user_complete',
            'total_points', 'item_count',
            'is_national_exam', 'national_year', 'duration_minutes',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        mongo_structures = self.context.get('mongo_structures')
        if mongo_structures is not None:
            json_content = mongo_structures.get(instance.display_id, {})
        else:
            json_content = get_structure(instance.type, instance.display_id)
        data['json_content'] = json_content
        data['total_points'] = get_total_points(json_content)
        data['item_count'] = get_item_count(json_content)
        return data

    def get_chapters(self, obj):
        return [{'id': c.id, 'name': c.name} for c in obj.chapters.all()]

    def get_theorems(self, obj):
        return [{'id': t.id, 'name': t.name} for t in obj.theorems.all()]

    def get_comment_count(self, obj):
        return obj.comments.count()

    def get_user_vote(self, obj):
        user = self.context.get('request').user if self.context.get('request') else None
        if user and user.is_authenticated:
            vote = obj.votes.filter(user=user).first()
            return vote.value if vote else None
        return None

    def get_user_save(self, obj):
        user = self.context.get('request').user if self.context.get('request') else None
        if user and user.is_authenticated:
            return obj.saved.filter(user=user).exists()
        return False

    def get_user_complete(self, obj):
        user = self.context.get('request').user if self.context.get('request') else None
        if user and user.is_authenticated:
            c = obj.completed.filter(user=user).first()
            return c.status if c else None
        return None


# =====================
# CONTENT — create/update serializer
# =====================

class ContentCreateSerializer(serializers.ModelSerializer):
    solution_content = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    chapters = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Chapter.objects.all(), required=False
    )
    class_levels = serializers.PrimaryKeyRelatedField(
        many=True, queryset=ClassLevel.objects.all(), required=False
    )
    subfields = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Subfield.objects.all(), required=False
    )
    theorems = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Theorem.objects.all(), required=False
    )
    national_date = serializers.CharField(
        write_only=True, required=False, allow_null=True
    )
    json_content = serializers.JSONField(required=False)

    class Meta:
        model = Content
        fields = [
            'id', 'type', 'title', 'content', 'json_content', 'difficulty',
            'chapters', 'class_levels', 'subject', 'subfields', 'theorems',
            'solution_content', 'national_date',
            'is_national_exam', 'national_year', 'duration_minutes',
        ]

    def validate(self, data):
        national_date = data.pop('national_date', None)
        if national_date:
            try:
                s = str(national_date)
                if len(s) == 4 and s.isdigit():
                    data['national_year'] = int(s)
                else:
                    from datetime import datetime
                    data['national_year'] = datetime.strptime(s, '%Y-%m-%d').year
            except (ValueError, TypeError):
                try:
                    year_str = str(national_date)[:4]
                    if year_str.isdigit():
                        data['national_year'] = int(year_str)
                except Exception:
                    pass
        return data

    def create(self, validated_data):
        json_content = validated_data.pop('json_content', None)
        solution_content = validated_data.pop('solution_content', None)
        chapters = validated_data.pop('chapters', [])
        class_levels = validated_data.pop('class_levels', [])
        subfields = validated_data.pop('subfields', [])
        theorems = validated_data.pop('theorems', [])

        item = Content.objects.create(
            author=self.context['request'].user,
            **validated_data
        )

        if chapters:
            item.chapters.set(chapters)
        if class_levels:
            item.class_levels.set(class_levels)
        if subfields:
            item.subfields.set(subfields)
        if theorems:
            item.theorems.set(theorems)

        if json_content is not None:
            upsert_structure(item.type, item.display_id, json_content)

        if solution_content:
            Solution.objects.create(
                content_item=item,
                solution_text=solution_content,
                author=item.author,
            )

        return item

    def update(self, instance, validated_data):
        json_content = validated_data.pop('json_content', None)
        solution_content = validated_data.pop('solution_content', None)
        chapters = validated_data.pop('chapters', None)
        class_levels = validated_data.pop('class_levels', None)
        subfields = validated_data.pop('subfields', None)
        theorems = validated_data.pop('theorems', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if chapters is not None:
            instance.chapters.set(chapters)
        if class_levels is not None:
            instance.class_levels.set(class_levels)
        if subfields is not None:
            instance.subfields.set(subfields)
        if theorems is not None:
            instance.theorems.set(theorems)

        instance.save()

        if json_content is not None:
            upsert_structure(instance.type, instance.display_id, json_content)

        if solution_content is not None:
            sol, _ = Solution.objects.get_or_create(
                content_item=instance,
                defaults={'author': instance.author},
            )
            sol.solution_text = solution_content
            sol.save()

        return instance
