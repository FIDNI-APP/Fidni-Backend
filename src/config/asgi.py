"""
ASGI de Fidni : le WebSocket /ws/ de la messagerie et des appels (apps/messagerie), servi par uvicorn
(entrypoint.sh, 127.0.0.1:8001, derrière le nginx du conteneur). Les requêtes HTTP restent sur gunicorn (wsgi.py) ;
elles passent aussi ici en développement (uvicorn seul).
"""
import os
import sys
from pathlib import Path

from django.core.asgi import get_asgi_application

src_path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(src_path))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402  (après django.setup())

from apps.messagerie.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': URLRouter(websocket_urlpatterns),
})
