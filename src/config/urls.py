from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter

from apps.things.views import ContentViewSet, SolutionViewSet, CommentViewSet
from apps.users.views import (
    AvatarUploadView,
    get_current_user,
    UserProfileViewSet, UserSettingsView, mark_content_viewed, OnboardingView,
    TeacherInvitationView, TeacherInvitationRespondView,
    TeacherInvitationDeleteView, StudentInvitationsView,
)
from apps.users.views import PasswordChangeView, UpdateUserInfoView
from apps.users.dashboard_views import (
    get_user_dashboard_stats,
    get_learning_path_progress,
    get_recommended_content,
)
from apps.users.study_stats_views import get_study_statistics
from apps.things.views import get_content_recommendations, parse_pdf_view
from apps.caracteristics.views import (
    ClassLevelViewSet, SubjectViewSet, ChapterViewSet, SubfieldViewSet, TheoremViewSet,
    difficulty_counts,
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
from apps.uploads.views import FileAttachmentViewSet
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

router = DefaultRouter()
router.register(r'contents', ContentViewSet, basename='content')
router.register(r'class-levels', ClassLevelViewSet, basename='class-level')
router.register(r'subjects', SubjectViewSet, basename='subject')
router.register(r'chapters', ChapterViewSet, basename='chapter')
router.register(r'comments', CommentViewSet, basename='comment')
router.register(r'solutions', SolutionViewSet, basename='solution')
router.register(r'subfields', SubfieldViewSet, basename='subfield')
router.register(r'theorems', TheoremViewSet, basename='theorem')
router.register(r'users', UserProfileViewSet, basename='user-profile')
router.register(r'notebooks', NotebookViewSet, basename='notebook')
router.register(r'learning-paths', LearningPathViewSet, basename='learningpath')
router.register(r'path-chapters', PathChapterViewSet, basename='pathchapter')
router.register(r'videos', VideoViewSet, basename='video')
router.register(r'chapter-quizzes', ChapterQuizViewSet, basename='chapterquiz')
router.register(r'revision-lists', RevisionListViewSet, basename='revisionlist')
router.register(r'files', FileAttachmentViewSet, basename='fileattachment')

urlpatterns = [
    path('admin/', admin.site.urls),

    # Avatar upload - MUST be before router to avoid conflict with /api/users/<username>/
    path('api/users/avatar/', AvatarUploadView.as_view(), name='avatar-upload'),

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

    # Onboarding
    path('api/onboarding/', OnboardingView.as_view(), name='onboarding'),

    # Teacher invitations
    path('api/teacher-invitations/', TeacherInvitationView.as_view(), name='teacher-invitations'),
    path('api/teacher-invitations/<int:invitation_id>/respond/', TeacherInvitationRespondView.as_view(), name='teacher-invitation-respond'),
    path('api/teacher-invitations/<int:invitation_id>/', TeacherInvitationDeleteView.as_view(), name='teacher-invitation-delete'),
    path('api/student-invitations/', StudentInvitationsView.as_view(), name='student-invitations'),

    # Settings
    path('api/settings/', UserSettingsView.as_view(), name='user-settings'),
    path('api/users/<str:username>/onboarding-status/', UserProfileViewSet.as_view({'get': 'onboarding_status'}), name='onboarding-status'),

    # User endpoints
    path('api/auth/settings/', UserSettingsView.as_view(), name='user-settings'),
    path('api/auth/password/change/', PasswordChangeView.as_view(), name='password-change'),
    path('api/auth/user/update/', UpdateUserInfoView.as_view(), name='user-update'),

    # Dashboard endpoints
    path('api/dashboard/stats/', get_user_dashboard_stats, name='dashboard-stats'),
    path('api/dashboard/learning-path/', get_learning_path_progress, name='learning-path-progress'),
    path('api/dashboard/recommended/', get_recommended_content, name='recommended-content'),

    # Study time tracking
    path('api/study-time/track/', track_study_time, name='track-study-time'),
    path('api/study-time/taxonomy-stats/', get_taxonomy_time_stats, name='taxonomy-time-stats'),

    # Study statistics
    path('api/users/<str:username>/study-stats/', get_study_statistics, name='study-statistics'),

    # Filter counts
    path('api/difficulty-counts/', difficulty_counts, name='difficulty-counts'),

    # Recommendations
    path('api/contents/<int:content_id>/recommendations/', get_content_recommendations, name='content-recommendations'),

    # PDF parsing
    path('api/parse-pdf/', parse_pdf_view, name='parse-pdf'),

    # Logging admin
    path('api/logs/', include('apps.logging.urls')),

    # Skill IQ assessments
    path('api/skill-assessments/', include('apps.skilliq.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
