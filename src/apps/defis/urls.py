from django.urls import path

from . import admin_api, views

urlpatterns = [
    path('defis/aujourdhui/', views.du_jour, name='defi-du-jour'),
    path('defis/archives/', views.archives, name='defi-archives'),
    path('defis/<str:jour>/', views.detail, name='defi-detail'),
    path('defis/<str:jour>/repondre/', views.repondre, name='defi-repondre'),
    path('defis/<str:jour>/indice/', views.indice, name='defi-indice'),
    path('defis/<str:jour>/abandonner/', views.abandonner, name='defi-abandonner'),
    path('pilotage/defis/', admin_api.liste, name='pilotage-defis'),
    path('pilotage/defis/valider/', admin_api.valider, name='pilotage-defis-valider'),
    path('pilotage/defis/<int:pk>/', admin_api.un_defi, name='pilotage-defi'),
]
