import random
import string

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from authapp.models import PlayerProfile, UserStatus
from .lifecycle import cleanup_inactive_rooms, sync_room_empty_state
from .lobby import broadcast_rooms_snapshot, rooms_snapshot
from .models import Room, RoomMember
from .serializers import CreateRoomSerializer, JoinRoomSerializer, RoomCodeSerializer

CODE_LENGTH = 6
MAX_PLAYERS = 8


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
            return Response({"detail": "Room not found."}, status=status.HTTP_404_NOT_FOUND)

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
                {"detail": "Complete your guest profile first."},
                status=status.HTTP_403_FORBIDDEN,
            )

        member = RoomMember.objects.filter(room=room, user=request.user).first()
        if member and member.is_active:
            sync_room_empty_state(room.id)
            broadcast_rooms_snapshot()
            return Response({"code": room.code}, status=status.HTTP_200_OK)

        if room.is_private and (not password or not room.check_password(password)):
            return Response(
                {"detail": "Room password is incorrect."},
                status=status.HTTP_403_FORBIDDEN,
            )

        active_count = RoomMember.objects.filter(room=room, is_active=True).count()
        if active_count >= MAX_PLAYERS:
            return Response({"detail": "Room is full."}, status=status.HTTP_400_BAD_REQUEST)

        if member:
            member.is_active = True
            member.save(update_fields=["is_active"])
        else:
            RoomMember.objects.create(room=room, user=request.user, is_active=True)

        sync_room_empty_state(room.id)
        broadcast_rooms_snapshot()
        return Response({"code": room.code}, status=status.HTTP_200_OK)


class JoinRandomRoomView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "room_join"

    def post(self, request):
        cleanup_inactive_rooms()

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
                {"detail": "Complete your guest profile first."},
                status=status.HTTP_403_FORBIDDEN,
            )

        selected_room = None
        with transaction.atomic():
            room_ids = list(
                Room.objects.filter(is_active=True, is_private=False).values_list("id", flat=True)
            )
            random.shuffle(room_ids)

            for room_id in room_ids:
                room = Room.objects.select_for_update().filter(id=room_id, is_active=True).first()
                if not room or room.is_private:
                    continue

                member = RoomMember.objects.filter(room=room, user=request.user).first()
                if member and member.is_active:
                    selected_room = room
                    break

                active_count = RoomMember.objects.filter(room=room, is_active=True).count()
                if active_count >= MAX_PLAYERS:
                    continue

                if member:
                    member.is_active = True
                    member.save(update_fields=["is_active"])
                else:
                    RoomMember.objects.create(room=room, user=request.user, is_active=True)
                selected_room = room
                break

        if not selected_room:
            return Response(
                {"detail": "No joinable public room is live right now."},
                status=status.HTTP_404_NOT_FOUND,
            )

        sync_room_empty_state(selected_room.id)
        broadcast_rooms_snapshot()
        return Response({"code": selected_room.code}, status=status.HTTP_200_OK)


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
        cleanup_inactive_rooms(empty_minutes=0)
        broadcast_rooms_snapshot()
        return Response({"detail": "Left room."}, status=status.HTTP_200_OK)


class ListRoomsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cleanup_inactive_rooms()
        return Response({"rooms": rooms_snapshot()}, status=status.HTTP_200_OK)
