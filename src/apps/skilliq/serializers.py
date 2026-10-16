# apps/skilliq/serializers.py
from rest_framework import serializers
from .models import SkillQuestion, SkillAssessment


class SkillQuestionSerializer(serializers.ModelSerializer):
    """Question servie à l'élève, SANS la bonne réponse. `nb_bonnes` : nombre de bonnes réponses (1, ou plusieurs :
    « Choisis 2 réponses »), jamais lesquelles."""
    nb_bonnes = serializers.SerializerMethodField()

    class Meta:
        model = SkillQuestion
        fields = ['id', 'question', 'options', 'difficulty', 'nb_bonnes']

    def get_nb_bonnes(self, obj):
        return len(obj.bonnes())


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
                  'previous_score', 'previous_max', 'attempts', 'hub_url', 'par_theoreme', 'class_level', 'completed_at',
                  'a_correction']

    a_correction = serializers.SerializerMethodField()

    def get_a_correction(self, obj):
        """La correction du dernier passage est gardée (« Voir mon dernier résultat » ; GET chapter/<id>/)."""
        return bool(obj.derniere_correction)

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
        if obj.class_level_id:  # quiz d'un niveau précis (13/10/2026) : les exercices de ce niveau
            return hub_url('exercises', obj.class_level, obj.chapter)
        level, chapter_ids = self._level()
        return hub_url('exercises', level, obj.chapter) if obj.chapter_id in chapter_ids else None


class QuizSubmissionSerializer(serializers.Serializer):
    """Envoi d'un quiz : {id de question: index, ou liste d'index pour une question à plusieurs bonnes réponses}
    (-1 : sans réponse, temps écoulé), temps passé en secondes. Les index sont contrôlés contre les réponses de chaque
    question à la notation (views.submit_quiz : hors des choix ou en double = sans réponse)."""
    answers = serializers.DictField(
        child=serializers.JSONField(),
        help_text="Question ID -> selected option index (or list of indexes)"
    )
    time_spent = serializers.IntegerField(min_value=0, required=False, default=0)

    @staticmethod
    def _entier(v):
        return isinstance(v, int) and not isinstance(v, bool)

    def validate_answers(self, value):
        if any(not str(k).isdigit() for k in value):
            raise serializers.ValidationError('Identifiants de questions invalides.')
        for v in value.values():
            ok = (self._entier(v) and v >= -1) or (
                isinstance(v, list) and len(v) <= 10 and all(self._entier(i) and i >= 0 for i in v))
            if not ok:
                raise serializers.ValidationError('Réponses invalides.')
        return value
