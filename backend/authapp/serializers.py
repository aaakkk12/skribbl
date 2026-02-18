from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import PlayerProfile, UserStatus

User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value):
        normalized = value.lower()
        user = User.objects.filter(email__iexact=normalized).first()
        if user:
            status = getattr(user, "status", None)
            if status and status.is_deleted:
                raise serializers.ValidationError(
                    "Account is archived. Ask admin to restore."
                )
            if status and status.is_banned:
                raise serializers.ValidationError(
                    "Account is banned. Contact support."
                )
            raise serializers.ValidationError("Email is already in use.")
        return normalized

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        email = validated_data["email"].lower()
        user = User(
            username=email,
            email=email,
            first_name=validated_data.get("first_name", ""),
            last_name=validated_data.get("last_name", ""),
        )
        user.set_password(validated_data["password"])
        user.save()
        UserStatus.objects.get_or_create(user=user)
        PlayerProfile.objects.get_or_create(user=user)
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        validate_password(value)
        return value


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


class PlayerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlayerProfile
        fields = [
            "display_name",
            "avatar_color",
            "avatar_eyes",
            "avatar_mouth",
            "avatar_accessory",
        ]

    def validate_display_name(self, value):
        name = value.strip()
        if len(name) < 2:
            raise serializers.ValidationError("Display name must be at least 2 characters.")
        return name

    def validate_avatar_color(self, value):
        color = value.strip()
        if len(color) != 7 or not color.startswith("#"):
            raise serializers.ValidationError("Color must be a valid hex value like #5eead4.")
        return color



