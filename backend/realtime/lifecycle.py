from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

try:
    import redis
except Exception:  # pragma: no cover - optional runtime dependency guard
    redis = None

from .models import Room, RoomMember


def _room_history_keys(code: str) -> set[str]:
    return {
        f"room:{code}:chat",
        f"room:{code}:draw",
        f"room:{code}:game_state",
        f"room:{code}:timer_owner",
    }


def _cleanup_room_redis_keys(codes: list[str]) -> int:
    if not codes:
        return 0
    if redis is None:
        return 0
    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        client.ping()
    except Exception:
        return 0

    keys_to_delete: set[str] = set()
    for code in codes:
        keys_to_delete.update(_room_history_keys(code))
        pattern = f"room:{code}:connections:*"
        for key in client.scan_iter(match=pattern):
            keys_to_delete.add(key)
    if not keys_to_delete:
        return 0
    try:
        return int(client.delete(*list(keys_to_delete)))
    except Exception:
        return 0


def sync_room_empty_state(room_id: int) -> bool:
    room = Room.objects.filter(id=room_id, is_active=True).first()
    if not room:
        return False

    active_count = RoomMember.objects.filter(room_id=room_id, is_active=True).count()
    if active_count > 0:
        if room.empty_since is not None:
            room.empty_since = None
            room.save(update_fields=["empty_since"])
        return False

    if room.empty_since is None:
        room.empty_since = timezone.now()
        room.save(update_fields=["empty_since"])
    return True


def cleanup_inactive_rooms(empty_minutes: int | None = None) -> int:
    configured_minutes = (
        getattr(settings, "EMPTY_ROOM_DELETE_MINUTES", 1)
        if empty_minutes is None
        else empty_minutes
    )
    retention_minutes = max(
        0,
        int(configured_minutes),
    )
    now = timezone.now()

    # Backfill marker for rooms that are currently empty but missing empty_since.
    Room.objects.filter(is_active=True, empty_since__isnull=True).annotate(
        active_count=Count("members", filter=Q(members__is_active=True))
    ).filter(active_count=0).update(empty_since=now)

    cutoff = now - timedelta(minutes=retention_minutes)
    stale_rooms = (
        Room.objects.filter(is_active=True, empty_since__isnull=False, empty_since__lte=cutoff)
        .annotate(active_count=Count("members", filter=Q(members__is_active=True)))
        .filter(active_count=0)
        .distinct()
    )
    stale_codes = list(stale_rooms.values_list("code", flat=True))
    if not stale_codes:
        return 0

    stale_rooms.delete()
    _cleanup_room_redis_keys(stale_codes)
    return len(stale_codes)
