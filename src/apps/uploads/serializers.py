from rest_framework import serializers
from .models import FileAttachment


class FileAttachmentSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    uploaded_by_username = serializers.CharField(source='uploaded_by.username', read_only=True)

    class Meta:
        model = FileAttachment
        fields = [
            'id', 'file_name', 'file_size', 'file_size_formatted', 'file_type',
            'mime_type', 'url', 'download_url', 'uploaded_by', 'uploaded_by_username',
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

    def get_download_url(self, obj):
        """Stable URL (redirects to a fresh presigned S3 URL). Safe to embed in content."""
        request = self.context.get('request')
        path = f'/api/files/{obj.id}/download/'
        return request.build_absolute_uri(path) if request else path


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
            # (Pas de SVG : un SVG peut contenir du JavaScript.)
            'image/jpeg', 'image/png', 'image/gif', 'image/webp',
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
            raise serializers.ValidationError(f"Type de fichier non autorisé : {file.content_type}")

        # Le type annoncé vient du navigateur : l'extension doit concorder, et une « image »
        # doit réellement en être une (sinon, un .html renommé serait servi tel quel).
        ext = file.name.rsplit('.', 1)[-1].lower() if '.' in file.name else ''
        allowed_ext = {
            'image/jpeg': {'jpg', 'jpeg'}, 'image/png': {'png'}, 'image/gif': {'gif'}, 'image/webp': {'webp'},
            'application/pdf': {'pdf'}, 'application/msword': {'doc'},
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': {'docx'},
            'application/vnd.ms-excel': {'xls'},
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': {'xlsx'},
            'text/plain': {'txt', 'md'}, 'application/zip': {'zip'}, 'application/x-rar-compressed': {'rar'},
        }
        if ext not in allowed_ext.get(file.content_type, set()):
            raise serializers.ValidationError('L’extension du fichier ne correspond pas à son type.')
        if file.content_type.startswith('image/'):
            try:
                from PIL import Image
                Image.open(file).verify()
            except Exception:
                raise serializers.ValidationError('Image illisible ou corrompue.')
            finally:
                file.seek(0)

        return file
