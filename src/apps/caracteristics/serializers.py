from rest_framework import serializers
from .models import ClassLevel, Subject, Chapter, Subfield, Theorem
import logging 



logger = logging.getLogger('django')


#----------------------------CLASS LEVELS/ SUBJECT / CHAPTER-------------------------------


class ClassLevelSerializer(serializers.ModelSerializer):
    content_count = serializers.SerializerMethodField()

    class Meta:
        model = ClassLevel
        fields = ['id', 'name', 'order', 'content_count']

    def get_content_count(self, obj):
        return getattr(obj, 'content_count', None)

class SubjectSerializer(serializers.ModelSerializer):
    class_levels = ClassLevelSerializer(many=True, read_only=True)
    content_count = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = ['id', 'name', 'class_levels', 'content_count']

    def get_content_count(self, obj):
        return getattr(obj, 'content_count', None)

class SubfieldSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)
    content_count = serializers.SerializerMethodField()

    class Meta:
        model = Subfield
        fields = ['id', 'name', 'subject', 'class_levels', 'content_count']

    def get_content_count(self, obj):
        return getattr(obj, 'content_count', None)

class ChapterSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)
    subfield = SubfieldSerializer(read_only = True)
    content_count = serializers.SerializerMethodField()

    class Meta:
        model = Chapter
        fields = ['id', 'name', 'subject', 'class_levels', 'subfield', 'content_count']

    def get_content_count(self, obj):
        return getattr(obj, 'content_count', None)

class TheoremSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)
    chapters = ChapterSerializer(read_only = True)
    subfield = SubfieldSerializer(read_only=  True)
    content_count = serializers.SerializerMethodField()

    class Meta:
        model = Theorem
        fields = ['id', 'name', 'subject', 'class_levels','chapters','subfield', 'content_count']

    def get_content_count(self, obj):
        return getattr(obj, 'content_count', None)


# Nested serializers for Skill IQ taxonomy tree
class ChapterMinimalSerializer(serializers.ModelSerializer):
    """Minimal chapter serializer for taxonomy tree"""
    class Meta:
        model = Chapter
        fields = ['id', 'name']


class SubjectWithChaptersSerializer(serializers.ModelSerializer):
    """Subject with its chapters for taxonomy tree"""
    chapters = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = ['id', 'name', 'chapters']

    def get_chapters(self, obj):
        # Get class level from context if available
        class_level_id = self.context.get('class_level_id')
        if class_level_id:
            chapters = obj.chapters.filter(class_levels__id=class_level_id)
        else:
            chapters = obj.chapters.all()
        return ChapterMinimalSerializer(chapters, many=True).data


class ClassLevelWithTaxonomySerializer(serializers.ModelSerializer):
    """Class level with full taxonomy tree (subjects + chapters)"""
    subjects = serializers.SerializerMethodField()

    class Meta:
        model = ClassLevel
        fields = ['id', 'name', 'order', 'subjects']

    def get_subjects(self, obj):
        subjects = obj.subjects.all()
        return SubjectWithChaptersSerializer(
            subjects,
            many=True,
            context={'class_level_id': obj.id}
        ).data