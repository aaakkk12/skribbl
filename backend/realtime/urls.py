from django.urls import path

from .views import (
    CreateRoomView,
    JoinRoomView,
    LeaveRoomView,
    ListRoomInvitesView,
    ListRoomsView,
    RespondRoomInviteView,
    SendRoomInviteView,
)

urlpatterns = [
    path("create/", CreateRoomView.as_view(), name="room_create"),
    path("join/", JoinRoomView.as_view(), name="room_join"),
    path("leave/", LeaveRoomView.as_view(), name="room_leave"),
    path("list/", ListRoomsView.as_view(), name="room_list"),
    path("<str:code>/invite/", SendRoomInviteView.as_view(), name="room_invite_send"),
    path("invites/", ListRoomInvitesView.as_view(), name="room_invites"),
    path("invites/<int:invite_id>/respond/", RespondRoomInviteView.as_view(), name="room_invite_respond"),
]
