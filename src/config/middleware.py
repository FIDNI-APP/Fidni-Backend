"""Middleware maison — santé ALB."""
from django.http import HttpResponse


class HealthCheckMiddleware:
    """Répond à /healthz AVANT la validation ALLOWED_HOSTS.

    Le health checker de l'ALB appelle la tâche par son IP privée (Host: <ip>),
    que Django rejetterait en 400. Placé en tête de MIDDLEWARE, ce middleware
    court-circuite uniquement ce chemin — tout le reste garde un ALLOWED_HOSTS strict.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.META.get('PATH_INFO') in ('/healthz', '/healthz/'):
            return HttpResponse('ok')
        return self.get_response(request)
