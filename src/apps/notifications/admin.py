from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'kind', 'title', 'count', 'updated_at', 'read_at')
    list_filter = ('kind',)
    search_fields = ('recipient__username', 'title')
    raw_id_fields = ('recipient', 'actor')
