from django.contrib import admin

from .models import (
    ConcoursExam, ConcoursTip, ConcoursComment, ConcoursExamStats,
    SimulationSession, SimulationAnswer,
)


@admin.register(ConcoursExamStats)
class ConcoursExamStatsAdmin(admin.ModelAdmin):
    list_display = ('exam', 'updated_by', 'updated_at')
    readonly_fields = ('updated_at',)


@admin.register(ConcoursExam)
class ConcoursExamAdmin(admin.ModelAdmin):
    list_display = ('display_id', 'concours_type', 'year', 'duration_minutes', 'created_at')
    list_filter = ('concours_type', 'year')
    search_fields = ('title',)
    readonly_fields = ('display_id', 'created_at', 'updated_at')


@admin.register(ConcoursTip)
class ConcoursTipAdmin(admin.ModelAdmin):
    list_display = ('title', 'subject', 'subfield', 'view_count', 'created_at')
    list_filter = ('subject', 'subfield')
    search_fields = ('title', 'description')
    readonly_fields = ('view_count', 'created_at', 'updated_at')
    autocomplete_fields = ()
    filter_horizontal = ('chapters',)


@admin.register(ConcoursComment)
class ConcoursCommentAdmin(admin.ModelAdmin):
    list_display = ('author', 'target_type', 'target_id', 'created_at')
    list_filter = ('target_type',)
    search_fields = ('content', 'author__username')


@admin.register(SimulationSession)
class SimulationSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'mode', 'concours_type', 'status',
                    'correct_count', 'total_questions', 'started_at', 'submitted_at')
    list_filter = ('mode', 'concours_type', 'status')
    search_fields = ('user__username',)
    readonly_fields = ('id', 'questions_snapshot', 'started_at', 'submitted_at')


@admin.register(SimulationAnswer)
class SimulationAnswerAdmin(admin.ModelAdmin):
    list_display = ('session', 'position', 'chosen_key', 'is_correct')
    list_filter = ('is_correct',)
