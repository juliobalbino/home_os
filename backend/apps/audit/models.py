from django.conf import settings
from django.db import models

from apps.households.models import Household


class AuditEvent(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="audit_events"
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=80)
    entity_type = models.CharField(max_length=40)
    entity_id = models.CharField(max_length=64)
    timestamp = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict)
