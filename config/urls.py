from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from things.views import (
    ExerciseViewSet, ClassLevelViewSet, SubjectViewSet, ChapterViewSet,SolutionViewSet,
    CommentViewSet,SubfieldViewSet, TheoremViewSet
)
from users.views import (
    LoginView, RegisterView, LogoutView, get_current_user,
    get_user_stats, get_user_history,
    mark_content_viewed, mark_content_completed,
    UserTokenObtainPairView
)
from users import views

router = DefaultRouter()
router.register(r'exercises', ExerciseViewSet, basename='exercise')
router.register(r'class-levels', ClassLevelViewSet, basename='class-level')
router.register(r'subjects', SubjectViewSet, basename='subject')
router.register(r'chapters', ChapterViewSet, basename='chapter')
router.register(r'comments', CommentViewSet, basename='comment')
router.register(r'solutions', SolutionViewSet, basename='solution')
router.register(r'subfields', SubfieldViewSet, basename='subfield')
router.register(r'theorems', TheoremViewSet, basename='theorem')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    
    # JWT Authentication
    path('api/auth/token/', UserTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    
    # Legacy Authentication (kept for backward compatibility)
    path('api/auth/login/', LoginView.as_view(), name='login'),
    path('api/auth/register/', RegisterView.as_view(), name='register'),
    path('api/auth/logout/', LogoutView.as_view(), name='logout'),
        
    # User endpoints
    path('api/auth/user/', get_current_user, name='current-user'),
    path('api/users/stats/', get_user_stats, name='user-stats'),
    path('api/users/history/', get_user_history, name='user-history'),
    path('api/content/<str:content_id>/view/', mark_content_viewed, name='mark-content-viewed'),
    path('api/content/<str:content_id>/complete/', mark_content_completed, name='mark-content-completed'),

    # User profile endpoints
    path('api/users/<str:username>/', views.get_user_profile, name='user_profile'),
    path('api/users/<str:username>/exercises/', views.get_user_exercises, name='user_exercises'),
    path('api/users/saved/', views.get_saved_content, name='saved_content'),
]