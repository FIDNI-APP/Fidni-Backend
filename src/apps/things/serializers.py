from django.utils.text import slugify
from rest_framework import serializers
from .models import ProposedSolution, Solution, Comment, Content
from apps.interactions.models import Vote
from apps.caracteristics.models import ClassLevel, Chapter, Subfield, Theorem
from apps.users.serializers import AuthorSerializer
from apps.caracteristics.serializers import ChapterSerializer, ClassLevelSerializer, SubjectSerializer, SubfieldSerializer, TheoremSerializer
from apps.uploads.serializers import FileAttachmentSerializer
from .structure_utils import get_total_points, get_item_count, get_section_count
import logging

logger = logging.getLogger('django')


# =====================
# SOLUTION
# =====================

class SolutionSerializer(serializers.ModelSerializer):
    author = AuthorSerializer(read_only=True)
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
    author = AuthorSerializer(read_only=True)
    replies = serializers.SerializerMethodField()
    vote_count = serializers.SerializerMethodField()
    like_count = serializers.SerializerMethodField()
    dislike_count = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    attachments = FileAttachmentSerializer(many=True, read_only=True)
    parent_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Comment
        fields = ['id', 'author', 'content', 'created_at', 'replies',
                  'vote_count', 'like_count', 'dislike_count', 'user_vote', 'parent_id', 'attachments']

    # Sur la page d'un contenu, tous les commentaires arrivent préchargés (ContentSerializer
    # .get_comments) : réponses, votes et auteur sont lus en mémoire. Avant, chaque commentaire
    # coûtait ~7 requêtes (réponses, 2 COUNT de votes, vote de l'élève, auteur, profil, fichiers).
    def get_replies(self, obj):
        tree = self.context.get('comment_children')
        children = tree.get(obj.id, []) if tree is not None else list(obj.replies.all())
        return CommentSerializer(children, many=True, context=self.context).data if children else []

    def get_vote_count(self, obj):
        values = [v.value for v in obj.votes.all()]
        return values.count(Vote.UP) - values.count(Vote.DOWN)

    def get_like_count(self, obj):
        return sum(1 for v in obj.votes.all() if v.value == Vote.UP)

    def get_dislike_count(self, obj):
        return sum(1 for v in obj.votes.all() if v.value == Vote.DOWN)

    def get_user_vote(self, obj):
        user = self.context.get('request').user if self.context.get('request') else None
        if user and user.is_authenticated:
            return next((v.value for v in obj.votes.all() if v.user_id == user.id), None)
        return None


# =====================
# CONTENT — detail serializer
# =====================

