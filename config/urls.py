from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from things.views import (
    ExerciseViewSet,SolutionViewSet,
    CommentViewSet
)
from users.views import (
    get_current_user,
    UserProfileViewSet, UserSettingsView, mark_content_viewed, OnboardingView,
)
from caracteristics.views import (
    ClassLevelViewSet, SubjectViewSet, ChapterViewSet, SubfieldViewSet, TheoremViewSet)
from authentication.views import LogoutView

from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from authentication.views import LoginView, RegisterView


router = DefaultRouter()
router.register(r'exercises', ExerciseViewSet, basename='exercise')
router.register(r'class-levels', ClassLevelViewSet, basename='class-level')
router.register(r'subjects', SubjectViewSet, basename='subject')
router.register(r'chapters', ChapterViewSet, basename='chapter')
router.register(r'comments', CommentViewSet, basename='comment')
router.register(r'solutions', SolutionViewSet, basename='solution')
router.register(r'subfields', SubfieldViewSet, basename='subfield')
router.register(r'theorems', TheoremViewSet, basename='theorem')
router.register(r'users', UserProfileViewSet, basename='user-profile')



urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path("api-auth/", include("rest_framework.urls")),
    
    # Legacy Authentication (kept for backward compatibility)
    path('api/auth/login/', LoginView.as_view(), name='login'),
    path('api/auth/register/', RegisterView.as_view(), name='register'),
    path('api/auth/logout/', LogoutView.as_view(), name='logout'),
        
    # User endpoints
    path('api/auth/user/', get_current_user, name='current-user'),
    path("api/token/", TokenObtainPairView.as_view(), name="get_token"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="refresh"),
    path('api/content/<str:content_id>/view/', mark_content_viewed, name='mark-content-viewed'),
    path('api/onboarding/', OnboardingView.as_view(), name='onboarding'),
    path('api/users/<str:username>/onboarding-status/', UserProfileViewSet.as_view({'get': 'onboarding_status'}), name='onboarding-status'),

     # User endpoints
    path('api/auth/settings/', UserSettingsView.as_view(), name='user-settings'),
    
    # Content interaction
    path('api/content/<str:content_id>/view/', mark_content_viewed, name='mark-content-viewed'),
]