from django.urls import path

from .views import (
    CreateRoomView,
    JoinRoomView,
    JoinRandomRoomView,
    LeaveRoomView,
    ListRoomsView,
)

urlpatterns = [
    path("create/", CreateRoomView.as_view(), name="room_create"),
    path("join/", JoinRoomView.as_view(), name="room_join"),
    path("join-random/", JoinRandomRoomView.as_view(), name="room_join_random"),
    path("leave/", LeaveRoomView.as_view(), name="room_leave"),
    path("list/", ListRoomsView.as_view(), name="room_list"),
]
