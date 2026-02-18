from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import ActiveSession, UserStatus


class CookieJWTAuthentication(JWTAuthentication):
    """Authenticate using the access token stored in an HttpOnly cookie."""

    def authenticate(self, request):
        raw_token = request.COOKIES.get(settings.JWT_ACCESS_COOKIE)
        if not raw_token:
            return None
        validated_token = self.get_validated_token(raw_token)
        user = self.get_user(validated_token)
        session_id = validated_token.get("sid")
        if not session_id:
            return None
        active = ActiveSession.objects.filter(user=user).first()
        if not active or str(active.session_id) != str(session_id):
            return None
        status_row, _ = UserStatus.objects.get_or_create(user=user)
        if status_row.is_banned or status_row.is_deleted or not user.is_active:
            return None
        return user, validated_token



