"""
Settings package - auto-detects environment
"""
import os

# Default to development
ENVIRONMENT = os.getenv('DJANGO_ENV', 'development')

if ENVIRONMENT == 'production':
    from .prod import *
elif ENVIRONMENT == 'test':
    from .test import *
else:
    from .dev import *
