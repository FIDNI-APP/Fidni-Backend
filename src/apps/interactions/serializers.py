from rest_framework import serializers
from .models import Vote,Save,Complete, RevisionList, RevisionListItem, AICorrection
from apps.users.serializers import UserSerializer
from apps.users.models import ViewHistory
from apps.things.serializers import CommentSerializer, SolutionSerializer, ContentListSerializer
import logging 



logger = logging.getLogger('django')


#----------------------------COMMENT-------------------------------


class VoteSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    comment = CommentSerializer(read_only=True)
    solution = SolutionSerializer(read_only=True)

    class Meta:
        model = Vote
        fields = ['id', 'value', 'created_at', 'updated_at', 'user', 'comment', 'solution']


class SaveSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Save
        fields = ['id', 'created_at', 'user']

class CompleteSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Complete
        fields = ['id', 'created_at', 'updated_at', 'user']


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


class RevisionListSerializer(serializers.ModelSerializer):
    """Serializer for revision lists"""
    user = UserSerializer(read_only=True)
    items = RevisionListItemSerializer(many=True, read_only=True)
    item_count = serializers.ReadOnlyField()

    class Meta:
        model = RevisionList
        fields = ['id', 'name', 'description', 'user', 'items', 'item_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']


class RevisionListCreateSerializer(serializers.ModelSerializer):
    """Simplified serializer for creating/updating revision lists"""

    class Meta:
        model = RevisionList
        fields = ['id', 'name', 'description']
        read_only_fields = ['id']


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