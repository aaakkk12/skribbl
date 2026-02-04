from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db.models import Count, Q
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from realtime.lobby import broadcast_rooms_snapshot
from realtime.models import Room, RoomMember
from .models import ActiveSession, UserStatus

User = get_user_model()


def _admin_signer():
    return TimestampSigner(salt="admin-panel")


def _set_admin_cookie(response, token: str):
    response.set_cookie(
        settings.ADMIN_COOKIE_NAME,
        token,
        max_age=settings.ADMIN_TOKEN_MAX_AGE,
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite=settings.JWT_COOKIE_SAMESITE,
        path="/",
    )


def _clear_admin_cookie(response):
    response.delete_cookie(settings.ADMIN_COOKIE_NAME, path="/")


class AdminCookiePermission(BasePermission):
    def has_permission(self, request, view):
        token = request.COOKIES.get(settings.ADMIN_COOKIE_NAME)
        if not token:
            return False
        try:
            value = _admin_signer().unsign(
                token, max_age=settings.ADMIN_TOKEN_MAX_AGE
            )
        except (BadSignature, SignatureExpired):
            return False
        return value == settings.ADMIN_USERNAME


class AdminLoginView(APIView):
    permission_classes = []

    def post(self, request):
        username = (request.data.get("username") or "").strip()
        password = (request.data.get("password") or "").strip()
        if username != settings.ADMIN_USERNAME or password != settings.ADMIN_PASSWORD:
            return Response(
                {"detail": "Invalid admin credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        token = _admin_signer().sign(settings.ADMIN_USERNAME)
        response = Response({"detail": "Admin logged in."})
        _set_admin_cookie(response, token)
        return response


class AdminLogoutView(APIView):
    permission_classes = [AdminCookiePermission]

    def post(self, request):
        response = Response({"detail": "Admin logged out."})
        _clear_admin_cookie(response)
        return response


class AdminMeView(APIView):
    permission_classes = [AdminCookiePermission]

    def get(self, request):
        return Response({"username": settings.ADMIN_USERNAME})


class AdminRoomsView(APIView):
    permission_classes = [AdminCookiePermission]

    def get(self, request):
        rooms = (
            Room.objects.filter(is_active=True)
            .annotate(active_count=Count("members", filter=Q(members__is_active=True)))
            .order_by("-created_at")
        )
        data = [
            {
                "code": room.code,
                "is_private": room.is_private,
                "active_count": room.active_count,
                "max_players": 8,
            }
            for room in rooms
        ]
        return Response({"rooms": data})


class AdminRoomDetailView(APIView):
    permission_classes = [AdminCookiePermission]

    def patch(self, request, code: str):
        room = Room.objects.filter(code=code.upper(), is_active=True).first()
        if not room:
            return Response({"detail": "Room not found."}, status=status.HTTP_404_NOT_FOUND)

        is_private = request.data.get("is_private")
        password = (request.data.get("password") or "").strip()
        if is_private is not None:
            room.is_private = bool(is_private)
            if room.is_private:
                if password:
                    room.set_password(password)
                elif not room.password_hash:
                    return Response(
                        {"detail": "Password required for private room."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                room.password_hash = ""

        room.save(update_fields=["is_private", "password_hash"])
        broadcast_rooms_snapshot()
        return Response({"detail": "Room updated."})

    def delete(self, request, code: str):
        room = Room.objects.filter(code=code.upper(), is_active=True).first()
        if not room:
            return Response({"detail": "Room not found."}, status=status.HTTP_404_NOT_FOUND)

        RoomMember.objects.filter(room=room).update(is_active=False)
        room.is_active = False
        room.save(update_fields=["is_active"])
        broadcast_rooms_snapshot()
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"room_{room.code}",
                {
                    "type": "admin_close",
                    "message": "Room closed by admin.",
                },
            )
        return Response({"detail": "Room deleted."})


class AdminPasswordResetView(APIView):
    permission_classes = [AdminCookiePermission]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            return Response(
                {"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND
            )

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        reset_link = f"{settings.FRONTEND_URL}/reset-password/confirm?uid={uid}&token={token}"

        subject = "Admin sent you a password reset link"
        message = (
            "An admin generated a password reset link for your account.\n\n"
            f"Reset link: {reset_link}\n\n"
            "If you did not request this, please ignore this email."
        )
        try:
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])
        except Exception:
            pass

        return Response({"detail": "Reset link sent."})


class AdminUsersView(APIView):
    permission_classes = [AdminCookiePermission]

    def get(self, request):
        users = User.objects.order_by("-date_joined")
        data = [
            {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "last_login": user.last_login,
                "is_active": user.is_active,
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
                "is_banned": getattr(getattr(user, "status", None), "is_banned", False),
                "is_deleted": getattr(getattr(user, "status", None), "is_deleted", False),
            }
            for user in users
        ]
        return Response({"users": data})


class AdminUserActionView(APIView):
    permission_classes = [AdminCookiePermission]

    def post(self, request, user_id: int):
        action = (request.data.get("action") or "").strip().lower()
        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        status_row, _ = UserStatus.objects.get_or_create(user=user)

        if action == "ban":
            status_row.is_banned = True
        elif action == "unban":
            status_row.is_banned = False
        elif action == "delete":
            status_row.is_deleted = True
            status_row.is_banned = False
            user.is_active = False
            user.save(update_fields=["is_active"])
            ActiveSession.objects.filter(user=user).delete()
        elif action == "restore":
            status_row.is_deleted = False
            user.is_active = True
            user.save(update_fields=["is_active"])
        else:
            return Response(
                {"detail": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST
            )

        status_row.save(update_fields=["is_banned", "is_deleted"])
        return Response({"detail": "User updated."})
