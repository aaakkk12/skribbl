from datetime import timedelta
from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from authapp.models import ActiveSession, PlayerProfile, UserStatus

User = get_user_model()


@override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class AuthFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_guest_session_bootstraps_profile_and_cookies(self):
        response = self.client.post(
            "/api/auth/guest-session/",
            {
                "username": "SketchMaster",
                "character": "royal",
                "device_id": "5f9c13d0-560a-4bc7-8f95-10c2f6d2a384",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)

        body = response.json()
        device_id = body.get("device_id")
        self.assertEqual(device_id, "5f9c13d0-560a-4bc7-8f95-10c2f6d2a384")

        guest_username = f"guest_{device_id.replace('-', '')}"
        user = User.objects.filter(username=guest_username).first()
        self.assertIsNotNone(user)

        profile = PlayerProfile.objects.filter(user=user).first()
        self.assertIsNotNone(profile)
        self.assertEqual(profile.display_name, "SketchMaster")
        self.assertEqual(profile.avatar_accessory, "crown")

        me_response = self.client.get("/api/auth/me/")
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json().get("display_name"), "SketchMaster")
        self.assertIn(settings.GUEST_DEVICE_COOKIE, response.cookies)

    def test_guest_session_reuses_cookie_device_id_when_not_provided(self):
        initial_device_id = "f1b26156-1111-4ca1-8db4-98b5ef52f82f"
        first = self.client.post(
            "/api/auth/guest-session/",
            {
                "username": "PlayerOne",
                "character": "sprinter",
                "device_id": initial_device_id,
            },
            format="json",
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json().get("device_id"), initial_device_id)

        second = self.client.post(
            "/api/auth/guest-session/",
            {
                "username": "PlayerOne",
                "character": "captain",
            },
            format="json",
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json().get("device_id"), initial_device_id)
        guest_username = f"guest_{initial_device_id.replace('-', '')}"
        self.assertEqual(User.objects.filter(username=guest_username).count(), 1)

    def test_guest_session_denies_banned_account(self):
        device_id = "8d6e6534-527a-4fac-9f68-22f6db59ab18"
        guest_username = f"guest_{device_id.replace('-', '')}"
        guest_email = f"{guest_username}@guest.local"

        user = User.objects.create_user(
            username=guest_username,
            email=guest_email,
            password="StrongPass123!",
            first_name="Blocked",
        )
        status_row, _ = UserStatus.objects.get_or_create(user=user)
        status_row.is_banned = True
        status_row.save(update_fields=["is_banned"])

        response = self.client.post(
            "/api/auth/guest-session/",
            {
                "username": "Blocked",
                "character": "sprinter",
                "device_id": device_id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get("detail"), "Your account is banned.")

    def test_refresh_and_logout_flow(self):
        session_response = self.client.post(
            "/api/auth/guest-session/",
            {
                "username": "RefreshUser",
                "character": "captain",
                "device_id": "1f9e9db5-c871-4a18-a1e2-a6b57791a736",
            },
            format="json",
        )
        self.assertEqual(session_response.status_code, 200)

        refresh_response = self.client.post("/api/auth/token/refresh/", {}, format="json")
        self.assertEqual(refresh_response.status_code, 200)
        self.assertIn("access_token", refresh_response.cookies)

        logout_response = self.client.post("/api/auth/logout/", {}, format="json")
        self.assertEqual(logout_response.status_code, 200)

        me_response = self.client.get("/api/auth/me/")
        self.assertEqual(me_response.status_code, 401)

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
