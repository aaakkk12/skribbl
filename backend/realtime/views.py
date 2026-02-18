import random
import string

from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from authapp.models import Friendship, PlayerProfile, UserStatus
from .models import Room, RoomInvite, RoomMember
from .serializers import (
    CreateRoomSerializer,
    JoinRoomSerializer,
    RespondInviteSerializer,
    RoomCodeSerializer,
    SendInviteSerializer,
)
from .lobby import broadcast_rooms_snapshot, rooms_snapshot
from .lifecycle import cleanup_inactive_rooms, sync_room_empty_state

CODE_LENGTH = 6
MAX_PLAYERS = 8
User = get_user_model()


def generate_code() -> str:
    for _ in range(20):
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=CODE_LENGTH))
        if not Room.objects.filter(code=code).exists():
            return code
    raise RuntimeError("Unable to generate unique room code.")


class CreateRoomView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "room_create"

    def post(self, request):
        cleanup_inactive_rooms()
        serializer = CreateRoomSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        visibility = serializer.validated_data["visibility"]
        password = (serializer.validated_data.get("password") or "").strip()
        with transaction.atomic():
            code = generate_code()
            room = Room.objects.create(
                code=code,
                owner=request.user,
                is_private=(visibility == "private"),
            )
            if visibility == "private":
                room.set_password(password)
                room.save(update_fields=["password_hash"])
            RoomMember.objects.create(room=room, user=request.user, is_active=True)
            sync_room_empty_state(room.id)
        broadcast_rooms_snapshot()
        return Response({"code": room.code}, status=status.HTTP_201_CREATED)


