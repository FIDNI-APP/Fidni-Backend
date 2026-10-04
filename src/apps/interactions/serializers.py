from rest_framework import serializers
from .models import RevisionList, RevisionListItem, AICorrection
from apps.caracteristics.models import ClassLevel, Subject, Chapter
from apps.users.serializers import UserSerializer
from apps.users.models import ViewHistory
import logging 



logger = logging.getLogger('django')


#----------------------------COMMENT-------------------------------


class ViewHistorySerializer(serializers.ModelSerializer):
    viewed_at = serializers.ReadOnlyField()
    time_spent = serializers.ReadOnlyField(source='time_spent_in_seconds')

    class Meta:
        model = ViewHistory
        fields = ('viewed_at', 'time_spent')
        read_only_fields = ('viewed_at', 'time_spent')


#----------------------------REVISION LISTS-------------------------------

class RevisionListItemSerializer(serializers.ModelSerializer):
    """Serializer for items in a revision list"""
    content_object = serializers.SerializerMethodField()
    content_type_name = serializers.SerializerMethodField()

    class Meta:
        model = RevisionListItem
        fields = ['id', 'content_object', 'content_type', 'object_id', 'content_type_name', 'added_at', 'notes']
        read_only_fields = ['id', 'added_at']

    def get_content_object(self, obj):
        if obj.content_object:
            from apps.things.serializers import ContentListSerializer
            return ContentListSerializer(obj.content_object, context=self.context).data
        return None

    def get_content_type_name(self, obj):
        """Return a readable content type name"""
        return obj.content_type.model if obj.content_type else None


class _NamedSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class RevisionListSerializer(serializers.ModelSerializer):
    """Serializer for revision lists"""
    user = UserSerializer(read_only=True)
    items = RevisionListItemSerializer(many=True, read_only=True)
    item_count = serializers.ReadOnlyField()
    class_levels = _NamedSerializer(many=True, read_only=True)
    subjects = _NamedSerializer(many=True, read_only=True)
    chapters = _NamedSerializer(many=True, read_only=True)

    class Meta:
        model = RevisionList
        fields = ['id', 'name', 'description', 'user', 'items', 'item_count',
                  'class_levels', 'subjects', 'chapters', 'created_at', 'updated_at']
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']


class RevisionListCreateSerializer(serializers.ModelSerializer):
    """Création / modification d'une liste : nom, description et étiquettes facultatives."""
    class_level_ids = serializers.PrimaryKeyRelatedField(
        source='class_levels', many=True, required=False, queryset=ClassLevel.objects.all())
    subject_ids = serializers.PrimaryKeyRelatedField(
        source='subjects', many=True, required=False, queryset=Subject.objects.all())
    chapter_ids = serializers.PrimaryKeyRelatedField(
        source='chapters', many=True, required=False, queryset=Chapter.objects.all())
    class_levels = _NamedSerializer(many=True, read_only=True)
    subjects = _NamedSerializer(many=True, read_only=True)
    chapters = _NamedSerializer(many=True, read_only=True)
    item_count = serializers.ReadOnlyField()

    class Meta:
        model = RevisionList
        fields = ['id', 'name', 'description', 'class_level_ids', 'subject_ids', 'chapter_ids',
                  'class_levels', 'subjects', 'chapters', 'item_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_name(self, value):
        value = (value or '').strip()
        if not value:
            raise serializers.ValidationError('Donne un nom à ta liste.')
        request = self.context.get('request')
        qs = RevisionList.objects.filter(user=request.user, name=value) if request else RevisionList.objects.none()
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('Tu as déjà une liste qui porte ce nom.')
        return value


#----------------------------AI CORRECTION-------------------------------

class AICorrectionSerializer(serializers.ModelSerializer):
    """Serializer for AI corrections"""
    image_url = serializers.SerializerMethodField()
    user = UserSerializer(read_only=True)

    class Meta:
        model = AICorrection
        fields = [
            'id', 'user', 'image', 'image_url', 'submitted_at',
            'conversation_started_at', 'submission_state', 'language',
            'ai_provider', 'ai_model', 'score_awarded', 'score_total',
            'feedback', 'raw_response', 'processing_time_ms', 'chat_history',
            'pedagogical_context'
        ]
        read_only_fields = [
            'id', 'user', 'submitted_at', 'conversation_started_at',
            'ai_provider', 'ai_model', 'score_awarded', 'score_total',
            'feedback', 'raw_response', 'processing_time_ms'
        ]

    def get_image_url(self, obj):
        """Get absolute URL for uploaded image"""
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None