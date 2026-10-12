from django.http import HttpResponse
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Document
from .serializers import DocumentListSerializer, DocumentSerializer
from .word import WordErreur, exporter_docx, importer_docx

# Garde-fou : au-delà, il faut en supprimer avant d'en créer.
MAX_DOCUMENTS = 300


class DocumentViewSet(viewsets.ModelViewSet):
    """`/api/documents/` : les documents de l'éditeur, ceux du membre connecté seulement."""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Document.objects.filter(user=self.request.user)
        q = (self.request.query_params.get('q') or '').strip()
        if q:
            qs = qs.filter(title__icontains=q[:100])
        return qs

    def get_serializer_class(self):
        return DocumentListSerializer if self.action == 'list' else DocumentSerializer

    def create(self, request, *args, **kwargs):
        if Document.objects.filter(user=request.user).count() >= MAX_DOCUMENTS:
            return Response({'detail': f'{MAX_DOCUMENTS} documents au plus : supprime ceux dont tu n’as plus besoin.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['post'])
    def dupliquer(self, request, pk=None):
        doc = self.get_object()
        if Document.objects.filter(user=request.user).count() >= MAX_DOCUMENTS:
            return Response({'detail': f'{MAX_DOCUMENTS} documents au plus.'}, status=status.HTTP_400_BAD_REQUEST)
        copy = Document.objects.create(user=request.user, title=f'{doc.title} (copie)'[:200], html=doc.html,
                                       orientation=doc.orientation, marges=doc.marges, entete=doc.entete)
        return Response(DocumentSerializer(copy).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='importer-docx', parser_classes=[MultiPartParser, FormParser])
    def importer_docx(self, request):
        """`POST /api/documents/importer-docx/` (champ `fichier`) : un document Word devient un nouveau document."""
        f = request.FILES.get('fichier')
        if not f:
            return Response({'detail': 'Aucun fichier envoyé.'}, status=status.HTTP_400_BAD_REQUEST)
        if Document.objects.filter(user=request.user).count() >= MAX_DOCUMENTS:
            return Response({'detail': f'{MAX_DOCUMENTS} documents au plus.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            titre, html, avertissements = importer_docx(f.read(), f.name, request.user, request)
        except WordErreur as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        ser = DocumentSerializer(data={'title': titre, 'html': html})
        if not ser.is_valid():
            return Response({'detail': 'Document trop long pour l’éditeur (2 Mo de texte au plus).'},
                            status=status.HTTP_400_BAD_REQUEST)
        doc = ser.save(user=request.user)
        return Response({**DocumentSerializer(doc).data, 'avertissements': avertissements}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def docx(self, request, pk=None):
        """`GET /api/documents/<id>/docx/` : le document en Word, équations modifiables."""
        doc = self.get_object()
        try:
            data = exporter_docx(doc)
        except WordErreur as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        resp = HttpResponse(data, content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        resp['Content-Disposition'] = f'attachment; filename="{slugify(doc.title) or "document"}.docx"'
        return resp
