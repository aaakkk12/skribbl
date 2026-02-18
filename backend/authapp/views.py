import uuid
import logging

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings

from .models import ActiveSession, Friendship, PlayerProfile, UserStatus
from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    PlayerProfileSerializer,
    UserSerializer,
)

User = get_user_model()
logger = logging.getLogger(__name__)


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


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth_register"

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        PlayerProfile.objects.get_or_create(user=user)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth_login"

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()
        password = serializer.validated_data["password"]
        user = authenticate(request, username=email, password=password)
        if not user:
            return Response(
                {"detail": "Invalid email or password."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not user.is_active:
            return Response(
                {"detail": "Account is disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )

        status_row, _ = UserStatus.objects.get_or_create(user=user)
        if status_row.is_deleted:
            return Response(
                {"detail": "Account is archived. Contact admin to restore."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if status_row.is_banned:
            return Response(
                {"detail": "Your account is banned."},
                status=status.HTTP_403_FORBIDDEN,
            )
        PlayerProfile.objects.get_or_create(user=user)
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        session, _ = ActiveSession.objects.update_or_create(
            user=user, defaults={"session_id": uuid.uuid4()}
        )

        refresh = RefreshToken.for_user(user)
        refresh["sid"] = str(session.session_id)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        response = Response({"user": UserSerializer(user).data})
        _set_access_cookie(response, access_token)
        _set_refresh_cookie(response, refresh_token)
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


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = PlayerProfile.objects.get_or_create(user=request.user)
        return Response(PlayerProfileSerializer(profile).data)

    def put(self, request):
        profile, _ = PlayerProfile.objects.get_or_create(user=request.user)
        serializer = PlayerProfileSerializer(profile, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth_password_reset"

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()
        user = User.objects.filter(email__iexact=email).first()

        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_link = f"{settings.FRONTEND_URL}/reset-password/confirm?uid={uid}&token={token}"

            subject = "Reset your password"
            message = (
                "We received a request to reset your password.\n\n"
                f"Reset link: {reset_link}\n\n"
                "If you did not request this, you can ignore this email."
            )

            try:
                send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])
            except Exception as exc:
                logger.warning("Password reset email failed for user_id=%s: %s", user.id, exc)

        return Response(
            {"detail": "If an account exists, a reset link has been sent."}
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth_password_reset"

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uid = serializer.validated_data["uid"]
        token = serializer.validated_data["token"]
        new_password = serializer.validated_data["new_password"]

        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            return Response(
                {"detail": "Invalid reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not default_token_generator.check_token(user, token):
            return Response(
                {"detail": "Invalid or expired token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save()
        ActiveSession.objects.filter(user=user).delete()
        UserStatus.objects.get_or_create(user=user)

        return Response({"detail": "Password reset successful."})


def _serialize_public_user(user):
    profile, _ = PlayerProfile.objects.get_or_create(user=user)
    name = (profile.display_name or "").strip()
    if not name:
        name = user.first_name or user.email.split("@")[0]
    return {
        "id": user.id,
        "email": user.email,
        "name": name,
        "avatar": {
            "color": profile.avatar_color,
            "eyes": profile.avatar_eyes,
            "mouth": profile.avatar_mouth,
            "accessory": profile.avatar_accessory,
        },
    }


class UserSearchView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "user_search"

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        if not query:
            return Response({"results": []})

        users = (
            User.objects.filter(is_active=True)
            .exclude(id=request.user.id)
            .filter(Q(status__isnull=True) | Q(status__is_deleted=False))
            .filter(Q(status__isnull=True) | Q(status__is_banned=False))
            .filter(
                Q(email__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(player_profile__display_name__icontains=query)
            )
            .select_related("player_profile")
            .order_by("-last_login", "-date_joined")[:20]
        )

        friend_ids = set(
            Friendship.objects.filter(user=request.user, friend__in=users).values_list(
                "friend_id", flat=True
            )
        )
        results = []
        for user in users:
            payload = _serialize_public_user(user)
            payload["is_friend"] = user.id in friend_ids
            results.append(payload)
        return Response({"results": results})


class FriendsView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "friend_action"

    def get(self, request):
        links = (
            Friendship.objects.filter(user=request.user)
            .select_related("friend", "friend__player_profile")
            .order_by("-created_at")
        )
        friends = []
        for link in links:
            friend_user = link.friend
            if not friend_user.is_active:
                continue
            status_row = getattr(friend_user, "status", None)
            if status_row and (status_row.is_banned or status_row.is_deleted):
                continue
            payload = _serialize_public_user(friend_user)
            payload["friend_since"] = link.created_at
            friends.append(payload)
        return Response({"friends": friends})

    def post(self, request):
        target_id = request.data.get("user_id")
        try:
            target_id = int(target_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "Valid user_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if target_id == request.user.id:
            return Response(
                {"detail": "You cannot add yourself as friend."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target = User.objects.filter(id=target_id).select_related("status").first()
        if not target:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if not target.is_active:
            return Response(
                {"detail": "User account is not active."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        status_row = getattr(target, "status", None)
        if status_row and (status_row.is_banned or status_row.is_deleted):
            return Response(
                {"detail": "User is not available."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            forward, _ = Friendship.objects.get_or_create(user=request.user, friend=target)
            Friendship.objects.get_or_create(user=target, friend=request.user)

        payload = _serialize_public_user(target)
        payload["friend_since"] = forward.created_at
        return Response({"detail": "Friend added.", "friend": payload})


class FriendDetailView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "friend_action"

    def delete(self, request, user_id: int):
        if user_id == request.user.id:
            return Response(
                {"detail": "You cannot unfriend yourself."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        deleted_count = 0
        with transaction.atomic():
            deleted_count += Friendship.objects.filter(
                user=request.user, friend_id=user_id
            ).delete()[0]
            deleted_count += Friendship.objects.filter(
                user_id=user_id, friend=request.user
            ).delete()[0]

        if deleted_count == 0:
            return Response({"detail": "Friend not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": "Unfriended successfully."})



