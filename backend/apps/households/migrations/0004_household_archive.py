from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("households", "0003_invitation_revoked_at_invitation_token_ciphertext"),
    ]

    operations = [
        migrations.AddField(
            model_name="household",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="household",
            name="archived_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="archived_households",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
