"""ASGI config for backend project."""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

django.setup()

from realtime.auth import JWTAuthMiddleware
from realtime.routing import websocket_urlpatterns

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
    }
)



