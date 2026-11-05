from django.db import transaction
from django.utils import timezone


def archive_snapshot(household):
    from apps.households.models import Invitation, Membership

    memberships = list(
        Membership.objects.filter(household=household)
        .order_by("pk")
        .values("id", "user_id", "role", "status")
    )
    pending = list(
        Invitation.objects.filter(
            household=household,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    return {
        "household": {"id": str(household.pk), "name": household.name},
        "memberships": [
            {**row, "id": str(row["id"]), "user_id": str(row["user_id"])}
            for row in memberships
        ],
        "active_member_count": sum(row["status"] == "active" for row in memberships),
        "pending_invitation_ids": [str(pk) for pk in pending],
        "pending_invitation_count": len(pending),
    }


@transaction.atomic
def archive_household(user, household_id, expected_snapshot, proposal_id):
    from apps.audit.models import AuditEvent
    from apps.assistant.models import AssistantActionProposal
    from apps.households.models import Household, Invitation, Membership

    household = Household.objects.select_for_update().get(pk=household_id)
    memberships = list(
        Membership.objects.select_for_update()
        .filter(household=household)
        .order_by("pk")
    )
    invitations = list(
        Invitation.objects.select_for_update()
        .filter(household=household)
        .order_by("pk")
    )
    current = archive_snapshot(household)
    if household.is_archived or current != expected_snapshot:
        proposal = AssistantActionProposal.objects.select_for_update().get(
            pk=proposal_id
        )
        proposal.status = "stale"
        proposal.completed_at = timezone.now()
        proposal.save(update_fields=["status", "completed_at"])
        return {"status": "stale"}
    now = timezone.now()
    household.archived_at = now
    household.archived_by = user
    household.save(update_fields=["archived_at", "archived_by"])
    for membership in memberships:
        if membership.status == "active":
            membership.status = "archived"
            membership.save(update_fields=["status"])
    for invitation in invitations:
        if invitation.accepted_at is None and invitation.revoked_at is None:
            invitation.revoked_at = now
            invitation.token_ciphertext = ""
            invitation.save(update_fields=["revoked_at", "token_ciphertext"])
    AuditEvent.objects.create(
        household=household,
        actor=user,
        action="household.archived",
        entity_type="household",
        entity_id=str(household.pk),
        metadata={},
    )
    AssistantActionProposal.objects.filter(
        household=household, status="pending"
    ).exclude(pk=proposal_id).update(status="stale", completed_at=now)
    return {"status": "confirmed", "household_id": str(household.pk)}
