from rest_framework import viewsets, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Count, Avg
from django.utils import timezone
from django.http import Http404
from datetime import timedelta
import time
from .models import ErrorLog, APILog, SystemEvent, PageView, UserInteraction, UserSession
from .serializers import (
    ErrorLogSerializer, APILogSerializer, SystemEventSerializer, ErrorLogStatsSerializer,
    AnalyticsStatsSerializer,
)


class IsAdminUser(permissions.BasePermission):
    """Only allow admin users to access logs"""

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_staff


class ErrorLogViewSet(viewsets.ModelViewSet):
    """ViewSet for error logs"""
    queryset = ErrorLog.objects.all()
    serializer_class = ErrorLogSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ['severity', 'status', 'endpoint', 'exception_type']
    search_fields = ['message', 'exception_type', 'endpoint']
    ordering_fields = ['last_seen', 'first_seen', 'count', 'severity']
    ordering = ['-last_seen']

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get error statistics"""
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        stats = {
            'total_errors': ErrorLog.objects.count(),
            'new_errors': ErrorLog.objects.filter(status='new').count(),
            'critical_errors': ErrorLog.objects.filter(severity='critical', status__in=['new', 'investigating']).count(),
            'errors_today': ErrorLog.objects.filter(first_seen__gte=today_start).count(),
            'errors_by_severity': dict(
                ErrorLog.objects.values('severity').annotate(count=Count('id')).values_list('severity', 'count')
            ),
            'errors_by_endpoint': list(
                ErrorLog.objects.values('endpoint')
                .annotate(count=Count('id'))
                .order_by('-count')[:10]
            ),
            'recent_errors': ErrorLog.objects.all()[:10]
        }

        serializer = ErrorLogStatsSerializer(stats)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Mark error as resolved"""
        error = self.get_object()
        error.status = 'resolved'
        error.resolved_at = timezone.now()
        error.resolved_by = request.user
        error.notes = request.data.get('notes', '')
        error.save()
        return Response({'status': 'resolved'})

    @action(detail=True, methods=['post'])
    def ignore(self, request, pk=None):
        """Mark error as ignored"""
        error = self.get_object()
        error.status = 'ignored'
        error.save()
        return Response({'status': 'ignored'})

    @action(detail=False, methods=['post'])
    def bulk_resolve(self, request):
        """Bulk resolve errors"""
        ids = request.data.get('ids', [])
        ErrorLog.objects.filter(id__in=ids).update(
            status='resolved',
            resolved_at=timezone.now(),
            resolved_by=request.user
        )
        return Response({'status': f'resolved {len(ids)} errors'})


class APILogViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for API logs (read-only)"""
    queryset = APILog.objects.all()
    serializer_class = APILogSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ['method', 'endpoint', 'status_code']
    search_fields = ['endpoint', 'request_body', 'response_body']
    ordering_fields = ['timestamp', 'response_time_ms', 'status_code']
    ordering = ['-timestamp']

    @action(detail=False, methods=['get'])
    def slow_requests(self, request):
        """Get slow API requests (>2s)"""
        slow_logs = APILog.objects.filter(response_time_ms__gte=2000).order_by('-response_time_ms')[:50]
        serializer = self.get_serializer(slow_logs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def error_requests(self, request):
        """Get failed API requests (4xx, 5xx)"""
        error_logs = APILog.objects.filter(status_code__gte=400).order_by('-timestamp')[:100]
        serializer = self.get_serializer(error_logs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['delete'])
    def cleanup(self, request):
        """Delete old logs (older than 30 days)"""
        cutoff_date = timezone.now() - timedelta(days=30)
        deleted_count = APILog.objects.filter(timestamp__lt=cutoff_date).delete()[0]
        return Response({'deleted': deleted_count})


class SystemEventViewSet(viewsets.ModelViewSet):
    """ViewSet for system events"""
    queryset = SystemEvent.objects.all()
    serializer_class = SystemEventSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ['event_type']
    search_fields = ['title', 'description']
    ordering_fields = ['timestamp']
    ordering = ['-timestamp']


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAdminUser])  # réservé aux admins (était ouvert à tous)
def get_analytics_stats(request):
    now = timezone.now()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)
    active_sessions = UserSession.objects.filter(last_activity__gte=last_24h)
    total_sessions = UserSession.objects.filter(started_at__gte=last_7d).count()
    total_page_views = PageView.objects.filter(timestamp__gte=last_7d).count()
    avg_duration = UserSession.objects.filter(started_at__gte=last_7d, ended_at__isnull=False).aggregate(avg=Avg('duration_seconds'))['avg'] or 0
    single_page_sessions = UserSession.objects.filter(started_at__gte=last_7d, pages_viewed=1).count()
    bounce_rate = (single_page_sessions / total_sessions * 100) if total_sessions > 0 else 0
    hourly_traffic = [
        {'hour': (now - timedelta(hours=i+1)).strftime('%H:00'),
         'count': PageView.objects.filter(timestamp__gte=now - timedelta(hours=i+1), timestamp__lt=now - timedelta(hours=i)).count()}
        for i in range(24)
    ]
    stats = {
        'active_users': active_sessions.filter(user__isnull=False).values('user').distinct().count(),
        'total_sessions': total_sessions,
        'total_page_views': total_page_views,
        'avg_session_duration': round(avg_duration, 1),
        'bounce_rate': round(bounce_rate, 1),
        'top_pages': list(PageView.objects.filter(timestamp__gte=last_7d).values('path').annotate(count=Count('id')).order_by('-count')[:10]),
        'top_interactions': list(UserInteraction.objects.filter(timestamp__gte=last_7d).values('element_id', 'interaction_type').annotate(count=Count('id')).order_by('-count')[:10]),
        'device_breakdown': dict(PageView.objects.filter(timestamp__gte=last_7d).values('device_type').annotate(count=Count('id')).values_list('device_type', 'count')),
        'browser_breakdown': dict(PageView.objects.filter(timestamp__gte=last_7d).values('browser').annotate(count=Count('id')).values_list('browser', 'count')),
        'hourly_traffic': list(reversed(hourly_traffic)),
    }
    serializer = AnalyticsStatsSerializer(stats)
    return Response(serializer.data)


# ---------------------------------------------------------------------------
# Test / debug endpoints
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAdminUser])  # réservé aux admins (était ouvert à tous)
def test_errors(request):
    error_type = request.GET.get('type', 'none')
    if error_type == 'none':
        return Response({'message': 'Error test endpoint', 'available_types': ['?type=500', '?type=404', '?type=403', '?type=400', '?type=division', '?type=attribute', '?type=key', '?type=type', '?type=slow']})
    elif error_type == '500':
        return Response({'error': 'Internal Server Error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    elif error_type == '404':
        raise Http404("Simulated 404")
    elif error_type == '403':
        return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
    elif error_type == '400':
        return Response({'error': 'Bad Request'}, status=status.HTTP_400_BAD_REQUEST)
    elif error_type == 'division':
        return Response({'result': 1 / 0})
    elif error_type == 'attribute':
        return Response({'value': None.some_attribute})
    elif error_type == 'key':
        return Response({'value': {}['nonexistent_key']})
    elif error_type == 'type':
        return Response({'result': "string" + 123})
    elif error_type == 'slow':
        time.sleep(3)
        return Response({'message': 'Slow response (3s)'})
    return Response({'error': 'Unknown error type'}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAdminUser])  # réservé aux admins (était ouvert à tous)
def test_post_error(request):
    action_type = request.data.get('action')
    if action_type == 'fail':
        return Response({'error': 'POST request failed', 'data_received': request.data}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    elif action_type == 'crash':
        raise ValueError("Simulated crash in POST request")
    return Response({'message': 'POST successful', 'data': request.data})
