from django.urls import path

from . import views

urlpatterns = [
    path('messagerie/conversations/', views.conversations, name='messagerie-conversations'),
    path('messagerie/conversations/<int:pk>/', views.conversation, name='messagerie-conversation'),
    path('messagerie/conversations/<int:pk>/messages/', views.messages, name='messagerie-messages'),
    path('messagerie/conversations/<int:pk>/lu/', views.lu, name='messagerie-lu'),
    path('messagerie/conversations/<int:pk>/membres/', views.membres, name='messagerie-membres'),
    path('messagerie/conversations/<int:pk>/quitter/', views.quitter, name='messagerie-quitter'),
    path('messagerie/conversations/<int:pk>/inviter/', views.inviter, name='messagerie-inviter'),
    path('messagerie/messages/<int:pk>/', views.message, name='messagerie-message'),
    path('messagerie/messages/<int:pk>/signaler/', views.signaler, name='messagerie-signaler'),
    path('messagerie/non-lus/', views.non_lus, name='messagerie-non-lus'),
    path('messagerie/contacts/', views.contacts, name='messagerie-contacts'),
    path('messagerie/avec/<str:username>/', views.avec, name='messagerie-avec'),
    path('messagerie/ticket/', views.ticket, name='messagerie-ticket'),
    path('messagerie/ice/', views.ice, name='messagerie-ice'),
    path('messagerie/signalements/', views.signalements, name='messagerie-signalements'),
    path('messagerie/signalements/<int:pk>/traiter/', views.traiter_signalement, name='messagerie-traiter'),
]
