from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from authapp.models import ActiveSession, Friendship, PlayerProfile, UserStatus
from realtime.lifecycle import cleanup_inactive_rooms
from realtime.models import Room, RoomInvite, RoomMember

User = get_user_model()


@override_settings(
    ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class RoomSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = self._create_user("owner@example.com", "Owner")
        self.guest = self._create_user("guest@example.com", "Guest")

    def _create_user(self, email: str, name: str):
        user = User.objects.create_user(username=email, email=email, password="StrongPass123!")
        UserStatus.objects.get_or_create(user=user)
        profile, _ = PlayerProfile.objects.get_or_create(user=user)
        profile.display_name = name
        profile.save(update_fields=["display_name"])
        return user

    def _auth_cookie(self, user):
        session, _ = ActiveSession.objects.update_or_create(user=user)
        refresh = RefreshToken.for_user(user)
        refresh["sid"] = str(session.session_id)
        access_token = str(refresh.access_token)
        return f"{settings.JWT_ACCESS_COOKIE}={access_token}"

    async def _connect(self, code: str, cookie_header: str):
        from backend.asgi import application

        communicator = WebsocketCommunicator(
            application,
            f"/ws/rooms/{code}/",
            headers=[(b"cookie", cookie_header.encode("utf-8"))],
        )
        connected, detail = await communicator.connect()
        if connected:
            await communicator.disconnect()
            return connected, 1000
        return connected, detail

    def test_private_room_requires_password(self):
        room = Room.objects.create(code="PRIV01", owner=self.owner, is_private=True)
        room.set_password("room-pass-123")
        room.save(update_fields=["password_hash"])
        RoomMember.objects.create(room=room, user=self.owner, is_active=True)

        self.client.force_authenticate(user=self.guest)
        response = self.client.post(
            "/api/rooms/join/",
            {"code": room.code, "password": ""},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_websocket_rejects_user_without_active_membership(self):
        room = Room.objects.create(code="OPEN01", owner=self.owner, is_private=False)
        RoomMember.objects.create(room=room, user=self.owner, is_active=True)
        cookie = self._auth_cookie(self.guest)

        connected, close_code = async_to_sync(self._connect)(room.code, cookie)
        self.assertFalse(connected)
        self.assertIsNotNone(close_code)


class RoomLifecycleTests(TestCase):
    def setUp(self):
        email = "room-owner@example.com"
        self.owner = User.objects.create_user(
            username=email,
            email=email,
            password="StrongPass123!",
        )

    def test_delete_empty_room_after_10_minutes(self):
        room = Room.objects.create(
            code="EMPTY1",
            owner=self.owner,
            is_active=True,
            empty_since=timezone.now() - timedelta(minutes=11),
        )
        RoomMember.objects.create(room=room, user=self.owner, is_active=False)

        deleted_count = cleanup_inactive_rooms(empty_minutes=10)

        self.assertEqual(deleted_count, 1)
        self.assertFalse(Room.objects.filter(id=room.id).exists())

    def test_keep_room_if_empty_for_less_than_10_minutes(self):
        room = Room.objects.create(
            code="EMPTY2",
            owner=self.owner,
            is_active=True,
            empty_since=timezone.now() - timedelta(minutes=5),
        )
        RoomMember.objects.create(room=room, user=self.owner, is_active=False)

        deleted_count = cleanup_inactive_rooms(empty_minutes=10)

        self.assertEqual(deleted_count, 0)
        self.assertTrue(Room.objects.filter(id=room.id).exists())


@override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class RoomInviteFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.sender = self._create_user("sender@example.com", "Sender")
        self.receiver = self._create_user("receiver@example.com", "Receiver")
        Friendship.objects.get_or_create(user=self.sender, friend=self.receiver)
        Friendship.objects.get_or_create(user=self.receiver, friend=self.sender)

    def _create_user(self, email: str, display_name: str):
        user = User.objects.create_user(
            username=email,
            email=email,
            password="StrongPass123!",
        )
        UserStatus.objects.get_or_create(user=user)
        profile, _ = PlayerProfile.objects.get_or_create(user=user)
        profile.display_name = display_name
        profile.save(update_fields=["display_name"])
        return user

    def test_accept_invite_switches_room(self):
        room_a = Room.objects.create(code="ROOMA1", owner=self.sender, is_active=True)
        room_b = Room.objects.create(code="ROOMB1", owner=self.receiver, is_active=True)
        RoomMember.objects.create(room=room_a, user=self.sender, is_active=True)
        RoomMember.objects.create(room=room_b, user=self.receiver, is_active=True)

        self.client.force_authenticate(user=self.sender)
        send_response = self.client.post(
            f"/api/rooms/{room_a.code}/invite/",
            {"user_id": self.receiver.id},
            format="json",
        )
        self.assertEqual(send_response.status_code, 201)

        self.client.force_authenticate(user=self.receiver)
        invites_response = self.client.get("/api/rooms/invites/")
        self.assertEqual(invites_response.status_code, 200)
        received = invites_response.json().get("received", [])
        self.assertEqual(len(received), 1)
        invite_id = received[0]["id"]

        accept_response = self.client.post(
            f"/api/rooms/invites/{invite_id}/respond/",
            {"action": "accept"},
            format="json",
        )
        self.assertEqual(accept_response.status_code, 200)
        self.assertEqual(accept_response.json().get("code"), room_a.code)

        self.assertTrue(
            RoomMember.objects.filter(room=room_a, user=self.receiver, is_active=True).exists()
        )
        self.assertFalse(
            RoomMember.objects.filter(room=room_b, user=self.receiver, is_active=True).exists()
        )
        self.assertTrue(
            RoomInvite.objects.filter(
                id=invite_id, status=RoomInvite.STATUS_ACCEPTED
            ).exists()
        )
