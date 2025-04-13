from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django.shortcuts import get_object_or_404

from .models import Notebook, NotebookSection
from .serializers import NotebookSerializer, NotebookSectionSerializer
from caracteristics.models import Subject, Chapter, ClassLevel
from things.models import Lesson


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
        lesson = get_object_or_404(Lesson, id=lesson_id)
        
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


class NotebookSectionViewSet(viewsets.ModelViewSet):
    serializer_class = NotebookSectionSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Récupérer uniquement les sections des cahiers de l'utilisateur actuel"""
        return NotebookSection.objects.filter(notebook__user=self.request.user)
    
    def perform_update(self, serializer):
        """Mettre à jour une section"""
        serializer.save()
    
    @action(detail=True, methods=['post'])
    def add_lesson(self, request, pk=None):
        """Ajouter une leçon à cette section"""
        section = self.get_object()
        lesson_id = request.data.get('lesson_id')
        
        if not lesson_id:
            return Response(
                {"error": "Le champ lesson_id est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        lesson = get_object_or_404(Lesson, id=lesson_id)
        
        # Vérifier que la leçon correspond à la matière du cahier
        if lesson.subject.id != section.notebook.subject.id:
            return Response(
                {"error": "Cette leçon ne correspond pas à la matière du cahier"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Mettre à jour la section
        section.lesson = lesson
        section.save()
        
        serializer = self.get_serializer(section)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def remove_lesson(self, request, pk=None):
        """Retirer la leçon de cette section"""
        section = self.get_object()
        section.lesson = None
        section.save()
        
        serializer = self.get_serializer(section)
        return Response(serializer.data)