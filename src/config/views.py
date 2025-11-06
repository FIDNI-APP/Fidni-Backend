from django.http import JsonResponse, FileResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import json
from django.db import connection
from django.core.cache import cache
import os
from django.utils import timezone
from datetime import datetime
import tempfile
import pdfkit

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
            "error": str(e)
        }, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def generate_pdf(request):
    try:
        # Parse the JSON body
        data = json.loads(request.body)
        html_content = data.get('html')
        
        if not html_content:
            return JsonResponse({'error': 'Missing HTML content'}, status=400)

        # Import pdfkit at the top of the file
import pdfkit

# Define PDF options
        options = {
            'page-size': 'A4',
            'margin-top': '2cm',
            'margin-right': '2cm',
            'margin-bottom': '2cm',
            'margin-left': '2cm',
            'encoding': 'UTF-8',
            'no-outline': None,
            'enable-local-file-access': None,
            'javascript-delay': 1000,  # Wait for KaTeX to render
        }

        try:
            # Generate PDF directly from HTML
            pdf = pdfkit.from_string(html_content, False, options=options)
            
            # Return the PDF
            response = HttpResponse(pdf, content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="revision-list.pdf"'
            return response

        finally:
            # Clean up temporary files
            os.unlink(html_path)
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'PDF generation failed: {str(e)}'}, status=500)
            "timestamp": str(datetime.now())
        }, status=503)