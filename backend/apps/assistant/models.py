import json
import uuid

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone


def credential_cipher():
    key = getattr(settings, "ASSISTANT_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("Assistant encryption is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("Assistant encryption key must be a Fernet key") from exc


class ChatGPTConnection(models.Model):
    user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, related_name="chatgpt_connections"
    )
    client_id = models.CharField(max_length=200)
    account_subject = models.CharField(max_length=255)
    host_id = models.CharField(max_length=300, blank=True)
    scopes = models.JSONField(default=list)
    credentials_ciphertext = models.TextField(blank=True)
    status = models.CharField(max_length=24, default="connected")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "client_id", "account_subject"),
                name="assistant_user_client_subject_uniq",
            )
        ]

    def set_credentials(self, credentials):
        self.credentials_ciphertext = (
            credential_cipher().encrypt(json.dumps(credentials).encode()).decode()
        )

    def get_credentials(self):
        if not self.credentials_ciphertext:
            return {}
        return json.loads(
            credential_cipher().decrypt(self.credentials_ciphertext.encode())
        )


class AssistantUsage(models.Model):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    household_id = models.UUIDField()
    created_at = models.DateTimeField(default=timezone.now)


class AssistantToolExecution(models.Model):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    household_id = models.UUIDField()
    request_uuid = models.UUIDField()
    call_index = models.PositiveSmallIntegerField()
    tool_name = models.CharField(max_length=80)
    arguments_hash = models.CharField(max_length=64)
    result = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "household_id", "request_uuid", "call_index"),
                name="assistant_tool_execution_identity_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(call_index__lte=32767),
                name="assistant_tool_execution_index_bounded",
            ),
        ]


class AssistantPairing(models.Model):
    pairing_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, related_name="assistant_pairings"
    )
    pairing_code_hash = models.CharField(max_length=64, unique=True)
    host_id = models.CharField(max_length=300)
    status = models.CharField(max_length=24, default="pending")
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now)
    pending_ciphertext = models.TextField(blank=True)
    helper_token_hash = models.CharField(max_length=64, blank=True)

    def set_pending(self, pending):
        self.pending_ciphertext = (
            credential_cipher().encrypt(json.dumps(pending).encode()).decode()
        )

    def get_pending(self):
        if not self.pending_ciphertext:
            return {}
        return json.loads(credential_cipher().decrypt(self.pending_ciphertext.encode()))


class AssistantHostIdentity(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    host_id = models.CharField(max_length=300)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1), name="assistant_host_identity_singleton"
            )
        ]


class AssistantActionProposal(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"
        STALE = "stale", "Stale"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    household = models.ForeignKey("households.Household", on_delete=models.CASCADE)
    action_type = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    snapshot = models.JSONField(default=dict)
    preview = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict)


class AssistantClarification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    household = models.ForeignKey("households.Household", on_delete=models.CASCADE)
    context_ciphertext = models.TextField()
    question = models.CharField(max_length=500)
    options = models.JSONField(default=list)
    answer = models.CharField(max_length=4000, blank=True)
    processing = models.BooleanField(default=False)
    response = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

    def set_context(self, context):
        self.context_ciphertext = (
            credential_cipher()
            .encrypt(json.dumps(context, ensure_ascii=False).encode())
            .decode()
        )

    def get_context(self):
        return json.loads(credential_cipher().decrypt(self.context_ciphertext.encode()))
