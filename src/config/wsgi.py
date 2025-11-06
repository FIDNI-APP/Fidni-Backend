"""
WSGI config for FIDNI project.
"""
import os
import sys
from pathlib import Path
from django.core.wsgi import get_wsgi_application

# Add src to path
src_path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(src_path))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()
