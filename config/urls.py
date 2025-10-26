from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from things.views import (
    ExerciseViewSet,SolutionViewSet,
    CommentViewSet, LessonViewSet,ExamViewSet
)
from users.views import (
    get_current_user,
    UserProfileViewSet, UserSettingsView, mark_content_viewed, OnboardingView,
)
from users.dashboard_views import (
    get_user_dashboard_stats,
    get_learning_path_progress,
    get_recommended_content,
)
from users.study_stats_views import get_study_statistics
from caracteristics.views import (
    ClassLevelViewSet, SubjectViewSet, ChapterViewSet, SubfieldViewSet, TheoremViewSet,)
from authentication.views import LogoutView
from interactions.views import RevisionListViewSet, track_study_time

from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from authentication.views import LoginView, RegisterView
from notebooks.views import NotebookViewSet, NotebookSectionViewSet
from .views import health_check
from learningpath.views import (
    LearningPathViewSet, PathChapterViewSet,
    VideoViewSet, ChapterQuizViewSet
)


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
router.register(r'lessons', LessonViewSet, basename='lesson')
router.register(r'notebooks', NotebookViewSet, basename='notebook')
router.register(r'sections', NotebookSectionViewSet, basename='section')
router.register(r'exams', ExamViewSet)  # Add this line
router.register(r'learning-paths', LearningPathViewSet, basename='learningpath')
router.register(r'path-chapters', PathChapterViewSet, basename='pathchapter')
router.register(r'videos', VideoViewSet, basename='video')
router.register(r'chapter-quizzes', ChapterQuizViewSet, basename='chapterquiz')
router.register(r'revision-lists', RevisionListViewSet, basename='revisionlist')




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

    # Dashboard endpoints
    path('api/dashboard/stats/', get_user_dashboard_stats, name='dashboard-stats'),
    path('api/dashboard/learning-path/', get_learning_path_progress, name='learning-path-progress'),
    path('api/dashboard/recommended/', get_recommended_content, name='recommended-content'),

    # Content interaction
    path('api/content/<str:content_id>/view/', mark_content_viewed, name='mark-content-viewed'),

    # Study time tracking
    path('api/study-time/track/', track_study_time, name='track-study-time'),

    # Study statistics
    path('api/users/<str:username>/study-stats/', get_study_statistics, name='study-statistics'),

    path('health/', health_check, name='health_check'),

]