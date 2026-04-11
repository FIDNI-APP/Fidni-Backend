from django.contrib import admin
from apps.things.models import Content, Solution, Comment


@admin.register(Content)
class ContentAdmin(admin.ModelAdmin):
    list_display = ('title', 'type', 'difficulty', 'author', 'created_at', 'view_count')
    list_filter = ('type', 'difficulty', 'is_national_exam', 'chapters', 'class_levels')
    filter_horizontal = ('chapters', 'class_levels', 'theorems', 'subfields')
    search_fields = ('title', 'content', 'author__username')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at', 'view_count', 'display_id')


@admin.register(Solution)
class SolutionAdmin(admin.ModelAdmin):
    list_display = ('content_item', 'author', 'created_at')
    search_fields = ('content_item__title', 'solution_text', 'author__username')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('author', 'content_item', 'created_at', 'parent')
    search_fields = ('content', 'author__username')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)
