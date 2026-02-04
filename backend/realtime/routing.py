from django.urls import re_path

from .consumers import LobbyConsumer, RoomConsumer

websocket_urlpatterns = [
    re_path(r"ws/rooms/(?P<code>[A-Za-z0-9]+)/?$", RoomConsumer.as_asgi()),
    re_path(r"ws/lobby/?$", LobbyConsumer.as_asgi()),
]
