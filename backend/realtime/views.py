import random
import string

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from authapp.models import UserStatus
from .models import Room, RoomMember
from .serializers import RoomCodeSerializer, CreateRoomSerializer, JoinRoomSerializer
from .lobby import broadcast_rooms_snapshot, rooms_snapshot

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

    def post(self, request):
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
        broadcast_rooms_snapshot()
        return Response({"code": room.code}, status=status.HTTP_201_CREATED)


class JoinRoomView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
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

        member = RoomMember.objects.filter(room=room, user=request.user).first()
        if member and member.is_active:
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

        broadcast_rooms_snapshot()
        return Response({"code": room.code}, status=status.HTTP_200_OK)


class LeaveRoomView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RoomCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data["code"].strip().upper()

        room = Room.objects.filter(code=code, is_active=True).first()
        if not room:
            return Response({"detail": "Room not found."}, status=status.HTTP_404_NOT_FOUND)

        RoomMember.objects.filter(room=room, user=request.user).update(is_active=False)
        broadcast_rooms_snapshot()
        return Response({"detail": "Left room."}, status=status.HTTP_200_OK)


class ListRoomsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"rooms": rooms_snapshot()}, status=status.HTTP_200_OK)
