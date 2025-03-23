from django.contrib import admin
from things.models import ClassLevel, Subject, Chapter, Exercise, Solution, Comment

@admin.register(ClassLevel)
class ClassLevelAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name',)
    filter_horizontal = ('class_levels',)
    search_fields = ('name',)

@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ('name', 'subject')
    list_filter = ('subject',)
    search_fields = ('name', 'subject__name')

@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ('title', 'difficulty', 'author', 'created_at', 'view_count')
    list_filter = ('difficulty', 'chapters', 'class_levels')
    filter_horizontal = ('chapters', 'class_levels')
    search_fields = ('title', 'content', 'author__username')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at', 'view_count')

@admin.register(Solution)
class SolutionAdmin(admin.ModelAdmin):
    list_display = ('exercise', 'author', 'created_at')
    list_filter = ('exercise__difficulty',)
    search_fields = ('exercise__title', 'content', 'author__username')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at')

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('exercise', 'author', 'created_at', 'parent')
    list_filter = ('exercise__difficulty',)
    search_fields = ('exercise__title', 'content', 'author__username')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)

