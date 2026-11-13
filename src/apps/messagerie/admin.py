from django.contrib import admin

from .models import SignalementMessage


@admin.register(SignalementMessage)
class SignalementMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'message', 'auteur', 'created_at', 'traite_le')
    list_filter = ('traite_le',)
    raw_id_fields = ('message', 'auteur')
