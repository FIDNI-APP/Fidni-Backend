"""
Serializers for logging models
"""
from rest_framework import serializers
from .models import ErrorLog, APILog, SystemEvent, PageView, UserInteraction, ABTestVariant


class ErrorLogSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True, allow_null=True)
    resolved_by_email = serializers.CharField(source='resolved_by.email', read_only=True, allow_null=True)

    class Meta:
        model = ErrorLog
        fields = [
            'id', 'severity', 'status', 'message', 'exception_type', 'traceback',
            'endpoint', 'method', 'user', 'user_email', 'ip_address', 'user_agent',
            'request_data', 'extra_context', 'count', 'first_seen', 'last_seen',
            'resolved_at', 'resolved_by', 'resolved_by_email', 'notes'
        ]
        read_only_fields = ['first_seen', 'last_seen', 'count']


class APILogSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True, allow_null=True)

    class Meta:
        model = APILog
        fields = [
            'id', 'method', 'endpoint', 'user', 'user_email', 'ip_address',
            'status_code', 'response_time_ms', 'request_body', 'response_body',
            'query_params', 'timestamp'
        ]
        read_only_fields = ['timestamp']


class SystemEventSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True, allow_null=True)

    class Meta:
        model = SystemEvent
        fields = [
            'id', 'event_type', 'title', 'description', 'metadata',
            'user', 'user_email', 'timestamp'
        ]
        read_only_fields = ['timestamp']


class ErrorLogStatsSerializer(serializers.Serializer):
    """Serializer for error statistics"""
    total_errors = serializers.IntegerField()
    new_errors = serializers.IntegerField()
    critical_errors = serializers.IntegerField()
    errors_today = serializers.IntegerField()
    errors_by_severity = serializers.DictField()
    errors_by_endpoint = serializers.ListField()
    recent_errors = ErrorLogSerializer(many=True)


class PageViewSerializer(serializers.Serializer):
    path = serializers.CharField()
    page_title = serializers.CharField(required=False, allow_blank=True)
    referrer = serializers.CharField(required=False, allow_blank=True)
    session_id = serializers.CharField()
    device_type = serializers.CharField(required=False)
    browser = serializers.CharField(required=False)
    os = serializers.CharField(required=False)
    time_on_page = serializers.IntegerField(required=False)


class UserInteractionSerializer(serializers.Serializer):
    interaction_type = serializers.CharField()
    element_id = serializers.CharField(required=False, allow_blank=True)
    element_text = serializers.CharField(required=False, allow_blank=True)
    page_path = serializers.CharField()
    session_id = serializers.CharField()
    variant = serializers.CharField(required=False, allow_blank=True)
    metadata = serializers.JSONField(required=False)


class ABTestImpressionSerializer(serializers.Serializer):
    test_name = serializers.CharField()
    variant_name = serializers.CharField()


class ABTestConversionSerializer(serializers.Serializer):
    test_name = serializers.CharField()
    variant_name = serializers.CharField()
    metadata = serializers.JSONField(required=False)


class AnalyticsStatsSerializer(serializers.Serializer):
    active_users = serializers.IntegerField()
    total_sessions = serializers.IntegerField()
    total_page_views = serializers.IntegerField()
    avg_session_duration = serializers.FloatField()
    bounce_rate = serializers.FloatField()
    top_pages = serializers.ListField()
    top_interactions = serializers.ListField()
    device_breakdown = serializers.DictField()
    browser_breakdown = serializers.DictField()
    hourly_traffic = serializers.ListField()
