from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter

from config.sitemap import sitemap as sitemap_view
from config.seo import content_page as seo_content_page, listing_page as seo_listing_page, hub_page as seo_hub_page
from apps.caracteristics.hubs import hub_view, levels_view, national_years_view

from apps.things.views import ContentViewSet, SolutionViewSet, CommentViewSet, ProposedSolutionViewSet
from apps.users.views import (
    AvatarUploadView,
    get_current_user,
    UserProfileViewSet, UserSettingsView, mark_content_viewed, OnboardingView,
    TeacherInvitationView, TeacherInvitationRespondView,
    TeacherInvitationDeleteView, StudentInvitationsView,
)
from apps.users.views import PasswordChangeView, UpdateUserInfoView, UpdateMeView, DeleteAccountView, ModerationDeleteAccountView, ExportMyDataView
from apps.users.dashboard_views import (
    get_user_dashboard_stats,
    get_learning_path_progress,
    get_recommended_content,
)
from apps.users.study_stats_views import get_study_statistics
from apps.users.overview_views import dashboard_overview
from apps.users import admin_dashboard, login_diagnostic
from apps.users import usage as usage_views
from apps.users.my_stats import my_stats
from apps.users.progression import progression
from apps.things import reports as content_reports
from apps.ia import views as ia_views
from apps.things.verification import set_verification
from apps.things.views import get_content_recommendations, parse_pdf_view, skill_suggestions
from apps.caracteristics.views import (
    ClassLevelViewSet, SubjectViewSet, ChapterViewSet, SubfieldViewSet, TheoremViewSet,
    difficulty_counts, school_search,
)
from apps.authentication.views import (
    LogoutView, LoginView, GoogleLoginView, RegisterView,
    VerifyEmailView, ResendVerificationView,
    PasswordResetRequestView, PasswordResetConfirmView,
    ThrottledTokenObtainPairView, ThrottledTokenRefreshView,
)
from apps.interactions.views import RevisionListViewSet, track_study_time, get_taxonomy_time_stats
from apps.interactions.devoirs import UpcomingTestViewSet
from apps.notebooks.views import (
    NotebookViewSet, NotebookChapterViewSet, NotebookLessonEntryAnnotationViewSet
)
from apps.learningpath.views import (
    LearningPathViewSet, PathChapterViewSet,
    VideoViewSet, ChapterQuizViewSet
)
from apps.uploads.views import FileAttachmentViewSet
from apps.notifications import views as notification_views

router = DefaultRouter()
router.register(r'contents', ContentViewSet, basename='content')
router.register(r'class-levels', ClassLevelViewSet, basename='class-level')
router.register(r'subjects', SubjectViewSet, basename='subject')
router.register(r'chapters', ChapterViewSet, basename='chapter')
router.register(r'comments', CommentViewSet, basename='comment')
router.register(r'solutions', SolutionViewSet, basename='solution')
router.register(r'proposed-solutions', ProposedSolutionViewSet, basename='proposed-solution')
router.register(r'subfields', SubfieldViewSet, basename='subfield')
router.register(r'theorems', TheoremViewSet, basename='theorem')
router.register(r'users', UserProfileViewSet, basename='user-profile')
router.register(r'notebooks', NotebookViewSet, basename='notebook')
router.register(r'learning-paths', LearningPathViewSet, basename='learningpath')
router.register(r'path-chapters', PathChapterViewSet, basename='pathchapter')
router.register(r'videos', VideoViewSet, basename='video')
router.register(r'chapter-quizzes', ChapterQuizViewSet, basename='chapterquiz')
router.register(r'revision-lists', RevisionListViewSet, basename='revisionlist')
router.register(r'devoirs', UpcomingTestViewSet, basename='devoir')
router.register(r'files', FileAttachmentViewSet, basename='fileattachment')

