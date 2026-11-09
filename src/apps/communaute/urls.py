from django.urls import path

from . import views

urlpatterns = [
    path('communaute/profils/<str:username>/', views.profil_view, name='communaute-profil'),
    path('communaute/profils/<str:username>/suivre/', views.suivre, name='communaute-suivre'),
    path('communaute/profils/<str:username>/bloquer/', views.bloquer, name='communaute-bloquer'),
    path('communaute/profils/<str:username>/abonnes/', views.abonnes, name='communaute-abonnes'),
    path('communaute/profils/<str:username>/abonnements/', views.abonnements, name='communaute-abonnements'),
    path('communaute/demandes/', views.demandes, name='communaute-demandes'),
    path('communaute/demandes/<str:username>/<str:reponse>/', views.repondre_demande, name='communaute-demande'),
    path('communaute/abonnes/<str:username>/', views.retirer_abonne, name='communaute-retirer'),
    path('communaute/membres/', views.membres, name='communaute-membres'),
    path('communaute/decouvrir/', views.decouvrir, name='communaute-decouvrir'),
    path('communaute/fil/', views.fil, name='communaute-fil'),
    path('communaute/moi/', views.moi, name='communaute-moi'),
]
