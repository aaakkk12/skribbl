from http.cookies import SimpleCookie

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.backends import TokenBackend
from rest_framework_simplejwt.settings import api_settings

from authapp.models import ActiveSession, UserStatus

token_backend = TokenBackend(
    algorithm=api_settings.ALGORITHM,
    signing_key=api_settings.SIGNING_KEY,
)


def get_cookie(scope, name: str):
    headers = dict(scope.get("headers", []))
    raw = headers.get(b"cookie")
    if not raw:
        return None
    cookie = SimpleCookie()
    cookie.load(raw.decode())
    morsel = cookie.get(name)
    return morsel.value if morsel else None


@database_sync_to_async
def get_user(user_id):
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
        status_row, _ = UserStatus.objects.get_or_create(user=user)
        if status_row.is_banned or status_row.is_deleted or not user.is_active:
            return AnonymousUser()
        return user
    except User.DoesNotExist:
        return AnonymousUser()

@database_sync_to_async
def get_active_session_id(user_id):
    session = ActiveSession.objects.filter(user_id=user_id).first()
    return str(session.session_id) if session else None


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        scope["user"] = AnonymousUser()
        token = get_cookie(scope, settings.JWT_ACCESS_COOKIE)
        if token:
            try:
                payload = token_backend.decode(token, verify=True)
                user_id = payload.get(api_settings.USER_ID_CLAIM)
                session_id = payload.get("sid")
                if user_id is not None and session_id:
                    active_session = await get_active_session_id(user_id)
                    if active_session and str(active_session) == str(session_id):
                        scope["user"] = await get_user(user_id)
            except Exception:
                scope["user"] = AnonymousUser()
        return await super().__call__(scope, receive, send)