urlpatterns = [
    path('admin/', admin.site.urls),
    # Plan du site (SEO), annoncé dans le robots.txt de fidni.fr
    path('sitemap.xml', sitemap_view, name='sitemap'),
    # Pages de contenu pré-remplies pour les moteurs de recherche (appelées par le nginx du frontend).
    path('seo/<str:section>/<int:pk>/', seo_content_page, name='seo-content'),
    # Accueil et listes (exercices, leçons, examens) pré-remplis pour les moteurs de recherche.
    path('seo/page/<str:name>/', seo_listing_page, name='seo-listing'),
    # Pages par niveau et par chapitre (exercices, cours, examens).
    path('seo/hub/<str:section>/<slug:level>/', seo_hub_page, name='seo-hub-level'),
    path('seo/hub/<str:section>/<slug:level>/<slug:chapter>/', seo_hub_page, name='seo-hub-chapter'),
    path('api/hubs/', hub_view, name='hubs'),
    path('api/hubs/niveaux/', levels_view, name='hubs-niveaux'),
    path('api/hubs/nationaux/', national_years_view, name='hubs-nationaux'),

    # Avatar upload - MUST be before router to avoid conflict with /api/users/<username>/
    path('api/users/avatar/', AvatarUploadView.as_view(), name='avatar-upload'),
    # Update own profile (no username in URL)
    path('api/users/me/', UpdateMeView.as_view(), name='update-me'),

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
    
    # Authentication
    path('api/auth/login/', LoginView.as_view(), name='login'),
    # Connexion (ou inscription) avec Google : jeton d'identité vérifié ici (apps/authentication/google.py).
    path('api/auth/google/', GoogleLoginView.as_view(), name='google-login'),
    path('api/auth/register/', RegisterView.as_view(), name='register'),
    path('api/auth/logout/', LogoutView.as_view(), name='logout'),
    path('api/auth/verify-email/', VerifyEmailView.as_view(), name='verify-email'),
    path('api/auth/resend-verification/', ResendVerificationView.as_view(), name='resend-verification'),
    path('api/auth/password-reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    path('api/auth/password-reset/confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('api/auth/user/', get_current_user, name='current-user'),
    path("api/token/", ThrottledTokenObtainPairView.as_view(), name="get_token"),
    path("api/token/refresh/", ThrottledTokenRefreshView.as_view(), name="refresh"),
    path('api/content/<str:content_id>/view/', mark_content_viewed, name='mark-content-viewed'),

    # Notifications (cloche de la barre du haut)
    path('api/notifications/', notification_views.notification_list, name='notifications'),
    path('api/notifications/non-lues/', notification_views.unread_count, name='notifications-unread'),
    path('api/notifications/lues/', notification_views.mark_read, name='notifications-read'),

    # Onboarding
    path('api/onboarding/', OnboardingView.as_view(), name='onboarding'),
    path('api/schools/', school_search, name='school-search'),

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
    path('api/auth/delete-account/', DeleteAccountView.as_view(), name='delete-account'),
    path('api/auth/my-data/', ExportMyDataView.as_view(), name='my-data'),
    path('api/moderation/users/<str:username>/delete/', ModerationDeleteAccountView.as_view(), name='moderation-delete-account'),

    # Dashboard endpoints
    path('api/dashboard/stats/', get_user_dashboard_stats, name='dashboard-stats'),
    path('api/dashboard/overview/', dashboard_overview, name='dashboard-overview'),
    # Pilotage (administrateurs) : inscrits, activité, statistiques d'usage.
    path('api/usage/', usage_views.record, name='usage'),
    path('api/pilotage/', admin_dashboard.overview, name='pilotage'),
    path('api/pilotage/utilisateurs/', admin_dashboard.users_list, name='pilotage-utilisateurs'),
    path('api/pilotage/utilisateurs/<int:pk>/', admin_dashboard.user_detail, name='pilotage-utilisateur'),
    # « Un membre n'arrive pas à se connecter » : comptes, blocage, journaux d'authentification.
    path('api/pilotage/connexion/', login_diagnostic.login_diagnostic, name='pilotage-connexion'),
    # Signalements d'erreurs sur les contenus : envoi (élèves connectés), suivi (administrateurs).
    path('api/contents/<int:content_id>/report/', content_reports.report_content, name='content-report'),
    # Correction « à vérifier » : validée (ou remise) par un administrateur depuis le site.
    path('api/contents/<int:content_id>/verification/', set_verification, name='content-verification'),
    path('api/pilotage/signalements/', content_reports.reports_list, name='pilotage-signalements'),
    path('api/pilotage/signalements/<int:pk>/', content_reports.report_update, name='pilotage-signalement'),
    # IA des administrateurs : import d'un document, correction d'un signalement (rien sans validation).
    path('api/pilotage/ia/', ia_views.jobs, name='pilotage-ia'),
    path('api/pilotage/ia/import/', ia_views.nouvel_import, name='pilotage-ia-import'),
    path('api/pilotage/ia/<int:pk>/', ia_views.job_detail, name='pilotage-ia-detail'),
    path('api/pilotage/ia/<int:pk>/corriger/', ia_views.job_corriger, name='pilotage-ia-corriger'),
    path('api/pilotage/ia/<int:pk>/relancer/', ia_views.job_relancer, name='pilotage-ia-relancer'),
    path('api/pilotage/ia/<int:pk>/publier/', ia_views.job_publier, name='pilotage-ia-publier'),
    path('api/pilotage/ia/<int:pk>/appliquer/', ia_views.job_appliquer, name='pilotage-ia-appliquer'),
    path('api/pilotage/ia/<int:pk>/rejeter/', ia_views.job_rejeter, name='pilotage-ia-rejeter'),
    path('api/pilotage/signalements/<int:pk>/ia/', ia_views.corriger_signalement, name='pilotage-signalement-ia'),
    path('api/pilotage/signalements/<int:pk>/ia/derniere/', ia_views.signalement_jobs,
         name='pilotage-signalement-ia-derniere'),
    # Statistiques de l'élève (page Statistiques) : période, matière, niveau.
    path('api/stats/me/', my_stats, name='my-stats'),
    path('api/stats/progression/', progression, name='progression'),
    path('api/dashboard/learning-path/', get_learning_path_progress, name='learning-path-progress'),
    path('api/dashboard/recommended/', get_recommended_content, name='recommended-content'),

    # Study time tracking
    path('api/study-time/track/', track_study_time, name='track-study-time'),
    path('api/study-time/taxonomy-stats/', get_taxonomy_time_stats, name='taxonomy-time-stats'),

    # Study statistics
    path('api/users/<str:username>/study-stats/', get_study_statistics, name='study-statistics'),

    # Filter counts
    path('api/difficulty-counts/', difficulty_counts, name='difficulty-counts'),
    path('api/skills/', skill_suggestions, name='skill-suggestions'),

    # Recommendations
    path('api/contents/<int:content_id>/recommendations/', get_content_recommendations, name='content-recommendations'),

    # PDF parsing
    path('api/parse-pdf/', parse_pdf_view, name='parse-pdf'),

    # Logging admin
    path('api/logs/', include('apps.logging.urls')),

    # Skill IQ assessments
    path('api/skill-assessments/', include('apps.skilliq.urls')),

    # Classrooms
    path('api/classrooms/', include('apps.classrooms.urls')),

    # Concours (ENSA / ENSAM / Médecine + tips + simulations)
    path('api/concours/', include('apps.concours.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
