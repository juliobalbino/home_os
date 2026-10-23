import hashlib
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Household(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    currency = models.CharField(max_length=3, default="BRL")
    timezone = models.CharField(max_length=64, default="America/Sao_Paulo")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_households",
    )
    created_at = models.DateTimeField(auto_now_add=True)


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MEMBER = "member", "Member"
        VIEWER = "viewer", "Viewer"

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    status = models.CharField(max_length=10, default="active")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("household", "user"), name="unique_household_user"
            ),
            models.UniqueConstraint(
                fields=("user",),
                condition=Q(status="active"),
                name="unique_active_membership_per_user",
            ),
        ]


class Invitation(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="invitations"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    role = models.CharField(
        max_length=10, choices=(("member", "Member"), ("viewer", "Viewer"))
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    @staticmethod
    def hash_token(token):
        return hashlib.sha256(token.encode()).hexdigest()

    @classmethod
    def issue(cls, household, user, role):
        token = secrets.token_urlsafe(32)
        invitation = cls.objects.create(
            household=household,
            created_by=user,
            role=role,
            token_hash=cls.hash_token(token),
            expires_at=timezone.now() + timedelta(days=7),
        )
        return invitation, token
