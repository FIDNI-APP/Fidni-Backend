from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404

from .models import FileAttachment
from .serializers import FileAttachmentSerializer, FileUploadSerializer

import logging

logger = logging.getLogger('django')


class FileAttachmentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for file attachments
    """
    queryset = FileAttachment.objects.all()
    serializer_class = FileAttachmentSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        """Filter by user's own files or public files"""
        return FileAttachment.objects.filter(uploaded_by=self.request.user)

    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def download(self, request, pk=None):
        """
        Stable, shareable URL for a file: redirects to a fresh presigned S3 URL.
        Embed THIS url in content HTML — presigned URLs expire, this one doesn't.
        GET /api/files/<uuid>/download/
        """
        attachment = get_object_or_404(FileAttachment.objects.all(), pk=pk)
        return HttpResponseRedirect(attachment.file.url)

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def upload(self, request):
        """
        Upload a file
        POST /api/files/upload/
        Form data:
        - file: the file to upload
        - content_type: optional content type (e.g., 'comment')
        - object_id: optional object ID to attach to
        """
        serializer = FileUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        file = serializer.validated_data['file']
        content_type_name = serializer.validated_data.get('content_type')
        # Le fichier reste libre : il n'est rattaché qu'à la publication (commentaire, solution),
        # par une vue qui vérifie que l'objet appartient bien à l'utilisateur. Avant, n'importe
        # qui pouvait accrocher un fichier au commentaire de quelqu'un d'autre via object_id.
        object_id = None

        # Get content type if provided
        content_type = None
        if content_type_name:
            try:
                content_type = ContentType.objects.get(model=content_type_name.lower())
            except ContentType.DoesNotExist:
                pass

        # Create file attachment
        attachment = FileAttachment.objects.create(
            file=file,
            file_name=file.name,
            file_size=file.size,
            mime_type=file.content_type,
            uploaded_by=request.user,
            content_type=content_type,
            object_id=object_id
        )

        return Response(
            FileAttachmentSerializer(attachment, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )

    def destroy(self, request, *args, **kwargs):
        """Delete file attachment"""
        instance = self.get_object()

        # Only allow user to delete their own files
        if instance.uploaded_by != request.user:
            return Response(
                {'error': 'You can only delete your own files'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Delete the actual file from storage
        if instance.file:
            instance.file.delete(save=False)

        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
