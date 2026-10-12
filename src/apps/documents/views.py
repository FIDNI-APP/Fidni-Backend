from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Document
from .serializers import DocumentListSerializer, DocumentSerializer

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
                                       orientation=doc.orientation, marges=doc.marges)
        return Response(DocumentSerializer(copy).data, status=status.HTTP_201_CREATED)
