# apps/skilliq/serializers.py
from rest_framework import serializers
from .models import SkillQuestion, SkillAssessment


class SkillQuestionSerializer(serializers.ModelSerializer):
    """Serializer for quiz questions (without correct answer)"""

    class Meta:
        model = SkillQuestion
        fields = ['id', 'question', 'options', 'difficulty']


class SkillQuestionAdminSerializer(serializers.ModelSerializer):
    """Serializer for admin - includes correct answer"""

    class Meta:
        model = SkillQuestion
        fields = ['id', 'chapter', 'question', 'options', 'correct_answer', 'difficulty', 'explanation', 'is_active']


class SkillAssessmentSerializer(serializers.ModelSerializer):
    """Serializer for skill assessment results"""
    chapter_name = serializers.CharField(source='chapter.name', read_only=True)
    subject_name = serializers.SerializerMethodField()

    class Meta:
        model = SkillAssessment
        fields = ['id', 'chapter', 'chapter_name', 'subject_name', 'score', 'max_score', 'level', 'time_spent', 'completed_at']

    def get_subject_name(self, obj):
        if obj.chapter and obj.chapter.subject:
            return obj.chapter.subject.name
        return None


class QuizSubmissionSerializer(serializers.Serializer):
    """Serializer for quiz submission"""
    answers = serializers.DictField(
        child=serializers.IntegerField(min_value=0),
        help_text="Question ID -> selected option index"
    )
    time_spent = serializers.IntegerField(min_value=0, required=False, default=0)
