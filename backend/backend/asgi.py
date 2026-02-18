"""ASGI config for backend project."""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django
from django.conf import settings
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator, OriginValidator
from django.core.asgi import get_asgi_application

django.setup()

from realtime.auth import JWTAuthMiddleware
from realtime.routing import websocket_urlpatterns

django_asgi_app = get_asgi_application()

websocket_application = JWTAuthMiddleware(URLRouter(websocket_urlpatterns))
if settings.WS_ALLOWED_ORIGINS:
    websocket_application = OriginValidator(websocket_application, settings.WS_ALLOWED_ORIGINS)
else:
    websocket_application = AllowedHostsOriginValidator(websocket_application)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": websocket_application,
    }
)



