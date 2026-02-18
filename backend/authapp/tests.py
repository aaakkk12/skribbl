from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from authapp.models import ActiveSession, Friendship, PlayerProfile, UserStatus

User = get_user_model()


@override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class AuthFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_login_logout_flow(self):
        payload = {
            "email": "auth-flow@example.com",
            "password": "StrongPass123!",
            "first_name": "Auth",
        }
        response = self.client.post("/api/auth/register/", payload, format="json")
        self.assertEqual(response.status_code, 201)

        response = self.client.post(
            "/api/auth/login/",
            {"email": payload["email"], "password": payload["password"]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)

        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)

        response = self.client.post("/api/auth/logout/", {}, format="json")
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 401)

    def test_banned_user_cannot_login(self):
        user = User.objects.create_user(
            username="banned@example.com",
            email="banned@example.com",
            password="StrongPass123!",
        )
        status_row, _ = UserStatus.objects.get_or_create(user=user)
        status_row.is_banned = True
        status_row.save(update_fields=["is_banned"])

        response = self.client.post(
            "/api/auth/login/",
            {"email": user.email, "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get("detail"), "Your account is banned.")

    def test_archived_user_cannot_register_again(self):
        user = User.objects.create_user(
            username="archived@example.com",
            email="archived@example.com",
            password="StrongPass123!",
        )
        status_row, _ = UserStatus.objects.get_or_create(user=user)
        status_row.is_deleted = True
        status_row.save(update_fields=["is_deleted"])

        response = self.client.post(
            "/api/auth/register/",
            {"email": user.email, "password": "AnotherPass123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        message = str(response.json())
        self.assertIn("archived", message.lower())

    def test_admin_api_disabled_by_default(self):
        response = self.client.post(
            "/api/admin/login/",
            {"username": "admin", "password": "123"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def tearDown(self):
        ActiveSession.objects.all().delete()
        PlayerProfile.objects.all().delete()


class MaintenanceCommandTests(TestCase):
    def test_inactive_account_deleted_after_7_days(self):
        inactive_user = User.objects.create_user(
            username="inactive@example.com",
            email="inactive@example.com",
            password="StrongPass123!",
        )
        inactive_user.last_login = timezone.now() - timedelta(days=8)
        inactive_user.save(update_fields=["last_login"])

        active_user = User.objects.create_user(
            username="active@example.com",
            email="active@example.com",
            password="StrongPass123!",
        )
        active_user.last_login = timezone.now() - timedelta(days=1)
        active_user.save(update_fields=["last_login"])

        staff_user = User.objects.create_user(
            username="staff@example.com",
            email="staff@example.com",
            password="StrongPass123!",
            is_staff=True,
        )
        staff_user.last_login = timezone.now() - timedelta(days=20)
        staff_user.save(update_fields=["last_login"])

        call_command(
            "run_maintenance",
            inactive_days=7,
            room_retention_days=365,
            max_storage_gb=20,
            target_storage_gb=15,
            log_retention_days=30,
        )

        self.assertFalse(User.objects.filter(id=inactive_user.id).exists())
        self.assertTrue(User.objects.filter(id=active_user.id).exists())
        self.assertTrue(User.objects.filter(id=staff_user.id).exists())

    def test_inactive_account_not_deleted_in_dry_run(self):
        inactive_user = User.objects.create_user(
            username="inactive-dry@example.com",
            email="inactive-dry@example.com",
            password="StrongPass123!",
        )
        inactive_user.last_login = timezone.now() - timedelta(days=8)
        inactive_user.save(update_fields=["last_login"])

        output = StringIO()
        call_command(
            "run_maintenance",
            inactive_days=7,
            room_retention_days=365,
            max_storage_gb=20,
            target_storage_gb=15,
            log_retention_days=30,
            dry_run=True,
            stdout=output,
        )

        self.assertTrue(User.objects.filter(id=inactive_user.id).exists())


@override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class FriendApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.me = self._create_user("me@example.com", "MePlayer")
        self.friend = self._create_user("buddy@example.com", "Buddy")
        self.client.force_authenticate(user=self.me)

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

    def test_search_add_and_unfriend(self):
        search_response = self.client.get("/api/auth/users/search/?q=buddy")
        self.assertEqual(search_response.status_code, 200)
        self.assertEqual(len(search_response.json().get("results", [])), 1)

        add_response = self.client.post(
            "/api/auth/friends/",
            {"user_id": self.friend.id},
            format="json",
        )
        self.assertEqual(add_response.status_code, 200)
        self.assertTrue(
            Friendship.objects.filter(user=self.me, friend=self.friend).exists()
        )
        self.assertTrue(
            Friendship.objects.filter(user=self.friend, friend=self.me).exists()
        )

        list_response = self.client.get("/api/auth/friends/")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json().get("friends", [])), 1)

        remove_response = self.client.delete(f"/api/auth/friends/{self.friend.id}/")
        self.assertEqual(remove_response.status_code, 200)
        self.assertFalse(
            Friendship.objects.filter(user=self.me, friend=self.friend).exists()
        )
