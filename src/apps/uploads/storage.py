"""
Storage configuration for file uploads
Supports both local filesystem and AWS S3

Environment variables for S3:
- AWS_STORAGE_ENABLED=true (to enable S3)
- AWS_ACCESS_KEY_ID=your_access_key
- AWS_SECRET_ACCESS_KEY=your_secret_key
- AWS_STORAGE_BUCKET_NAME=your_bucket_name
- AWS_S3_REGION_NAME=your_region (e.g., eu-west-1)
- AWS_S3_CUSTOM_DOMAIN=your_cdn_domain (optional, for CloudFront)
"""

from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


class MediaStorage(S3Boto3Storage):
    """Custom storage for media files (user uploads)"""
    location = 'media'
    file_overwrite = False  # Don't overwrite files with same name


def get_storage_backend():
    """
    Get the appropriate storage backend based on configuration
    Returns S3 storage if enabled, otherwise default Django storage
    """
    if getattr(settings, 'AWS_STORAGE_ENABLED', False):
        return 'apps.uploads.storage.MediaStorage'
    return 'django.core.files.storage.FileSystemStorage'
