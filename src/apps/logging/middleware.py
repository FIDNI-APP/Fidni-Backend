"""
Middleware for error tracking and API logging
"""
import time
import traceback as tb
import json
from django.utils.deprecation import MiddlewareMixin
from .models import ErrorLog, APILog
import logging

logger = logging.getLogger("django")


# Jamais écrits en base : mots de passe, jetons, liens de réinitialisation.
SENSITIVE_KEYS = {
    'password', 'password1', 'password2', 'confirmpassword', 'confirm_password',
    'current_password', 'new_password', 'old_password',
    'token', 'access', 'refresh', 'uid', 'secret', 'api_key',
}


def redact(value):
    """Copie de `value` (dict/list) où les champs sensibles sont masqués."""
    if isinstance(value, dict):
        return {k: ('[masqué]' if str(k).lower() in SENSITIVE_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def redact_body(raw: str):
    """Corps de requête/réponse masqué ; un corps illisible (formulaire, fichier) n'est pas gardé."""
    try:
        return json.dumps(redact(json.loads(raw)), ensure_ascii=False)[:5000]
    except (ValueError, TypeError):
        return '[corps non JSON non conservé]'


def get_client_ip(request):
    """Extract client IP from request"""
    cf_ip = request.META.get('HTTP_CF_CONNECTING_IP')
    if cf_ip:
        return cf_ip.strip()
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


class ErrorTrackingMiddleware(MiddlewareMixin):
    """Middleware to capture and log exceptions"""

    def process_exception(self, request, exception):
        """Called when view raises exception"""
        try:
            # Get user if authenticated
            # DRF met request.user à None pour un visiteur (UNAUTHENTICATED_USER = None).
            user = request.user if getattr(request.user, "is_authenticated", False) else None

            # Get request data
            request_data = {}
            if request.method == 'GET':
                request_data = dict(request.GET)
            elif request.method == 'POST':
                try:
                    if request.content_type == 'application/json':
                        request_data = json.loads(request.body.decode('utf-8'))
                    else:
                        request_data = dict(request.POST)
                except:
                    request_data = {'error': 'Could not parse request body'}
            request_data = redact(request_data)

            # Determine severity based on exception type
            severity = 'error'
            if isinstance(exception, (ValueError, TypeError, KeyError)):
                severity = 'warning'
            elif isinstance(exception, PermissionError):
                severity = 'warning'

            # Create or update error log

            # Try to find existing error with same signature
            existing_error = ErrorLog.objects.filter(
                exception_type=type(exception).__name__,
                endpoint=request.path,
                status__in=['new', 'investigating']
            ).first()

            if existing_error:
                existing_error.increment_count()
            else:
                ErrorLog.objects.create(
                    severity=severity,
                    message=str(exception),
                    exception_type=type(exception).__name__,
                    traceback=tb.format_exc(),
                    endpoint=request.path,
                    method=request.method,
                    user=user,
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    request_data=request_data,
                )

        except Exception as e:
            # Don't let logging errors break the app
            print(f"Error logging failed: {e}")

        # Return None to continue with default exception handling
        return None


class APILoggingMiddleware(MiddlewareMixin):
    """Middleware to log API requests and responses"""

    # Endpoints to exclude from logging
    EXCLUDE_PATHS = [
        '/admin/',
        '/static/',
        '/media/',
        '/api/logs/',  # Don't log the logging endpoints themselves
    ]

    def should_log(self, path):
        """Check if this path should be logged"""
        return not any(path.startswith(exclude) for exclude in self.EXCLUDE_PATHS)

    def _purge_old_logs_daily(self):
        # Durée de conservation des journaux (RGPD) : purge au plus une fois par jour.
        from django.core.cache import cache
        if cache.add('fidni:logs-purged', True, timeout=24 * 3600):
            try:
                from apps.users.legal import purge_old_logs
                purge_old_logs()
            except Exception:  # la purge ne doit jamais faire échouer une requête
                logger.exception('Purge des journaux impossible')

    def process_request(self, request):
        self._purge_old_logs_daily()
        """Mark request start time"""
        if not hasattr(request, '_start_time'):
            request._start_time = time.time()
        return None

    def process_response(self, request, response):
        """Log API request after response"""
        if not self.should_log(request.path):
            return response

        try:
            # Calculate response time
            if not hasattr(request, '_start_time'):
                request._start_time = time.time()
            response_time = int((time.time() - request._start_time) * 1000)

            # Get user - check if request.user exists first
            user = None
            if hasattr(request, 'user') and request.user and hasattr(request.user, 'is_authenticated') and request.user.is_authenticated:
                user = request.user

            # Get request body
            request_body = None
            if request.method in ['POST', 'PUT', 'PATCH']:
                try:
                    if hasattr(request, 'body'):
                        request_body = redact_body(request.body.decode('utf-8'))
                except:
                    pass

            # Get query params
            query_params = redact(dict(request.GET)) if request.GET else None

            # Get response body (only for errors or if explicitly enabled)
            response_body = None
            if response.status_code >= 400:
                try:
                    if hasattr(response, 'content'):
                        response_body = redact_body(response.content.decode('utf-8'))
                except:
                    pass

            # Only log if response time is significant or status is error
            if response_time > 1000 or response.status_code >= 400:
                APILog.objects.create(
                    method=request.method,
                    endpoint=request.path,
                    user=user,
                    ip_address=get_client_ip(request),
                    status_code=response.status_code,
                    response_time_ms=response_time,
                    request_body=request_body,
                    response_body=response_body,
                    query_params=query_params,
                )

        except Exception as e:
            import traceback
            print(f"API logging failed: {e}")
            print(traceback.format_exc())

        return response
