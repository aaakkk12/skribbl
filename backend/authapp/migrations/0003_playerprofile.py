from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("authapp", "0002_userstatus"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlayerProfile",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("display_name", models.CharField(blank=True, max_length=32)),
                ("avatar_color", models.CharField(default="#5eead4", max_length=7)),
                (
                    "avatar_eyes",
                    models.CharField(
                        choices=[("dot", "Dot"), ("happy", "Happy"), ("sleepy", "Sleepy")],
                        default="dot",
                        max_length=16,
                    ),
                ),
                (
                    "avatar_mouth",
                    models.CharField(
                        choices=[("smile", "Smile"), ("flat", "Flat"), ("open", "Open")],
                        default="smile",
                        max_length=16,
                    ),
                ),
                (
                    "avatar_accessory",
                    models.CharField(
                        choices=[
                            ("none", "None"),
                            ("cap", "Cap"),
                            ("crown", "Crown"),
                            ("glasses", "Glasses"),
                        ],
                        default="none",
                        max_length=16,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="player_profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
