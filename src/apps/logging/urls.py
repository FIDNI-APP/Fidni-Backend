"""
URL configuration for logging app
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .client_errors import client_error
from .views import (
    ErrorLogViewSet, APILogViewSet, SystemEventViewSet,
    test_errors, test_post_error,
    get_analytics_stats,
)
from .csp import csp_report

router = DefaultRouter()
router.register(r'errors', ErrorLogViewSet, basename='error')
router.register(r'api-logs', APILogViewSet, basename='apilog')
router.register(r'events', SystemEventViewSet, basename='event')

urlpatterns = [
    path('client-errors/', client_error, name='client-error'),
    path('', include(router.urls)),
    path('test/errors/', test_errors, name='test-errors'),
    path('test/post-error/', test_post_error, name='test-post-error'),

    # Suivi d'audience : seulement la lecture des statistiques (équipe). Les routes d'écriture anonymes
    # (pages vues, interactions, tests A/B) n'étaient appelées par aucun client : retirées le 07/11/2026.
    path('analytics/stats/', get_analytics_stats, name='analytics-stats'),
    # Rapports de la politique de sécurité du contenu (CSP) envoyés par les navigateurs.
    path('csp/', csp_report, name='csp-report'),
]
