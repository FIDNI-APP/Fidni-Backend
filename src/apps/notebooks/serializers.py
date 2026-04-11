# notebooks/serializers.py

from rest_framework import serializers
from .models import Notebook, NotebookSection, NotebookLessonEntry, NotebookAnnotation
from apps.caracteristics.serializers import SubjectSerializer, ClassLevelSerializer, ChapterSerializer
from apps.caracteristics.models import Chapter, Subject, ClassLevel
from apps.things.models import Content
from apps.things.serializers import ContentSerializer

class NotebookLessonEntrySerializer(serializers.ModelSerializer):
    lesson = ContentSerializer(read_only=True)
    lesson_id = serializers.PrimaryKeyRelatedField(source='lesson', queryset=Content.objects.filter(type='lesson'), write_only=True)
    
    class Meta:
        model = NotebookLessonEntry
        fields = ['id', 'lesson', 'lesson_id', 'page_order', 'content_start', 'content_end', 
                 'is_continuation', 'added_at']
        read_only_fields = ['id', 'added_at']

class NotebookSectionSerializer(serializers.ModelSerializer):
    chapter = ChapterSerializer(read_only=True)
    lesson_entries = NotebookLessonEntrySerializer(many=True, read_only=True)
    chapter_id = serializers.PrimaryKeyRelatedField(source='chapter', queryset=Chapter.objects.all(), write_only=True)
    
    class Meta:
        model = NotebookSection
        fields = ['id', 'chapter', 'chapter_id', 'lesson_entries', 'user_notes', 'order']
        read_only_fields = ['id']

class NotebookAnnotationSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotebookAnnotation
        fields = ['id', 'annotation_id', 'annotation_type', 'position_x', 'position_y', 
                 'width', 'height', 'color', 'content', 'path_data', 'stroke_width', 'lesson_entry', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

class NotebookSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    class_level = ClassLevelSerializer(read_only=True)
    sections = NotebookSectionSerializer(many=True, read_only=True)
    subject_id = serializers.PrimaryKeyRelatedField(source='subject', queryset=Subject.objects.all(), write_only=True)
    class_level_id = serializers.PrimaryKeyRelatedField(source='class_level', queryset=ClassLevel.objects.all(), write_only=True)
    
    class Meta:
        model = Notebook
        fields = ['id', 'title', 'subject', 'subject_id', 'class_level', 'class_level_id', 'created_at', 'updated_at', 'sections']
        read_only_fields = ['id', 'created_at', 'updated_at']