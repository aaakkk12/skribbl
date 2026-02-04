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
