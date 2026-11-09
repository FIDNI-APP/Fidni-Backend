from django.contrib import admin

from .models import Abonnement, BadgeObtenu, Blocage, ProfilPublic


@admin.register(ProfilPublic)
class ProfilPublicAdmin(admin.ModelAdmin):
    list_display = ('user', 'verifie', 'abonnes_a_valider', 'visible_recherche', 'objectif', 'updated_at')
    list_editable = ('verifie',)
    list_filter = ('verifie', 'abonnes_a_valider', 'visible_recherche')
    search_fields = ('user__username',)
    raw_id_fields = ('user',)


@admin.register(Abonnement)
class AbonnementAdmin(admin.ModelAdmin):
    list_display = ('abonne', 'suivi', 'statut', 'created_at')
    list_filter = ('statut',)
    search_fields = ('abonne__username', 'suivi__username')
    raw_id_fields = ('abonne', 'suivi')


@admin.register(Blocage)
class BlocageAdmin(admin.ModelAdmin):
    list_display = ('auteur', 'bloque', 'created_at')
    search_fields = ('auteur__username', 'bloque__username')
    raw_id_fields = ('auteur', 'bloque')


@admin.register(BadgeObtenu)
class BadgeObtenuAdmin(admin.ModelAdmin):
    list_display = ('user', 'badge', 'palier', 'obtenu_le')
    list_filter = ('badge', 'palier')
    search_fields = ('user__username',)
    raw_id_fields = ('user',)
