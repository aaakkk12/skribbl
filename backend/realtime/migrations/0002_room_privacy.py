from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("realtime", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="room",
            name="is_private",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="room",
            name="password_hash",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
