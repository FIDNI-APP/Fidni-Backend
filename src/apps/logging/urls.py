"""
URL configuration for logging app
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ErrorLogViewSet, APILogViewSet, SystemEventViewSet,
    test_errors, test_post_error,
    track_pageview, update_page_time, track_interaction,
    track_abtest_impression, track_abtest_conversion, get_analytics_stats,
)

router = DefaultRouter()
router.register(r'errors', ErrorLogViewSet, basename='error')
router.register(r'api-logs', APILogViewSet, basename='apilog')
router.register(r'events', SystemEventViewSet, basename='event')

urlpatterns = [
    path('', include(router.urls)),
    path('test/errors/', test_errors, name='test-errors'),
    path('test/post-error/', test_post_error, name='test-post-error'),

    # Analytics endpoints
    path('analytics/pageview/', track_pageview, name='track-pageview'),
    path('analytics/pageview/update-time/', update_page_time, name='update-page-time'),
    path('analytics/interaction/', track_interaction, name='track-interaction'),
    path('analytics/abtest/impression/', track_abtest_impression, name='abtest-impression'),
    path('analytics/abtest/conversion/', track_abtest_conversion, name='abtest-conversion'),
    path('analytics/stats/', get_analytics_stats, name='analytics-stats'),
]
