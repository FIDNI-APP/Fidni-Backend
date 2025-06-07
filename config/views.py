# In your main app's views.py (or create a new one)
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import json
from django.db import connection
from django.core.cache import cache
import os
from django.utils import timezone
from datetime import datetime

@csrf_exempt
@require_http_methods(["GET"])
def health_check(request):
    """
    Health check endpoint for load balancers and monitoring
    """
    try:
        # Check database connection
        db_status = "ok"
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception as e:
            db_status = f"error: {str(e)}"
        
        # Check if we're using SQLite or PostgreSQL
        db_engine = connection.settings_dict['ENGINE']
        
        health_data = {
            "status": "healthy",
            "timestamp": str(timezone.now()) if 'timezone' in globals() else str(datetime.now()),
            "database": {
                "status": db_status,
                "engine": db_engine
            },
            "environment": os.environ.get('DJANGO_SETTINGS_MODULE', 'unknown'),
            "version": "1.0.0"  # You can version your app
        }
        
        # If database has issues, return 503
        if "error" in db_status:
            return JsonResponse(health_data, status=503)
        
        return JsonResponse(health_data, status=200)
        
    except Exception as e:
        return JsonResponse({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": str(datetime.now())
        }, status=503)