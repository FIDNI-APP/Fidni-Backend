from django.urls import path

from . import views

urlpatterns = [
    path('astuces/', views.liste, name='astuces'),
    path('astuces/etat/', views.etat, name='astuces-etat'),  # avant <slug> : « etat » n'est pas une astuce
    path('astuces/<slug:slug>/', views.detail, name='astuce'),
]