class ContentSerializer(serializers.ModelSerializer):
    author = AuthorSerializer(read_only=True)
    chapters = ChapterSerializer(many=True, read_only=True)
    comments = serializers.SerializerMethodField()
    solution = SolutionSerializer(read_only=True)
    vote_count = serializers.IntegerField(read_only=True)
    like_count = serializers.IntegerField(read_only=True)
    dislike_count = serializers.IntegerField(read_only=True)
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
            'id', 'display_id', 'type', 'title', 'json_content',
            'difficulty', 'chapters', 'author', 'created_at', 'updated_at',
            'view_count', 'comments', 'solution', 'vote_count', 'like_count', 'dislike_count', 'user_vote',
            'class_levels', 'subject', 'subfields', 'theorems',
            'user_save', 'user_complete', 'user_timespent',
            'total_points', 'item_count', 'section_count',
            # exam fields
            'is_national_exam', 'national_year', 'duration_minutes',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        json_content = instance.json_content or {}
        data['json_content'] = json_content
        data['total_points'] = get_total_points(json_content)
        data['item_count'] = get_item_count(json_content)
        data['section_count'] = get_section_count(json_content)
        return data

    def get_comments(self, obj):
        # Tous les commentaires du contenu en une fois, puis l'arbre des réponses en mémoire.
        comments = list(
            Comment.objects.filter(content_item=obj)
            .select_related('author', 'author__profile')
            .prefetch_related('votes', 'attachments')
            # Ordre chronologique fixe (le modèle n'en définit aucun : l'ordre variait d'un chargement à l'autre).
            .order_by('created_at', 'id')
        )
        children, roots = {}, []
        for c in comments:
            if c.parent_id:
                children.setdefault(c.parent_id, []).append(c)
            else:
                roots.append(c)
        return CommentSerializer(roots, many=True, context={**self.context, 'comment_children': children}).data

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
    author = AuthorSerializer(read_only=True)
    subject = SubjectSerializer(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)
    chapters = serializers.SerializerMethodField()
    theorems = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()
    vote_count = serializers.SerializerMethodField()
    like_count = serializers.SerializerMethodField()
    dislike_count = serializers.SerializerMethodField()
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
            'comment_count', 'created_at', 'view_count', 'vote_count', 'like_count', 'dislike_count',
            'user_vote', 'user_save', 'user_complete',
            'total_points', 'item_count',
            'is_national_exam', 'national_year', 'duration_minutes',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # La structure est une colonne de la même ligne : déjà chargée, pas de requête en plus.
        json_content = instance.json_content or {}
        data['json_content'] = json_content
        data['total_points'] = get_total_points(json_content)
        data['item_count'] = get_item_count(json_content)
        return data

    def get_chapters(self, obj):
        return [{'id': c.id, 'name': c.name, 'slug': slugify(c.name)} for c in obj.chapters.all()]

    def get_theorems(self, obj):
        return [{'id': t.id, 'name': t.name} for t in obj.theorems.all()]

    # Tout ce qui suit lit les données préchargées par ContentViewSet.get_queryset :
    # avant, chaque carte d'une liste déclenchait ~18 requêtes SQL (N+1).
    def get_vote_count(self, obj):
        annotated = getattr(obj, 'vote_count_annotation', None)
        return annotated if annotated is not None else obj.vote_count

    def get_like_count(self, obj):
        annotated = getattr(obj, 'like_count_annotation', None)
        return annotated if annotated is not None else obj.like_count

    def get_dislike_count(self, obj):
        annotated = getattr(obj, 'dislike_count_annotation', None)
        return annotated if annotated is not None else obj.dislike_count

    def get_comment_count(self, obj):
        return len(obj.comments.all())

    def _viewer(self):
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        return user if user and user.is_authenticated else None

    def get_user_vote(self, obj):
        user = self._viewer()
        if not user:
            return None
        return next((v.value for v in obj.votes.all() if v.user_id == user.id), None)

    def get_user_save(self, obj):
        user = self._viewer()
        if not user:
            return False
        mine = getattr(obj, 'my_saves', None)
        return bool(mine) if mine is not None else obj.saved.filter(user=user).exists()

    def get_user_complete(self, obj):
        user = self._viewer()
        if not user:
            return None
        mine = getattr(obj, 'my_completes', None)
        if mine is None:
            c = obj.completed.filter(user=user).first()
            return c.status if c else None
        return mine[0].status if mine else None


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
            'id', 'type', 'title', 'json_content', 'difficulty',
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
            item.json_content = json_content or {}
            item.save(update_fields=['json_content'])

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

        if json_content is not None:
            instance.json_content = json_content or {}
        instance.save()

        if solution_content is not None:
            sol, _ = Solution.objects.get_or_create(
                content_item=instance,
                defaults={'author': instance.author},
            )
            sol.solution_text = solution_content
            sol.save()

        return instance


# =====================
# PROPOSED SOLUTION
# =====================

class ProposedSolutionSerializer(serializers.ModelSerializer):
    """Solution d'élève : texte de l'éditeur et/ou photos de la copie."""
    author = AuthorSerializer(read_only=True)
    attachments = FileAttachmentSerializer(many=True, read_only=True)
    vote_count = serializers.SerializerMethodField()
    like_count = serializers.SerializerMethodField()
    dislike_count = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()
    content = serializers.PrimaryKeyRelatedField(source='content_item', queryset=Content.objects.all())
    # Pièces jointes déjà envoyées par /api/files/upload/ (photos de la copie).
    file_ids = serializers.ListField(child=serializers.UUIDField(), write_only=True, required=False, max_length=6)

    class Meta:
        model = ProposedSolution
        fields = ['id', 'content', 'author', 'body', 'attachments', 'vote_count', 'like_count', 'dislike_count', 'user_vote',
                  'is_mine', 'created_at', 'updated_at', 'file_ids']
        read_only_fields = ['id', 'author', 'created_at', 'updated_at']

    def validate_body(self, value):
        value = (value or '').strip()
        if len(value) > 30000:
            raise serializers.ValidationError('Solution trop longue (30 000 caractères au plus).')
        return value

    def validate_content(self, item):
        if item.type == 'lesson':
            raise serializers.ValidationError('Les leçons n’acceptent pas de solutions.')
        if self.instance is not None and item.pk != self.instance.content_item_id:
            raise serializers.ValidationError('Une solution ne change pas d’exercice.')
        return item

    def validate(self, attrs):
        body = attrs.get('body', self.instance.body if self.instance else '')
        has_files = bool(attrs.get('file_ids')) or (self.instance is not None and self.instance.attachments.exists())
        if not body and not has_files:
            raise serializers.ValidationError('Rédige ta solution ou ajoute au moins une photo.')
        return attrs

    def get_vote_count(self, obj):
        values = [v.value for v in obj.votes.all()]
        return values.count(Vote.UP) - values.count(Vote.DOWN)

    def get_like_count(self, obj):
        return sum(1 for v in obj.votes.all() if v.value == Vote.UP)

    def get_dislike_count(self, obj):
        return sum(1 for v in obj.votes.all() if v.value == Vote.DOWN)

    def get_user_vote(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            return next((v.value for v in obj.votes.all() if v.user_id == user.id), None)
        return None

    def get_is_mine(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        return bool(user and user.is_authenticated and obj.author_id == user.id)
