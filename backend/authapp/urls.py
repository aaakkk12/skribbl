from django.urls import path

from .views import (
    FriendDetailView,
    FriendsView,
    RegisterView,
    LoginView,
    LogoutView,
    CookieTokenRefreshView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    MeView,
    ProfileView,
    UserSearchView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("token/refresh/", CookieTokenRefreshView.as_view(), name="token_refresh"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="password_reset"),
    path(
        "password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path("me/", MeView.as_view(), name="me"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("users/search/", UserSearchView.as_view(), name="users_search"),
    path("friends/", FriendsView.as_view(), name="friends"),
    path("friends/<int:user_id>/", FriendDetailView.as_view(), name="friend_detail"),
]



