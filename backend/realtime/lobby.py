from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models import Count, Q

from .models import Room

MAX_PLAYERS = 8


def rooms_snapshot():
    rooms = (
        Room.objects.filter(is_active=True)
        .annotate(active_count=Count("members", filter=Q(members__is_active=True)))
        .order_by("-created_at")
    )
    return [
        {
            "code": room.code,
            "active_count": room.active_count,
            "max_players": MAX_PLAYERS,
            "is_full": room.active_count >= MAX_PLAYERS,
            "is_private": room.is_private,
        }
        for room in rooms
    ]


def broadcast_rooms_snapshot():
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    async_to_sync(channel_layer.group_send)(
        "rooms_lobby",
        {
            "type": "rooms_list",
            "rooms": rooms_snapshot(),
        },
    )
