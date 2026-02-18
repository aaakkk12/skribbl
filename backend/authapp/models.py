import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ActiveSession(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="active_session"
    )
    session_id = models.UUIDField(default=uuid.uuid4, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.user_id}:{self.session_id}"


class UserStatus(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="status"
    )
    is_banned = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.user_id}:banned={self.is_banned},deleted={self.is_deleted}"


class PlayerProfile(models.Model):
    EYES_DOT = "dot"
    EYES_HAPPY = "happy"
    EYES_SLEEPY = "sleepy"
    EYES_CHOICES = [
        (EYES_DOT, "Dot"),
        (EYES_HAPPY, "Happy"),
        (EYES_SLEEPY, "Sleepy"),
    ]

    MOUTH_SMILE = "smile"
    MOUTH_FLAT = "flat"
    MOUTH_OPEN = "open"
    MOUTH_CHOICES = [
        (MOUTH_SMILE, "Smile"),
        (MOUTH_FLAT, "Flat"),
        (MOUTH_OPEN, "Open"),
    ]

    ACCESSORY_NONE = "none"
    ACCESSORY_CAP = "cap"
    ACCESSORY_CROWN = "crown"
    ACCESSORY_GLASSES = "glasses"
    ACCESSORY_CHOICES = [
        (ACCESSORY_NONE, "None"),
        (ACCESSORY_CAP, "Cap"),
        (ACCESSORY_CROWN, "Crown"),
        (ACCESSORY_GLASSES, "Glasses"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="player_profile"
    )
    display_name = models.CharField(max_length=32, blank=True)
    avatar_color = models.CharField(max_length=7, default="#5eead4")
    avatar_eyes = models.CharField(max_length=16, choices=EYES_CHOICES, default=EYES_DOT)
    avatar_mouth = models.CharField(max_length=16, choices=MOUTH_CHOICES, default=MOUTH_SMILE)
    avatar_accessory = models.CharField(
        max_length=16, choices=ACCESSORY_CHOICES, default=ACCESSORY_NONE
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.user_id}:{self.display_name or 'profile'}"


class Friendship(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="friend_links"
    )
    friend = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="friend_of_links"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "friend"], name="unique_friend_link"),
            models.CheckConstraint(check=~Q(user=F("friend")), name="no_self_friend"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}->{self.friend_id}"



