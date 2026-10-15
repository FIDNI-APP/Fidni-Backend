"""Routes des évaluations d'une classe (montées sous /api/classrooms/, voir classrooms/urls.py)."""
from django.urls import path

from . import views

urlpatterns = [
    path('<int:cid>/evaluations/', views.evaluations, name='copies-evaluations'),
    path('<int:cid>/evaluations/<int:eid>/', views.evaluation, name='copies-evaluation'),
    path('<int:cid>/evaluations/<int:eid>/sujet/import/', views.importer_sujet, name='copies-sujet-import'),
    path('<int:cid>/evaluations/<int:eid>/copies/', views.copies, name='copies-copies'),
    path('<int:cid>/evaluations/<int:eid>/eleves/<int:sid>/pages/', views.ajouter_pages, name='copies-pages'),
    path('<int:cid>/evaluations/<int:eid>/pages/<int:pid>/', views.supprimer_page, name='copies-page'),
    path('<int:cid>/evaluations/<int:eid>/copies/<int:pk>/', views.copie, name='copies-copie'),
    path('<int:cid>/evaluations/<int:eid>/copies/<int:pk>/ordre/', views.ordonner_pages, name='copies-ordre'),
    path('<int:cid>/evaluations/<int:eid>/copies/<int:pk>/recorriger/', views.recorriger, name='copies-recorriger'),
    path('<int:cid>/evaluations/<int:eid>/corriger/', views.corriger, name='copies-corriger'),
    path('<int:cid>/evaluations/<int:eid>/publier/', views.publier, name='copies-publier'),
    path('<int:cid>/evaluations/<int:eid>/rapport/', views.rapport, name='copies-rapport'),
    path('<int:cid>/evaluations/<int:eid>/export/', views.exporter, name='copies-export'),
    path('<int:cid>/evaluations/<int:eid>/lots/', views.lots, name='copies-lots'),
    path('<int:cid>/evaluations/<int:eid>/lots/<int:lid>/', views.lot, name='copies-lot'),
    path('<int:cid>/evaluations/<int:eid>/lots/<int:lid>/confirmer/', views.confirmer_lot, name='copies-lot-confirmer'),
]

# Élève et images signées : montées sous /api/ (config/urls.py).
urlpatterns_api = [
    path('mes-copies/', views.mes_copies, name='mes-copies'),
    path('mes-copies/<int:pk>/', views.ma_copie, name='ma-copie'),
    path('copies/pages/<int:pid>/', views.image_page, name='copies-image-page'),
    path('copies/lots/<int:lid>/pages/<int:n>/', views.image_lot, name='copies-image-lot'),
]
