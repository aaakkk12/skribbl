from django.urls import path

from .views import (
    GuestSessionView,
    CookieTokenRefreshView,
    LogoutView,
    MeView,
)

urlpatterns = [
    path("guest-session/", GuestSessionView.as_view(), name="guest_session"),
    path("token/refresh/", CookieTokenRefreshView.as_view(), name="token_refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
]



