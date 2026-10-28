import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0002_chatgptconnection_host_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssistantHostIdentity",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("host_id", models.CharField(max_length=300)),
            ],
        ),
        migrations.AddConstraint(
            model_name="assistanthostidentity",
            constraint=models.CheckConstraint(
                condition=models.Q(id=1), name="assistant_host_identity_singleton"
            ),
        ),
        migrations.CreateModel(
            name="AssistantPairing",
            fields=[
                (
                    "pairing_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("pairing_code_hash", models.CharField(max_length=64, unique=True)),
                ("host_id", models.CharField(max_length=300)),
                ("status", models.CharField(default="pending", max_length=24)),
                ("expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("pending_ciphertext", models.TextField(blank=True)),
                ("helper_token_hash", models.CharField(blank=True, max_length=64)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assistant_pairings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
