from django.conf import settings
from django.db import models
from django.contrib.auth.hashers import check_password, make_password


class Room(models.Model):
    code = models.CharField(max_length=8, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_rooms"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    empty_since = models.DateTimeField(null=True, blank=True)
    is_private = models.BooleanField(default=False)
    password_hash = models.CharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return self.code

    def set_password(self, raw_password: str) -> None:
        if raw_password:
            self.password_hash = make_password(raw_password)
        else:
            self.password_hash = ""

    def check_password(self, raw_password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password(raw_password, self.password_hash)


class RoomMember(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("room", "user")

    def __str__(self) -> str:
        return f"{self.room.code}:{self.user_id}"


class RoomInvite(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="invites")
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_room_invites"
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="received_room_invites"
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["to_user", "status"]),
            models.Index(fields=["room", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.room.code}:{self.from_user_id}->{self.to_user_id}:{self.status}"
