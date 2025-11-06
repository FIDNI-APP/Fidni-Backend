from rest_framework import serializers
from .models import ClassLevel, Subject, Chapter, Subfield, Theorem
import logging 



logger = logging.getLogger('django')


#----------------------------CLASS LEVELS/ SUBJECT / CHAPTER-------------------------------


class ClassLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassLevel
        fields = ['id', 'name', 'order']

class SubjectSerializer(serializers.ModelSerializer):
    class_levels = ClassLevelSerializer(many=True, read_only=True)

    class Meta:
        model = Subject
        fields = ['id', 'name', 'class_levels']
class SubfieldSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)


    class Meta:
        model = Subfield
        fields = ['id', 'name', 'subject', 'class_levels']


class ChapterSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)
    subfield = SubfieldSerializer(read_only = True)


    class Meta:
        model = Chapter
        fields = ['id', 'name', 'subject', 'class_levels', 'subfield']

class TheoremSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)
    chapters = ChapterSerializer(read_only = True)
    subfield = SubfieldSerializer(read_only=  True)


    class Meta:
        model = Theorem
        fields = ['id', 'name', 'subject', 'class_levels','chapters','subfield']