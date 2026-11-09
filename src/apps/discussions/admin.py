from django.contrib import admin

from .models import Discussion, Reply


@admin.register(Discussion)
class DiscussionAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'genre', 'author', 'salon', 'class_level', 'reply_count', 'last_activity_at')
    list_filter = ('genre', 'salon', 'class_level')
    search_fields = ('title', 'body', 'author__username')
    raw_id_fields = ('author', 'contents')


@admin.register(Reply)
class ReplyAdmin(admin.ModelAdmin):
    list_display = ('discussion', 'author', 'created_at')
    search_fields = ('body', 'author__username')
    raw_id_fields = ('discussion', 'author', 'reply_to')
