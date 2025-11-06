"""API v1 URL Configuration"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

# Import all viewsets (can be organized later)
router = DefaultRouter()

urlpatterns = [
    path('', include(router.urls)),
]
