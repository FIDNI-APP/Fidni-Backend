from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.db import transaction

from .models import Notebook, NotebookSection, NotebookAnnotation, NotebookLessonEntry
from .serializers import NotebookSerializer, NotebookSectionSerializer, NotebookAnnotationSerializer
from apps.caracteristics.models import Subject, Chapter, ClassLevel
from apps.things.models import Content
import logging

logger = logging.getLogger(__name__)


class NotebookChapterViewSet(viewsets.ModelViewSet):
    """ViewSet for managing chapters within notebooks"""
    serializer_class = NotebookSectionSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get chapters for a specific notebook"""
        notebook_id = self.kwargs.get('notebook_pk')
        return NotebookSection.objects.filter(
            notebook_id=notebook_id,
            notebook__user=self.request.user
        ).order_by('order', 'chapter__name')
    
    def get_notebook(self):
        """Helper method to get the notebook"""
        notebook_id = self.kwargs.get('notebook_pk')
        return get_object_or_404(Notebook, id=notebook_id, user=self.request.user)
    
    def perform_create(self, serializer):
        """Create a new chapter in the notebook"""
        notebook = self.get_notebook()
        serializer.save(notebook=notebook)
    
    @action(detail=True, methods=['post'])
    def add_lesson(self, request, notebook_pk=None, pk=None):
        """Add a lesson to this chapter as a new page"""
        logger.info(f"add_lesson called with notebook_pk={notebook_pk}, pk={pk}, data={request.data}")

        chapter = self.get_object()
        logger.info(f"Chapter retrieved: {chapter}")
        lesson_id = request.data.get('lesson_id')
        logger.info(f"Lesson ID: {lesson_id}")
        
        if not lesson_id:
            return Response(
                {"error": "lesson_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        lesson = get_object_or_404(Content, id=lesson_id, type='lesson')

        # Get the next page order
        last_entry = chapter.lesson_entries.order_by('-page_order').first()
        next_page_order = (last_entry.page_order + 1) if last_entry else 0

        try:
            # Create new lesson entry
            lesson_entry = NotebookLessonEntry.objects.create(
                section=chapter,
                lesson=lesson,
                page_order=next_page_order,
                content_start=0,
                content_end=None,
                is_continuation=False
            )

            serializer = self.get_serializer(chapter)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error in add_lesson: {str(e)}", exc_info=True)
            return Response(
                {"error": f"Erreur lors de l'ajout de la leçon: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def remove_lesson_page(self, request, notebook_pk=None, pk=None):
        """Remove a specific lesson page from this chapter"""
        from .models import NotebookLessonEntry
        
        chapter = self.get_object()
        lesson_entry_id = request.data.get('lesson_entry_id')
        
        if not lesson_entry_id:
            return Response(
                {"error": "lesson_entry_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            lesson_entry = NotebookLessonEntry.objects.get(
                id=lesson_entry_id,
                section=chapter
            )
            lesson_entry.delete()
            
            # Reorder remaining pages
            remaining_entries = chapter.lesson_entries.order_by('page_order')
            for i, entry in enumerate(remaining_entries):
                entry.page_order = i
                entry.save()
                
        except NotebookLessonEntry.DoesNotExist:
            return Response(
                {"error": "Lesson entry not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(chapter)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def update_notes(self, request, notebook_pk=None, pk=None):
        """Update the notes for this chapter"""
        chapter = self.get_object()
        user_notes = request.data.get('user_notes', '')
        
        chapter.user_notes = user_notes
        chapter.save()
        
        serializer = self.get_serializer(chapter)
        return Response(serializer.data)


class NotebookLessonEntryAnnotationViewSet(viewsets.ModelViewSet):
    """ViewSet for managing annotations on lesson entries (pages) within notebook chapters"""
    serializer_class = NotebookAnnotationSerializer
    permission_classes = [IsAuthenticated]
    
    def get_lesson_entry(self):
        """Helper method to get the lesson entry object"""
        notebook_pk = self.kwargs.get('notebook_pk')
        chapter_pk = self.kwargs.get('chapter_pk')
        lesson_entry_pk = self.kwargs.get('lesson_entry_pk')

        return get_object_or_404(
            NotebookLessonEntry,
            id=lesson_entry_pk,
            section_id=chapter_pk,
            section__notebook_id=notebook_pk,
            section__notebook__user=self.request.user
        )

    def get_queryset(self):
        """Get annotations for a specific lesson entry (page)"""
        lesson_entry = self.get_lesson_entry()

        return NotebookAnnotation.objects.filter(
            user=self.request.user,
            lesson=lesson_entry.lesson
        ).order_by('created_at')

    def list(self, request, *args, **kwargs):
        """List all annotations for a lesson entry (page)"""
        lesson_entry = self.get_lesson_entry()

        # Get annotations
        annotations = self.get_queryset()
        annotations_data = [annotation.to_frontend_format() for annotation in annotations]

        return Response({
            "annotations": annotations_data,
            "count": len(annotations_data)
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        """Create/update annotations for a lesson entry (page)"""
        lesson_entry = self.get_lesson_entry()
        annotations = request.data.get('annotations', [])

        try:
            with transaction.atomic():
                # Delete existing annotations for this lesson (not lesson_entry)
                NotebookAnnotation.objects.filter(
                    user=request.user,
                    lesson=lesson_entry.lesson
                ).delete()

                # Create new annotations
                for annotation_data in annotations:
                    annotation = NotebookAnnotation.from_frontend_format(
                        user=request.user,
                        lesson=lesson_entry.lesson,
                        annotation_data=annotation_data
                    )
                    annotation.save()
                
                return Response({
                    "message": "Annotations sauvegardées avec succès",
                    "count": len(annotations)
                }, status=status.HTTP_201_CREATED)
                
        except Exception as e:
            return Response(
                {"error": f"Erreur lors de la sauvegarde: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class NotebookViewSet(viewsets.ModelViewSet):
    serializer_class = NotebookSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Récupérer uniquement les cahiers de l'utilisateur actuel"""
        return Notebook.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        """Associer l'utilisateur actuel lors de la création"""
        serializer.save(user=self.request.user)
    
    @action(detail=False, methods=['get'])
    def get_notebooks(self, request):
        """Récupérer tous les cahiers de l'utilisateur"""
        notebooks = self.get_queryset()
        serializer = self.get_serializer(notebooks, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def create_notebook(self, request):
        """Créer un nouveau cahier avec sections automatiques basées sur les chapitres"""
        # Validation des données
        subject_id = request.data.get('subject_id')
        class_level_id = request.data.get('class_level_id')
        
        if not subject_id or not class_level_id:
            return Response(
                {"error": "Les champs subject_id et class_level_id sont requis"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        subject = get_object_or_404(Subject, id=subject_id)
        class_level = get_object_or_404(ClassLevel, id=class_level_id)
        
        # Vérifier si un cahier existe déjà pour cette combinaison
        existing = Notebook.objects.filter(
            user=request.user,
            subject=subject,
            class_level=class_level
        ).first()
        
        if existing:
            return Response(
                {"error": "Un cahier existe déjà pour cette matière et ce niveau", "notebook_id": existing.id},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Créer le cahier
        notebook = Notebook.objects.create(
            user=request.user,
            subject=subject,
            class_level=class_level,
            title=f"{subject.name} - {class_level.name}"
        )
        
        # Récupérer les chapitres correspondant à cette matière et ce niveau
        chapters = Chapter.objects.filter(
            subject=subject,
            class_levels=class_level
        ).order_by('name')
        
        # Créer les sections pour chaque chapitre
        for i, chapter in enumerate(chapters):
            NotebookSection.objects.create(
                notebook=notebook,
                chapter=chapter,
                order=i
            )
        
        # Renvoyer le cahier complet avec ses sections
        serializer = self.get_serializer(notebook)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'])
    def add_lesson_to_section(self, request, pk=None):
        """Ajouter une leçon à une section spécifique du cahier"""
        notebook = self.get_object()
        section_id = request.data.get('section_id')
        lesson_id = request.data.get('lesson_id')
        
        if not section_id or not lesson_id:
            return Response(
                {"error": "Les champs section_id et lesson_id sont requis"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Vérifier que la section appartient au cahier
        section = get_object_or_404(NotebookSection, id=section_id, notebook=notebook)
        lesson = get_object_or_404(Content, id=lesson_id, type='lesson')
        
        # Vérifier que la leçon correspond à la matière et au niveau
        if lesson.subject.id != notebook.subject.id:
            return Response(
                {"error": "Cette leçon ne correspond pas à la matière du cahier"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Mettre à jour la section avec la leçon
        section.lesson = lesson
        section.save()
        
        # Renvoyer la section mise à jour
        serializer = NotebookSectionSerializer(section)
        return Response(serializer.data)
    

    
    @action(detail=True, methods=['post'])
    def update_section_notes(self, request, pk=None):
        """Mettre à jour les notes personnelles d'une section"""
        notebook = self.get_object()
        section_id = request.data.get('section_id')
        user_notes = request.data.get('user_notes', '')
        
        if not section_id:
            return Response(
                {"error": "Le champ section_id est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Vérifier que la section appartient au cahier
        section = get_object_or_404(NotebookSection, id=section_id, notebook=notebook)
        
        # Mettre à jour les notes
        section.user_notes = user_notes
        section.save()
        
        # Renvoyer la section mise à jour
        serializer = NotebookSectionSerializer(section)
        return Response(serializer.data)


# NotebookSectionViewSet removed - replaced by NotebookChapterViewSet with lesson entries