# notebooks/serializers.py

from rest_framework import serializers
from .models import Notebook, NotebookSection
from caracteristics.serializers import SubjectSerializer, ClassLevelSerializer, ChapterSerializer
from caracteristics.models import Chapter, Subject, ClassLevel
from things.models import Lesson
from things.serializers import LessonSerializer

class NotebookSectionSerializer(serializers.ModelSerializer):
    chapter = ChapterSerializer(read_only=True)
    lesson = LessonSerializer(read_only=True)
    chapter_id = serializers.PrimaryKeyRelatedField(source='chapter', queryset=Chapter.objects.all(), write_only=True)
    lesson_id = serializers.PrimaryKeyRelatedField(source='lesson', queryset=Lesson.objects.all(), write_only=True, required=False, allow_null=True)
    
    class Meta:
        model = NotebookSection
        fields = ['id', 'chapter', 'chapter_id', 'lesson', 'lesson_id', 'user_notes', 'order']
        read_only_fields = ['id']

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