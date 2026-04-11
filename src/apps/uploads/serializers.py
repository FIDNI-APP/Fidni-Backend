from rest_framework import serializers
from .models import FileAttachment


class FileAttachmentSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    uploaded_by_username = serializers.CharField(source='uploaded_by.username', read_only=True)

    class Meta:
        model = FileAttachment
        fields = [
            'id', 'file_name', 'file_size', 'file_size_formatted', 'file_type',
            'mime_type', 'url', 'uploaded_by', 'uploaded_by_username',
            'uploaded_at', 'width', 'height'
        ]
        read_only_fields = [
            'id', 'file_size', 'file_size_formatted', 'file_type',
            'uploaded_by', 'uploaded_at', 'width', 'height'
        ]

    def get_url(self, obj):
        request = self.context.get('request')
        if obj.url:
            if request:
                return request.build_absolute_uri(obj.url)
            return obj.url
        return None


class FileUploadSerializer(serializers.Serializer):
    """Serializer for file upload"""
    file = serializers.FileField()
    content_type = serializers.CharField(required=False, allow_blank=True)
    object_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_file(self, file):
        # Max file size: 10MB
        max_size = 10 * 1024 * 1024
        if file.size > max_size:
            raise serializers.ValidationError(f"File size must be less than 10MB. Current size: {file.size / 1024 / 1024:.1f}MB")

        # Allowed mime types
        allowed_types = [
            # Images
            'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml',
            # Documents
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'text/plain',
            # Archives
            'application/zip',
            'application/x-rar-compressed',
        ]

        if file.content_type not in allowed_types:
            raise serializers.ValidationError(f"File type not allowed: {file.content_type}")

        return file
