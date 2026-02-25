from django.urls import path

from .admin_views import (
    AdminLoginView,
    AdminLogoutView,
    AdminMeView,
    AdminRoomsView,
    AdminRoomDetailView,
    AdminUsersView,
    AdminUserActionView,
)

urlpatterns = [
    path("login/", AdminLoginView.as_view(), name="admin_login"),
    path("logout/", AdminLogoutView.as_view(), name="admin_logout"),
    path("me/", AdminMeView.as_view(), name="admin_me"),
    path("rooms/", AdminRoomsView.as_view(), name="admin_rooms"),
    path("rooms/<str:code>/", AdminRoomDetailView.as_view(), name="admin_room_detail"),
    path("users/", AdminUsersView.as_view(), name="admin_users"),
    path("users/<int:user_id>/action/", AdminUserActionView.as_view(), name="admin_user_action"),
]