class JoinRoomView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "room_join"

    def post(self, request):
        cleanup_inactive_rooms()
        serializer = JoinRoomSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data["code"].strip().upper()
        password = (serializer.validated_data.get("password") or "").strip()

        room = Room.objects.filter(code=code, is_active=True).first()
        if not room:
            return Response(
                {"detail": "Room not found."}, status=status.HTTP_404_NOT_FOUND
            )

        status_row, _ = UserStatus.objects.get_or_create(user=request.user)
        if status_row.is_deleted:
            return Response(
                {"detail": "Account is archived. Contact admin."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if status_row.is_banned:
            return Response(
                {"detail": "Your account is banned."},
                status=status.HTTP_403_FORBIDDEN,
            )
        profile, _ = PlayerProfile.objects.get_or_create(user=request.user)
        if not (profile.display_name or "").strip():
            return Response(
                {"detail": "Complete your player profile first."},
                status=status.HTTP_403_FORBIDDEN,
            )

        member = RoomMember.objects.filter(room=room, user=request.user).first()
        if member and member.is_active:
            sync_room_empty_state(room.id)
            broadcast_rooms_snapshot()
            return Response({"code": room.code}, status=status.HTTP_200_OK)

        if room.is_private:
            if not password or not room.check_password(password):
                return Response(
                    {"detail": "Room password is incorrect."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        active_count = RoomMember.objects.filter(room=room, is_active=True).count()
        if active_count >= MAX_PLAYERS:
            return Response(
                {"detail": "Room is full."}, status=status.HTTP_400_BAD_REQUEST
            )

        if member:
            member.is_active = True
            member.save(update_fields=["is_active"])
        else:
            RoomMember.objects.create(room=room, user=request.user, is_active=True)

        sync_room_empty_state(room.id)
        broadcast_rooms_snapshot()
        return Response({"code": room.code}, status=status.HTTP_200_OK)


class LeaveRoomView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        cleanup_inactive_rooms()
        serializer = RoomCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data["code"].strip().upper()

        room = Room.objects.filter(code=code, is_active=True).first()
        if not room:
            return Response({"detail": "Room not found."}, status=status.HTTP_404_NOT_FOUND)

        RoomMember.objects.filter(room=room, user=request.user).update(is_active=False)
        sync_room_empty_state(room.id)
        cleanup_inactive_rooms()
        broadcast_rooms_snapshot()
        return Response({"detail": "Left room."}, status=status.HTTP_200_OK)


class ListRoomsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cleanup_inactive_rooms()
        return Response({"rooms": rooms_snapshot()}, status=status.HTTP_200_OK)


def _serialize_member(user):
    profile, _ = PlayerProfile.objects.get_or_create(user=user)
    name = (profile.display_name or "").strip()
    if not name:
        name = user.first_name or user.email.split("@")[0]
    return {
        "id": user.id,
        "name": name,
        "avatar": {
            "color": profile.avatar_color,
            "eyes": profile.avatar_eyes,
            "mouth": profile.avatar_mouth,
            "accessory": profile.avatar_accessory,
        },
    }


class SendRoomInviteView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "room_invite"

    def post(self, request, code: str):
        serializer = SendInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_user_id = serializer.validated_data["user_id"]

        room = Room.objects.filter(code=code.strip().upper(), is_active=True).first()
        if not room:
            return Response({"detail": "Room not found."}, status=status.HTTP_404_NOT_FOUND)

        if not RoomMember.objects.filter(room=room, user=request.user, is_active=True).exists():
            return Response(
                {"detail": "You must be an active member of this room to invite friends."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if target_user_id == request.user.id:
            return Response(
                {"detail": "You cannot invite yourself."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target = User.objects.filter(id=target_user_id).first()
        if not target:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        target_status, _ = UserStatus.objects.get_or_create(user=target)
        if not target.is_active or target_status.is_deleted or target_status.is_banned:
            return Response(
                {"detail": "User is not available for invites."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not Friendship.objects.filter(user=request.user, friend=target).exists():
            return Response(
                {"detail": "You can invite only friends."},
                status=status.HTTP_403_FORBIDDEN,
            )

        target_profile, _ = PlayerProfile.objects.get_or_create(user=target)
        if not (target_profile.display_name or "").strip():
            return Response(
                {"detail": "Friend must complete profile before joining rooms."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if RoomMember.objects.filter(room=room, user=target, is_active=True).exists():
            return Response(
                {"detail": "Friend is already in this room."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = RoomInvite.objects.filter(
            room=room,
            from_user=request.user,
            to_user=target,
            status=RoomInvite.STATUS_PENDING,
        ).first()
        if existing:
            return Response({"detail": "Invite already sent."}, status=status.HTTP_200_OK)

        RoomInvite.objects.create(
            room=room,
            from_user=request.user,
            to_user=target,
            status=RoomInvite.STATUS_PENDING,
        )
        return Response({"detail": "Invite sent."}, status=status.HTTP_201_CREATED)


class ListRoomInvitesView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "room_invite"

    def get(self, request):
        received = (
            RoomInvite.objects.filter(to_user=request.user, status=RoomInvite.STATUS_PENDING)
            .select_related("room", "from_user", "from_user__player_profile")
            .order_by("-created_at")[:30]
        )
        sent = (
            RoomInvite.objects.filter(from_user=request.user, status=RoomInvite.STATUS_PENDING)
            .select_related("room", "to_user", "to_user__player_profile")
            .order_by("-created_at")[:30]
        )
        return Response(
            {
                "received": [
                    {
                        "id": invite.id,
                        "room_code": invite.room.code,
                        "created_at": invite.created_at,
                        "from_user": _serialize_member(invite.from_user),
                    }
                    for invite in received
                ],
                "sent": [
                    {
                        "id": invite.id,
                        "room_code": invite.room.code,
                        "created_at": invite.created_at,
                        "to_user": _serialize_member(invite.to_user),
                    }
                    for invite in sent
                ],
            }
        )


class RespondRoomInviteView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "room_invite"

    def post(self, request, invite_id: int):
        serializer = RespondInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]

        invite = (
            RoomInvite.objects.filter(id=invite_id, to_user=request.user)
            .select_related("room", "from_user", "to_user")
            .first()
        )
        if not invite:
            return Response({"detail": "Invite not found."}, status=status.HTTP_404_NOT_FOUND)
        if invite.status != RoomInvite.STATUS_PENDING:
            return Response(
                {"detail": "Invite already handled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if action == "reject":
            invite.status = RoomInvite.STATUS_REJECTED
            invite.responded_at = timezone.now()
            invite.save(update_fields=["status", "responded_at"])
            return Response({"detail": "Invite rejected."})

        old_room_codes: list[str] = []
        with transaction.atomic():
            invite = (
                RoomInvite.objects.select_for_update()
                .select_related("room", "from_user", "to_user")
                .filter(id=invite.id, to_user=request.user)
                .first()
            )
            if not invite:
                return Response({"detail": "Invite not found."}, status=status.HTTP_404_NOT_FOUND)
            if invite.status != RoomInvite.STATUS_PENDING:
                return Response(
                    {"detail": "Invite already handled."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            room = invite.room
            if not room.is_active:
                invite.status = RoomInvite.STATUS_CANCELLED
                invite.responded_at = timezone.now()
                invite.save(update_fields=["status", "responded_at"])
                return Response(
                    {"detail": "Room is no longer active."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not Friendship.objects.filter(user=invite.from_user, friend=request.user).exists():
                invite.status = RoomInvite.STATUS_CANCELLED
                invite.responded_at = timezone.now()
                invite.save(update_fields=["status", "responded_at"])
                return Response(
                    {"detail": "Invite expired because friendship changed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            profile, _ = PlayerProfile.objects.get_or_create(user=request.user)
            if not (profile.display_name or "").strip():
                return Response(
                    {"detail": "Complete profile before joining room."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            active_elsewhere = RoomMember.objects.filter(
                user=request.user, is_active=True
            ).exclude(room=room)
            old_room_ids = list(active_elsewhere.values_list("room_id", flat=True).distinct())
            old_room_codes = list(
                Room.objects.filter(id__in=old_room_ids).values_list("code", flat=True)
            )

            target_member = RoomMember.objects.filter(room=room, user=request.user).first()
            is_already_active_in_room = bool(target_member and target_member.is_active)
            if not is_already_active_in_room:
                active_count = RoomMember.objects.filter(room=room, is_active=True).count()
                if active_count >= MAX_PLAYERS:
                    return Response(
                        {"detail": "Room is full."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            active_elsewhere.update(is_active=False)
            if target_member:
                if not target_member.is_active:
                    target_member.is_active = True
                    target_member.save(update_fields=["is_active"])
            else:
                RoomMember.objects.create(room=room, user=request.user, is_active=True)

            invite.status = RoomInvite.STATUS_ACCEPTED
            invite.responded_at = timezone.now()
            invite.save(update_fields=["status", "responded_at"])

            RoomInvite.objects.filter(
                to_user=request.user,
                status=RoomInvite.STATUS_PENDING,
            ).exclude(id=invite.id).update(
                status=RoomInvite.STATUS_CANCELLED,
                responded_at=timezone.now(),
            )

        for room_id in old_room_ids:
            sync_room_empty_state(room_id)
        sync_room_empty_state(invite.room.id)
        cleanup_inactive_rooms()
        broadcast_rooms_snapshot()

        channel_layer = get_channel_layer()
        if channel_layer:
            for old_code in old_room_codes:
                async_to_sync(channel_layer.group_send)(
                    f"room_{old_code}",
                    {
                        "type": "direct_disconnect_user",
                        "target_id": request.user.id,
                        "close_code": 4003,
                    },
                )

        return Response(
            {
                "detail": "Invite accepted. Joined room.",
                "code": invite.room.code,
            }
        )
