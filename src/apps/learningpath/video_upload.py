"""Envoi vidéo admin par blocs, dans le stockage de fichiers déjà utilisé par Fidni."""
from pathlib import Path
from datetime import timedelta
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files import File
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from apps.uploads.models import FileAttachment
from .models import ParcoursVideoUpload, Video
from .serializers import VideoSerializer

CHUNK_SIZE = 5 * 1024 * 1024
MAX_SIZE = 2 * 1024 * 1024 * 1024
TYPES = {'video/mp4': '.mp4', 'video/webm': '.webm'}


class VideoUploadMetadata(serializers.ModelSerializer):
    class Meta:
        model = Video
        fields = ['path_chapter', 'title', 'video_type', 'duration_seconds', 'order']



class UploadStart(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    mime_type = serializers.ChoiceField(choices=list(TYPES))
    size = serializers.IntegerField(min_value=1, max_value=MAX_SIZE)
    video = serializers.DictField()
    target = serializers.PrimaryKeyRelatedField(queryset=Video.objects.all(), required=False)


class UploadPart(serializers.Serializer):
    session = serializers.UUIDField()
    offset = serializers.IntegerField(min_value=0)
    file = serializers.FileField()


class UploadFinish(serializers.Serializer):
    session = serializers.UUIDField()


def staging_path(upload):
    # Hors des fichiers publics : nginx refuse ce sous-dossier.
    return Path(settings.MEDIA_ROOT) / '.parcours-uploads' / (str(upload.id) + '.part')


def get_upload(request, session):
    upload = get_object_or_404(ParcoursVideoUpload.objects.select_for_update(), pk=session, user=request.user)
    if not upload.video_id and upload.created_at < timezone.now() - timedelta(days=1):
        raise serializers.ValidationError('Cet envoi a expiré. Sélectionne à nouveau le fichier.')
    return upload


class VideoUploadMixin:
    @action(detail=False, methods=['post'], permission_classes=[IsAdminUser], parser_classes=[JSONParser])
    def upload_init(self, request):
        serializer = UploadStart(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if not values['name'].lower().endswith(TYPES[values['mime_type']]):
            raise serializers.ValidationError('Le nom et le type de la vidéo ne correspondent pas.')
        target = values.get('target')
        video = VideoUploadMetadata(target, data=values['video'])
        video.is_valid(raise_exception=True)
        fields = video.validated_data
        if fields['duration_seconds'] <= 0:
            raise serializers.ValidationError('Renseigne une durée supérieure à zéro.')
        if target and target.path_chapter_id != fields['path_chapter'].id:
            raise serializers.ValidationError('La vidéo appartient à un autre chapitre.')
        # Les envois abandonnés du même admin sont purgés à sa prochaine visite.
        expired = ParcoursVideoUpload.objects.filter(user=request.user, created_at__lt=timezone.now() - timedelta(days=1))
        for previous in expired:
            staging_path(previous).unlink(missing_ok=True)
        expired.delete()
        upload = ParcoursVideoUpload.objects.create(
            user=request.user, chapter=fields['path_chapter'],
            name=values['name'], mime_type=values['mime_type'], size=values['size'],
            metadata={**{k: fields[k] for k in ('title', 'video_type', 'duration_seconds', 'order')}, 'target_id': target.pk if target else None},
        )
        return Response({'session': str(upload.id), 'received': 0, 'chunk_size': CHUNK_SIZE}, status=201)

    @action(detail=False, methods=['post'], permission_classes=[IsAdminUser],
            parser_classes=[MultiPartParser, FormParser])
    @transaction.atomic
    def upload_part(self, request):
        serializer = UploadPart(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        upload = get_upload(request, values['session'])
        offset, chunk = values['offset'], values['file']
        if upload.video_id or offset < upload.received:
            return Response({'received': upload.received})
        if offset != upload.received:
            return Response({'received': upload.received}, status=status.HTTP_409_CONFLICT)
        if not chunk.size or chunk.size > CHUNK_SIZE or upload.received + chunk.size > upload.size:
            raise serializers.ValidationError('Taille de bloc invalide.')
        if offset == 0:
            header = chunk.read(16)
            chunk.seek(0)
            valid = header[4:8] == b'ftyp' if upload.mime_type == 'video/mp4' else header[:4] == b'\x1aE\xdf\xa3'
            if not valid:
                raise serializers.ValidationError('Le fichier ne correspond pas au format vidéo annoncé.')
        path = staging_path(upload)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Un bloc réémis après une coupure réécrit la même position.
        with path.open('r+b' if path.exists() else 'w+b') as output:
            output.seek(offset)
            for data in chunk.chunks():
                output.write(data)
            output.truncate(offset + chunk.size)
        upload.received += chunk.size
        upload.save(update_fields=['received'])
        return Response({'received': upload.received})

    @action(detail=False, methods=['post'], permission_classes=[IsAdminUser], parser_classes=[JSONParser])
    @transaction.atomic
    def upload_finish(self, request):
        serializer = UploadFinish(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = get_upload(request, serializer.validated_data['session'])
        if upload.video_id:
            return Response(VideoSerializer(upload.video, context={'request': request}).data)
        path = staging_path(upload)
        if upload.received != upload.size or not path.exists() or path.stat().st_size != upload.size:
            raise serializers.ValidationError('L’envoi est incomplet. Réessaie.')
        target_id = upload.metadata.get('target_id')
        target = get_object_or_404(Video.objects.select_for_update(), pk=target_id) if target_id else None
        payload = {k: upload.metadata[k] for k in ('title', 'video_type', 'duration_seconds', 'order')}
        payload['path_chapter'] = upload.chapter_id
        video_serializer = VideoUploadMetadata(target, data=payload)
        video_serializer.is_valid(raise_exception=True)
        # Le stockage et le rattachement se font après réception de tous les blocs.
        attachment = FileAttachment(
            uploaded_by=request.user, file_name=upload.name, file_size=upload.size,
            file_type='video', mime_type=upload.mime_type,
            content_type=ContentType.objects.get_for_model(Video),
        )
        try:
            with path.open('rb') as source:
                attachment.file.name = attachment.file.storage.save(
                    f'parcours-videos/{upload.id}{TYPES[upload.mime_type]}', File(source)
                )
            attachment.save()
            video = video_serializer.save(url=request.build_absolute_uri(f'/api/files/{attachment.pk}/download/'))
            attachment.object_id = video.pk
            attachment.save(update_fields=['object_id'])
            upload.video = video
            upload.save(update_fields=['video'])
        except Exception:
            if attachment.file.name:
                attachment.file.delete(save=False)
            raise
        transaction.on_commit(lambda: path.unlink(missing_ok=True))
        return Response(VideoSerializer(video, context={'request': request}).data, status=201)
