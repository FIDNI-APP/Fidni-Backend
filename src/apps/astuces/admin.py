from django.contrib import admin

from .models import Astuce


@admin.register(Astuce)
class AstuceAdmin(admin.ModelAdmin):
    list_display = ('titre', 'chapitre', 'type_question', 'technique', 'ordre', 'publie')
    list_filter = ('niveau', 'chapitre', 'technique', 'publie')
    search_fields = ('titre', 'type_question', 'technique')
