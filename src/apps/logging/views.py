from rest_framework import viewsets, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Count, Q, Avg, F
from django.utils import timezone
from django.http import Http404
from datetime import timedelta
import time
from .models import ErrorLog, APILog, SystemEvent, PageView, UserInteraction, UserSession, ABTestVariant
from .serializers import (
    ErrorLogSerializer, APILogSerializer, SystemEventSerializer, ErrorLogStatsSerializer,
    PageViewSerializer, UserInteractionSerializer,
    ABTestImpressionSerializer, ABTestConversionSerializer, AnalyticsStatsSerializer,
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

def _get_or_create_session(session_id, user=None, ip_address=None, user_agent=None):
    session, created = UserSession.objects.get_or_create(
        session_id=session_id,
        defaults={
            'user': user if user and user.is_authenticated else None,
            'ip_address': ip_address,
            'user_agent': user_agent,
        }
    )
    if not created:
        session.last_activity = timezone.now()
        session.save(update_fields=['last_activity'])
    return session


@api_view(['POST'])
@permission_classes([AllowAny])
def track_pageview(request):
    serializer = PageViewSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    user = request.user if request.user.is_authenticated else None
    session = _get_or_create_session(
        session_id=data['session_id'], user=user,
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT'),
    )
    PageView.objects.create(
        path=data['path'], page_title=data.get('page_title'),
        referrer=data.get('referrer'), user=user,
        session_id=data['session_id'],
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT'),
        device_type=data.get('device_type'), browser=data.get('browser'), os=data.get('os'),
    )
    session.pages_viewed = F('pages_viewed') + 1
    session.save(update_fields=['pages_viewed'])
    return Response({'status': 'tracked'}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def update_page_time(request):
    path = request.data.get('path')
    session_id = request.data.get('session_id')
    time_on_page = request.data.get('time_on_page')
    if path and session_id and time_on_page:
        PageView.objects.filter(path=path, session_id=session_id).order_by('-timestamp').first().update(time_on_page=time_on_page)
    return Response({'status': 'updated'})


@api_view(['POST'])
@permission_classes([AllowAny])
def track_interaction(request):
    serializer = UserInteractionSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    user = request.user if request.user.is_authenticated else None
    UserInteraction.objects.create(
        interaction_type=data['interaction_type'], element_id=data.get('element_id'),
        element_text=data.get('element_text'), page_path=data['page_path'],
        variant=data.get('variant'), user=user,
        session_id=data['session_id'], metadata=data.get('metadata'),
    )
    session = UserSession.objects.filter(session_id=data['session_id']).first()
    if session:
        session.interactions_count = F('interactions_count') + 1
        session.save(update_fields=['interactions_count'])
    return Response({'status': 'tracked'}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def track_abtest_impression(request):
    serializer = ABTestImpressionSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    variant, _ = ABTestVariant.objects.get_or_create(test_name=data['test_name'], variant_name=data['variant_name'])
    variant.impressions = F('impressions') + 1
    variant.save(update_fields=['impressions'])
    return Response({'status': 'tracked'}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def track_abtest_conversion(request):
    serializer = ABTestConversionSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    variant = ABTestVariant.objects.filter(test_name=data['test_name'], variant_name=data['variant_name']).first()
    if variant:
        variant.conversions = F('conversions') + 1
        variant.save(update_fields=['conversions'])
        variant.refresh_from_db()
        variant.calculate_conversion_rate()
    return Response({'status': 'tracked'}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([AllowAny])
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
@permission_classes([AllowAny])
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
@permission_classes([AllowAny])
def test_post_error(request):
    action_type = request.data.get('action')
    if action_type == 'fail':
        return Response({'error': 'POST request failed', 'data_received': request.data}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    elif action_type == 'crash':
        raise ValueError("Simulated crash in POST request")
    return Response({'message': 'POST successful', 'data': request.data})
