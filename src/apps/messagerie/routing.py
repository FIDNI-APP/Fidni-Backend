from django.urls import path

from .consumers import MessagerieConsumer

websocket_urlpatterns = [
    path('ws/', MessagerieConsumer.as_asgi()),
]
