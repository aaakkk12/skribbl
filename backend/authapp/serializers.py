import uuid

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import PlayerProfile

User = get_user_model()

GUEST_CHARACTER_CHOICES = [
    ("sprinter", "Sprinter"),
    ("captain", "Captain"),
    ("vision", "Vision"),
    ("joker", "Joker"),
    ("royal", "Royal"),
    ("ninja", "Ninja"),
]


class GuestSessionSerializer(serializers.Serializer):
    username = serializers.CharField(min_length=2, max_length=24)
    character = serializers.ChoiceField(choices=GUEST_CHARACTER_CHOICES)
    device_id = serializers.CharField(required=False, allow_blank=True, max_length=64)

    def validate_username(self, value: str):
        normalized = " ".join(value.strip().split())
        if len(normalized) < 2:
            raise serializers.ValidationError("Username must be at least 2 characters.")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-")
        if any(ch not in allowed for ch in normalized):
            raise serializers.ValidationError(
                "Username can contain letters, numbers, space, underscore, and hyphen only."
            )
        return normalized

    def validate_device_id(self, value: str):
        raw = (value or "").strip().lower()
        if not raw:
            return None
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError):
            return None


class UserSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    profile_completed = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "display_name",
            "profile_completed",
            "avatar",
        ]

    def _get_profile(self, obj):
        profile, _ = PlayerProfile.objects.get_or_create(user=obj)
        return profile

    def get_display_name(self, obj):
        profile = self._get_profile(obj)
        if profile.display_name:
            return profile.display_name
        if obj.first_name:
            return obj.first_name
        return obj.email.split("@")[0]

    def get_profile_completed(self, obj):
        profile = self._get_profile(obj)
        return bool((profile.display_name or "").strip())

    def get_avatar(self, obj):
        profile = self._get_profile(obj)
        return {
            "color": profile.avatar_color,
            "eyes": profile.avatar_eyes,
            "mouth": profile.avatar_mouth,
            "accessory": profile.avatar_accessory,
        }
