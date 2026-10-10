# apps/skilliq/serializers.py
from rest_framework import serializers
from .models import SkillQuestion, SkillAssessment


class SkillQuestionSerializer(serializers.ModelSerializer):
    """Serializer for quiz questions (without correct answer)"""

    class Meta:
        model = SkillQuestion
        fields = ['id', 'question', 'options', 'difficulty']


class SkillAssessmentSerializer(serializers.ModelSerializer):
    """Résultat d'un quiz de chapitre. previous_score / previous_max : passage précédent (None au premier),
    pour « 40 % → 80 % » ; attempts : nombre de passages. hub_url : page d'exercices du chapitre au niveau
    de l'élève (context request), pour « S'entraîner » ; None si le chapitre n'est pas de son niveau."""
    chapter_name = serializers.CharField(source='chapter.name', read_only=True)
    subject_name = serializers.SerializerMethodField()
    hub_url = serializers.SerializerMethodField()

    class Meta:
        model = SkillAssessment
        fields = ['id', 'chapter', 'chapter_name', 'subject_name', 'score', 'max_score', 'level', 'time_spent',
                  'previous_score', 'previous_max', 'attempts', 'hub_url', 'completed_at']

    def get_subject_name(self, obj):
        if obj.chapter and obj.chapter.subject:
            return obj.chapter.subject.name
        return None

    def _level(self):
        """(niveau de l'élève, ids des chapitres de ce niveau), lus une fois pour toute la liste."""
        if not hasattr(self, '_level_cache'):
            from apps.caracteristics.models import Chapter
            request = self.context.get('request')
            level = getattr(getattr(getattr(request, 'user', None), 'profile', None), 'class_level', None)
            ids = set(Chapter.objects.filter(class_levels=level).values_list('id', flat=True)) if level else set()
            self._level_cache = (level, ids)
        return self._level_cache

    def get_hub_url(self, obj):
        from apps.caracteristics.hubs import hub_url
        level, chapter_ids = self._level()
        return hub_url('exercises', level, obj.chapter) if obj.chapter_id in chapter_ids else None


class QuizSubmissionSerializer(serializers.Serializer):
    """Serializer for quiz submission"""
    answers = serializers.DictField(
        child=serializers.IntegerField(min_value=0),
        help_text="Question ID -> selected option index"
    )
    time_spent = serializers.IntegerField(min_value=0, required=False, default=0)
