import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from .models import ActiveSession, PlayerProfile, UserStatus
from .serializers import GuestSessionSerializer, UserSerializer

User = get_user_model()

CHARACTER_PRESETS = {
    "sprinter": {
        "color": "#5eead4",
        "eyes": "dot",
        "mouth": "smile",
        "accessory": "none",
    },
    "captain": {
        "color": "#1d4ed8",
        "eyes": "happy",
        "mouth": "smile",
        "accessory": "cap",
    },
    "vision": {
        "color": "#8b5cf6",
        "eyes": "happy",
        "mouth": "open",
        "accessory": "glasses",
    },
    "joker": {
        "color": "#f97316",
        "eyes": "happy",
        "mouth": "open",
        "accessory": "none",
    },
    "royal": {
        "color": "#f59e0b",
        "eyes": "dot",
        "mouth": "smile",
        "accessory": "crown",
    },
    "ninja": {
        "color": "#334155",
        "eyes": "sleepy",
        "mouth": "flat",
        "accessory": "none",
    },
}


def _cookie_settings():
    return {
        "httponly": True,
        "secure": settings.JWT_COOKIE_SECURE,
        "samesite": settings.JWT_COOKIE_SAMESITE,
        "path": "/",
    }


def _set_access_cookie(response, access_token):
    access_max_age = int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())
    response.set_cookie(
        settings.JWT_ACCESS_COOKIE,
        access_token,
        max_age=access_max_age,
        **_cookie_settings(),
    )


def _set_refresh_cookie(response, refresh_token):
    refresh_max_age = int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE,
        refresh_token,
        max_age=refresh_max_age,
        **_cookie_settings(),
    )


def _normalize_device_id(raw_value):
    raw = (raw_value or "").strip().lower()
    if not raw:
        return None
    try:
        return str(uuid.UUID(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def _resolve_device_id(request, explicit_device_id):
    resolved = _normalize_device_id(explicit_device_id)
    if resolved:
        return resolved
    cookie_value = request.COOKIES.get(settings.GUEST_DEVICE_COOKIE)
    resolved = _normalize_device_id(cookie_value)
    if resolved:
        return resolved
    return str(uuid.uuid4())


def _set_guest_device_cookie(response, device_id):
    response.set_cookie(
        settings.GUEST_DEVICE_COOKIE,
        device_id,
        max_age=settings.GUEST_DEVICE_COOKIE_MAX_AGE,
        **_cookie_settings(),
    )


class GuestSessionView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "guest_session"

    def post(self, request):
        serializer = GuestSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data["username"]
        character = serializer.validated_data["character"]
        device_id = _resolve_device_id(request, serializer.validated_data.get("device_id"))

        guest_key = device_id.replace("-", "")
        guest_username = f"guest_{guest_key}"
        guest_email = f"{guest_username}@guest.local"
        avatar = CHARACTER_PRESETS[character]

        with transaction.atomic():
            user = User.objects.filter(username=guest_username).first()
            if not user:
                user = User(
                    username=guest_username,
                    email=guest_email,
                    first_name=username,
                    last_name="",
                    is_active=True,
                )
                user.set_unusable_password()
                user.save()
            else:
                changed_fields: list[str] = []
                if user.email != guest_email:
                    user.email = guest_email
                    changed_fields.append("email")
                if user.first_name != username:
                    user.first_name = username
                    changed_fields.append("first_name")
                if not user.is_active:
                    user.is_active = True
                    changed_fields.append("is_active")
                if changed_fields:
                    user.save(update_fields=changed_fields)

            status_row, _ = UserStatus.objects.get_or_create(user=user)
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

            profile, _ = PlayerProfile.objects.get_or_create(user=user)
            profile.display_name = username
            profile.avatar_color = avatar["color"]
            profile.avatar_eyes = avatar["eyes"]
            profile.avatar_mouth = avatar["mouth"]
            profile.avatar_accessory = avatar["accessory"]
            profile.save(
                update_fields=[
                    "display_name",
                    "avatar_color",
                    "avatar_eyes",
                    "avatar_mouth",
                    "avatar_accessory",
                    "updated_at",
                ]
            )

            session, _ = ActiveSession.objects.update_or_create(
                user=user, defaults={"session_id": uuid.uuid4()}
            )
            user.last_login = timezone.now()
            user.save(update_fields=["last_login"])

        refresh = RefreshToken.for_user(user)
        refresh["sid"] = str(session.session_id)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        response = Response(
            {
                "device_id": device_id,
                "character": character,
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )
        _set_access_cookie(response, access_token)
        _set_refresh_cookie(response, refresh_token)
        _set_guest_device_cookie(response, device_id)
        return response


class CookieTokenRefreshView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth_login"

    def post(self, request):
        refresh_token = request.COOKIES.get(settings.JWT_REFRESH_COOKIE) or request.data.get(
            "refresh"
        )
        if not refresh_token:
            return Response(
                {"detail": "Refresh token missing."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            refresh = RefreshToken(refresh_token)
        except TokenError:
            return Response(
                {"detail": "Invalid refresh token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        session_id = refresh.get("sid")
        if not session_id:
            return Response(
                {"detail": "Invalid refresh token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user_id = refresh.get(api_settings.USER_ID_CLAIM)
        active = ActiveSession.objects.filter(user_id=user_id).first()
        if not active or str(active.session_id) != str(session_id):
            return Response(
                {"detail": "Session expired."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        access_token = str(refresh.access_token)
        response = Response({"detail": "Token refreshed."})
        _set_access_cookie(response, access_token)
        return response


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if request.user.is_authenticated:
            ActiveSession.objects.filter(user=request.user).delete()
        response = Response({"detail": "Logged out."})
        response.delete_cookie(settings.JWT_ACCESS_COOKIE, path="/")
        response.delete_cookie(settings.JWT_REFRESH_COOKIE, path="/")
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        PlayerProfile.objects.get_or_create(user=request.user)
        return Response(UserSerializer(request.user).data)
