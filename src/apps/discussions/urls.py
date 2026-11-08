from django.urls import path

from . import views

urlpatterns = [
    path('discussions/', views.discussions, name='discussions'),
    path('discussions/panneau/', views.panneau, name='discussions-panneau'),
    path('discussions/compteur/', views.compteur, name='discussions-compteur'),
    path('discussions/contenus/', views.contenus, name='discussions-contenus'),
    path('discussions/reponses/<int:pk>/', views.reponse, name='discussions-reponse'),
    path('discussions/reponses/<int:pk>/utile/', views.reponse_utile, name='discussions-reponse-utile'),
    path('discussions/<int:pk>/', views.discussion, name='discussion'),
    path('discussions/<int:pk>/repondre/', views.repondre, name='discussion-repondre'),
    path('discussions/<int:pk>/utile/', views.utile, name='discussion-utile'),
    path('discussions/<int:pk>/suivre/', views.suivre, name='discussion-suivre'),
]
