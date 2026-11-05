import uuid
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.accounts.models import (
    AccountDeactivationEvent,
    AccountDeactivationProposal,
    User,
)


class DeactivationConflict(APIException):
    status_code = 409
    default_code = "account_deactivation_conflict"

    def __init__(self, households):
        super().__init__(
            {
                "detail": "Transfer ownership before deactivating this account.",
                "blocking_households": households,
            }
        )


def _snapshot(user):
    from apps.households.models import Household, Invitation, Membership

    memberships = list(
        Membership.objects.filter(user=user)
        .order_by("pk")
        .values("id", "household_id", "role", "status", "joined_at")
    )
    invitations = list(
        Invitation.objects.filter(created_by=user)
        .order_by("pk")
        .values(
            "id",
            "household_id",
            "role",
            "created_at",
            "expires_at",
            "accepted_at",
            "revoked_at",
        )
    )
    households = {
        str(row.pk): row.name
        for row in Household.objects.filter(
            pk__in=[m["household_id"] for m in memberships]
            + [i["household_id"] for i in invitations]
        )
    }
    return {
        "memberships": [
            {
                **m,
                "household_id": str(m["household_id"]),
                "joined_at": m["joined_at"].isoformat(),
            }
            for m in memberships
        ],
        "invitations": [
            {
                **i,
                "household_id": str(i["household_id"]),
                "created_at": i["created_at"].isoformat(),
                "expires_at": i["expires_at"].isoformat(),
                "accepted_at": i["accepted_at"].isoformat()
                if i["accepted_at"]
                else None,
                "revoked_at": i["revoked_at"].isoformat() if i["revoked_at"] else None,
            }
            for i in invitations
        ],
        "households": households,
    }


def _lock_account_state(user):
    from apps.households.models import Household, Invitation, Membership

    locked_user = User.objects.select_for_update().get(pk=user.pk)
    list(
        Household.objects.select_for_update()
        .filter(Q(memberships__user=user) | Q(invitations__created_by=user))
        .distinct()
        .order_by("pk")
    )
    list(Membership.objects.select_for_update().filter(user=user).order_by("pk"))
    list(Invitation.objects.select_for_update().filter(created_by=user).order_by("pk"))
    owners = list(
        Household.objects.filter(
            memberships__user=user,
            memberships__role="owner",
            memberships__status="active",
            archived_at__isnull=True,
        )
        .values_list("name", flat=True)
        .distinct()
    )
    if owners:
        raise DeactivationConflict(owners)
    return locked_user


def create_account_deactivation_proposal(user):
    with transaction.atomic():
        user = _lock_account_state(user)
        snapshot = _snapshot(user)
        expires = timezone.now() + timedelta(minutes=15)
        preview = {
            "title": "Deactivate account?",
            "summary": "Your account access and assistant data will be removed.",
            "details": {
                "memberships_to_remove": sum(
                    m["status"] == "active" and m["role"] != "owner"
                    for m in snapshot["memberships"]
                ),
                "invitations_to_revoke": sum(
                    i["accepted_at"] is None and i["revoked_at"] is None
                    for i in snapshot["invitations"]
                ),
                "expires_at": expires.isoformat(),
            },
        }
        proposal = AccountDeactivationProposal.objects.create(
            actor=user, snapshot=snapshot, preview=preview, expires_at=expires
        )
    return {
        "proposal_id": str(proposal.pk),
        **preview,
        "expires_at": expires.isoformat(),
    }


def _deactivate_locked(user, proposal):
    from apps.audit.models import AuditEvent
    from apps.assistant.models import (
        AssistantActionProposal,
        AssistantPairing,
        AssistantToolExecution,
        AssistantUsage,
        ChatGPTConnection,
    )
    from apps.households.models import Invitation, Membership

    now = timezone.now()
    for membership in (
        Membership.objects.select_for_update()
        .filter(user=user, status="active")
        .exclude(role="owner")
        .select_related("household")
    ):
        membership.status = "removed"
        membership.save(update_fields=["status"])
        AuditEvent.objects.create(
            household=membership.household,
            actor=user,
            action="membership.removed",
            entity_type="membership",
            entity_id=str(membership.pk),
            metadata={"reason": "account_deactivated"},
        )
    for invitation in (
        Invitation.objects.select_for_update()
        .filter(created_by=user, accepted_at__isnull=True, revoked_at__isnull=True)
        .select_related("household")
    ):
        invitation.revoked_at = now
        invitation.token_ciphertext = ""
        invitation.save(update_fields=["revoked_at", "token_ciphertext"])
        AuditEvent.objects.create(
            household=invitation.household,
            actor=user,
            action="invitation.revoked",
            entity_type="invitation",
            entity_id=str(invitation.pk),
            metadata={"reason": "account_deactivated", "role": invitation.role},
        )
    ChatGPTConnection.objects.filter(user=user).delete()
    AssistantPairing.objects.filter(user=user).delete()
    AssistantUsage.objects.filter(user=user).delete()
    AssistantToolExecution.objects.filter(user=user).delete()
    AssistantActionProposal.objects.filter(actor=user, status="pending").update(
        status="stale", completed_at=now
    )
    AccountDeactivationProposal.objects.filter(actor=user, status="pending").exclude(
        pk=proposal.pk
    ).update(status="stale", completed_at=now)
    for session in Session.objects.all().iterator():
        try:
            if str(session.get_decoded().get("_auth_user_id")) == str(user.pk):
                session.delete()
        except (ValueError, TypeError):
            continue
    user.is_active = False
    user.email = f"deactivated-{uuid.uuid4()}@invalid.invalid"
    user.name = "Conta desativada"
    user.set_unusable_password()
    user.deactivated_at = now
    user.last_login = None
    user.save(
        update_fields=[
            "is_active",
            "email",
            "name",
            "password",
            "deactivated_at",
            "last_login",
        ]
    )
    AccountDeactivationEvent.objects.create(
        actor=user,
        action="account.deactivated",
        metadata={"proposal_id": str(proposal.pk)},
    )
    return {"status": "confirmed"}


def confirm_account_deactivation_proposal(user, proposal_id, confirm):
    if not isinstance(confirm, bool):
        return {"status": 400, "data": {"detail": "confirm must be a boolean."}}
    with transaction.atomic():
        proposal = (
            AccountDeactivationProposal.objects.select_for_update()
            .filter(pk=proposal_id, actor=user)
            .first()
        )
        if proposal is None:
            return {"status": 404, "data": {"detail": "Proposal not found."}}
        if proposal.status == "confirmed":
            return {"status": 200, "data": proposal.result}
        if proposal.status != "pending":
            return {"status": 409, "data": {"status": proposal.status}}
        if not confirm:
            proposal.status, proposal.completed_at = "cancelled", timezone.now()
            proposal.save(update_fields=["status", "completed_at"])
            return {"status": 200, "data": {"status": "cancelled"}}
        if proposal.expires_at <= timezone.now():
            proposal.status, proposal.completed_at = "expired", timezone.now()
            proposal.save(update_fields=["status", "completed_at"])
            return {"status": 410, "data": {"status": "expired"}}
        user = _lock_account_state(user)
        if _snapshot(user) != proposal.snapshot:
            proposal.status, proposal.completed_at = "stale", timezone.now()
            proposal.save(update_fields=["status", "completed_at"])
            return {"status": 409, "data": {"status": "stale"}}
        result = _deactivate_locked(user, proposal)
        proposal.status, proposal.completed_at, proposal.result = (
            "confirmed",
            timezone.now(),
            result,
        )
        proposal.save(update_fields=["status", "completed_at", "result"])
        return {"status": 200, "data": result}
