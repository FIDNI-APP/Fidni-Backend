# apps/skilliq/admin.py
from django.contrib import admin
from .models import SkillQuestion, SkillAssessment


@admin.register(SkillQuestion)
class SkillQuestionAdmin(admin.ModelAdmin):
    list_display = ['id', 'chapter', 'question_preview', 'difficulty', 'is_active', 'created_at']
    list_filter = ['difficulty', 'is_active', 'chapter__subject']
    search_fields = ['question', 'chapter__name']
    list_editable = ['is_active', 'difficulty']

    def question_preview(self, obj):
        return obj.question[:80] + '...' if len(obj.question) > 80 else obj.question
    question_preview.short_description = 'Question'


@admin.register(SkillAssessment)
class SkillAssessmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'chapter', 'score', 'max_score', 'level', 'completed_at']
    list_filter = ['level', 'chapter__subject']
    search_fields = ['user__username', 'chapter__name']
    readonly_fields = ['score', 'max_score', 'level', 'answers', 'time_spent']
