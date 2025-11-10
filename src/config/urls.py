from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.things.views import (
    ExerciseViewSet, SolutionViewSet,
    CommentViewSet, LessonViewSet, ExamViewSet
)
from apps.users.views import (
    get_current_user,
    UserProfileViewSet, UserSettingsView, mark_content_viewed, OnboardingView,
)
from apps.users.dashboard_views import (
    get_user_dashboard_stats,
    get_learning_path_progress,
    get_recommended_content,
)
from apps.users.study_stats_views import get_study_statistics
from apps.things.recommendation_views import (
    get_exercise_recommendations,
    get_lesson_recommendations,
    get_exam_recommendations
)
from apps.caracteristics.views import (
    ClassLevelViewSet, SubjectViewSet, ChapterViewSet, SubfieldViewSet, TheoremViewSet,
)
from apps.authentication.views import LogoutView, LoginView, RegisterView
from apps.interactions.views import RevisionListViewSet, track_study_time, get_taxonomy_time_stats
from apps.notebooks.views import (
    NotebookViewSet, NotebookChapterViewSet, NotebookLessonEntryAnnotationViewSet
)
from apps.learningpath.views import (
    LearningPathViewSet, PathChapterViewSet,
    VideoViewSet, ChapterQuizViewSet
)

from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

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
router.register(r'exams', ExamViewSet)
router.register(r'learning-paths', LearningPathViewSet, basename='learningpath')
router.register(r'path-chapters', PathChapterViewSet, basename='pathchapter')
router.register(r'videos', VideoViewSet, basename='video')
router.register(r'chapter-quizzes', ChapterQuizViewSet, basename='chapterquiz')
router.register(r'revision-lists', RevisionListViewSet, basename='revisionlist')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    
    # Nested routes for notebook chapters
    path('api/notebooks/<int:notebook_pk>/chapters/', 
         NotebookChapterViewSet.as_view({'get': 'list', 'post': 'create'}), 
         name='notebook-chapters'),
    path('api/notebooks/<int:notebook_pk>/chapters/<int:pk>/', 
         NotebookChapterViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), 
         name='notebook-chapter-detail'),
    path('api/notebooks/<int:notebook_pk>/chapters/<int:pk>/add_lesson/', 
         NotebookChapterViewSet.as_view({'post': 'add_lesson'}), 
         name='notebook-chapter-add-lesson'),
    path('api/notebooks/<int:notebook_pk>/chapters/<int:pk>/remove_lesson_page/', 
         NotebookChapterViewSet.as_view({'post': 'remove_lesson_page'}), 
         name='notebook-chapter-remove-lesson-page'),
    path('api/notebooks/<int:notebook_pk>/chapters/<int:pk>/update_notes/', 
         NotebookChapterViewSet.as_view({'post': 'update_notes'}), 
         name='notebook-chapter-update-notes'),
    
    # Routes for lesson entry annotations
    path('api/notebooks/<int:notebook_pk>/chapters/<int:chapter_pk>/lesson_entry/<int:lesson_entry_pk>/annotations/',
         NotebookLessonEntryAnnotationViewSet.as_view({'get': 'list', 'post': 'create'}),
         name='lesson-entry-annotations'),
    path("api-auth/", include("rest_framework.urls")),
    
    # Authentication
    path('api/auth/login/', LoginView.as_view(), name='login'),
    path('api/auth/register/', RegisterView.as_view(), name='register'),
    path('api/auth/logout/', LogoutView.as_view(), name='logout'),
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

    # Study time tracking
    path('api/study-time/track/', track_study_time, name='track-study-time'),
    path('api/study-time/taxonomy-stats/', get_taxonomy_time_stats, name='taxonomy-time-stats'),

    # Study statistics
    path('api/users/<str:username>/study-stats/', get_study_statistics, name='study-statistics'),

    # Recommendations
    path('api/exercises/<int:exercise_id>/recommendations/', get_exercise_recommendations, name='exercise-recommendations'),
    path('api/lessons/<int:lesson_id>/recommendations/', get_lesson_recommendations, name='lesson-recommendations'),
    path('api/exams/<int:exam_id>/recommendations/', get_exam_recommendations, name='exam-recommendations'),
]
