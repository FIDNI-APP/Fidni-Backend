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
            raise serializers.ValidationError(
                f'Fichier trop lourd ({file.size / 1024 / 1024:.1f} Mo) : 10 Mo au plus.')

        mime = (file.content_type or '').lower()
        ext = file.name.rsplit('.', 1)[-1].lower() if '.' in file.name else ''

        # Une image se reconnaît à son contenu (25/11/2026, une élève n'arrivait pas à envoyer sa photo au
        # forum) : « photo.jfif », « image/jpg », un type vide ou une photo sans extension passent s'ils sont
        # vraiment du JPEG, PNG, GIF ou WebP, et leur nom et leur type sont remis d'aplomb. Une extension qui
        # n'est pas celle d'une image (« page.html ») reste refusée, même avec un contenu d'image.
        if mime.startswith('image/') or ext in _EXT_IMAGES or (not ext and mime in ('', 'application/octet-stream')):
            if ext and ext not in _EXT_IMAGES:
                raise serializers.ValidationError('L’extension du fichier ne correspond pas à son type.')
            if ext in ('heic', 'heif') or mime in ('image/heic', 'image/heif'):
                raise serializers.ValidationError(
                    'Photo au format HEIC (iPhone) : envoie plutôt une capture d’écran de la photo, ou choisis '
                    '« Le plus compatible » dans Réglages › Appareil photo › Formats.')
            if not _image_reelle(file):
                raise serializers.ValidationError('Image illisible ou dans un format non accepté (JPEG, PNG, GIF ou WebP).')
            return file

        # Documents (pas de SVG : un SVG peut contenir du JavaScript). Le type annoncé vient du navigateur :
        # l'extension doit concorder (sinon, un .html renommé serait servi tel quel).
        allowed_ext = {
            'application/pdf': {'pdf'}, 'application/msword': {'doc'},
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': {'docx'},
            'application/vnd.ms-excel': {'xls'},
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': {'xlsx'},
            'text/plain': {'txt', 'md'}, 'application/zip': {'zip'}, 'application/x-rar-compressed': {'rar'},
        }
        if mime not in allowed_ext:
            raise serializers.ValidationError(f'Type de fichier non autorisé : {file.content_type}')
        if ext not in allowed_ext[mime]:
            raise serializers.ValidationError('L’extension du fichier ne correspond pas à son type.')
        return file


_EXT_IMAGES = {'jpg', 'jpeg', 'jpe', 'jfif', 'pjpeg', 'pjp', 'png', 'gif', 'webp', 'heic', 'heif'}
_FORMATS_IMAGES = {'JPEG': ('image/jpeg', 'jpg'), 'PNG': ('image/png', 'png'),
                   'GIF': ('image/gif', 'gif'), 'WEBP': ('image/webp', 'webp')}


def _image_reelle(file):
    """True si le fichier est réellement une image JPEG, PNG, GIF ou WebP ; son nom et son type sont alors
    corrigés (« photo.jfif » → « photo.jpg », image/jpeg)."""
    try:
        from PIL import Image
        with Image.open(file) as img:
            fmt = img.format
            img.verify()
    except Exception:
        return False
    finally:
        file.seek(0)
    if fmt not in _FORMATS_IMAGES:
        return False
    mime, ext = _FORMATS_IMAGES[fmt]
    base = file.name.rsplit('.', 1)[0] if '.' in file.name else file.name
    file.name = f'{base or "image"}.{ext}'
    file.content_type = mime
    return True
