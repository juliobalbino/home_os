from django.conf import settings
from django.db import models

from apps.households.models import Household, Membership


class Chore(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="chores"
    )
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=80, blank=True)
    recurrence_rule = models.JSONField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class ChoreAssignment(models.Model):
    chore = models.ForeignKey(
        Chore, on_delete=models.CASCADE, related_name="assignments"
    )
    membership = models.ForeignKey(Membership, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("chore", "membership"), name="chores_unique_assignment"
            )
        ]


class ChoreOccurrence(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        SKIPPED = "skipped", "Skipped"
        CANCELLED = "cancelled", "Cancelled"

    chore = models.ForeignKey(
        Chore, on_delete=models.CASCADE, related_name="occurrences"
    )
    due_at = models.DateTimeField()
    assigned_to = models.ForeignKey(
        Membership, null=True, blank=True, on_delete=models.PROTECT
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("chore", "due_at"), name="chores_unique_occurrence_due"
            )
        ]
        ordering = ("due_at", "id")


class ChoreCompletion(models.Model):
    occurrence = models.ForeignKey(
        ChoreOccurrence, on_delete=models.CASCADE, related_name="completions"
    )
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    completed_at = models.DateTimeField(auto_now_add=True)
