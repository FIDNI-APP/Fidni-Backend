from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
import uuid
import os


def upload_to(instance, filename):
    """Generate upload path: uploads/{content_type}/{year}/{month}/{uuid}_{filename}"""
    ext = filename.split('.')[-1]
    filename = f"{uuid.uuid4().hex[:12]}_{filename}"

    content_type = instance.content_type.model if instance.content_type else 'general'
    from datetime import datetime
    now = datetime.now()

    return f"uploads/{content_type}/{now.year}/{now.month:02d}/{filename}"


class FileAttachment(models.Model):
    """
    Generic file attachment model that can be attached to any model (comments, exercises, etc.)
    Supports local storage and S3
    """
    FILE_TYPE_CHOICES = [
        ('image', 'Image'),
        ('document', 'Document'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Generic relation to any model
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    # File info
    file = models.FileField(upload_to=upload_to, max_length=500)
    file_name = models.CharField(max_length=255)
    file_size = models.BigIntegerField(help_text="File size in bytes")
    file_type = models.CharField(max_length=20, choices=FILE_TYPE_CHOICES, default='other')
    mime_type = models.CharField(max_length=100)

    # Metadata
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='uploaded_files')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # Optional: Image dimensions (for images)
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['uploaded_by', '-uploaded_at']),
        ]

    def __str__(self):
        return f"{self.file_name} ({self.get_file_type_display()})"

    @property
    def url(self):
        """Get the URL of the file"""
        if self.file:
            return self.file.url
        return None

    @property
    def file_size_formatted(self):
        """Human-readable file size"""
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    def detect_file_type(self):
        """Auto-detect file type based on mime type"""
        if self.mime_type.startswith('image/'):
            return 'image'
        elif self.mime_type.startswith('video/'):
            return 'video'
        elif self.mime_type.startswith('audio/'):
            return 'audio'
        elif self.mime_type in ['application/pdf', 'application/msword',
                                 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                                 'application/vnd.ms-excel',
                                 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']:
            return 'document'
        return 'other'

    def save(self, *args, **kwargs):
        # Auto-detect file type if not set
        if not self.file_type or self.file_type == 'other':
            self.file_type = self.detect_file_type()

        # Extract image dimensions if it's an image
        if self.file_type == 'image' and not self.width:
            try:
                from PIL import Image
                img = Image.open(self.file)
                self.width, self.height = img.size
            except:
                pass

        super().save(*args, **kwargs)
