from django.contrib import admin
from .models import FileAttachment


@admin.register(FileAttachment)
class FileAttachmentAdmin(admin.ModelAdmin):
    list_display = ['file_name', 'file_type', 'file_size_formatted', 'uploaded_by', 'uploaded_at']
    list_filter = ['file_type', 'uploaded_at']
    search_fields = ['file_name', 'uploaded_by__username']
    readonly_fields = ['id', 'uploaded_at', 'file_size', 'width', 'height']

    def file_size_formatted(self, obj):
        return obj.file_size_formatted
    file_size_formatted.short_description = 'Size'
