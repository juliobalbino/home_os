from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.assistant.models import AssistantActionProposal
from apps.households.permissions import require_membership

MAX_PROPOSAL_ITEMS = 500
PROPOSAL_TTL = timedelta(minutes=10)


def shopping_list_snapshot(shopping_list):
    from apps.shopping.models import ShoppingListItem

    items = list(
        ShoppingListItem.objects.select_for_update()
        .filter(shopping_list=shopping_list)
        .select_related("product")
        .order_by("id")[: MAX_PROPOSAL_ITEMS + 1]
    )
    if len(items) > MAX_PROPOSAL_ITEMS:
        raise ValueError("Shopping list exceeds the proposal limit")
    return {
        "list": {
            "id": str(shopping_list.pk),
            "name": shopping_list.name,
            "status": shopping_list.status,
        },
        "items": [
            {
                "id": str(item.pk),
                "product_id": str(item.product_id) if item.product_id else None,
                "product_name": item.product.name if item.product_id else None,
                "free_text_name": item.free_text_name,
                "quantity": str(item.quantity),
                "unit": item.unit,
                "priority": item.priority,
                "status": item.status,
            }
            for item in items
        ],
    }


def proposal_card(proposal):
    return {
        "proposal_id": str(proposal.pk),
        "kind": proposal.action_type,
        "title": proposal.preview["title"],
        "summary": proposal.preview["summary"],
        "details": proposal.preview["details"],
        "expires_at": proposal.expires_at.isoformat(),
    }


@transaction.atomic
def create_shopping_list_deletion(*, user, household_id, shopping_list_id):
    from apps.households.models import Household
    from apps.shopping.models import ShoppingList

    household = Household.objects.select_for_update().get(pk=household_id)
    require_membership(user, household.pk, write=True)
    try:
        shopping_list = ShoppingList.objects.select_for_update().get(
            pk=shopping_list_id, household=household
        )
    except (ShoppingList.DoesNotExist, ValueError, TypeError):
        raise ValueError("Shopping list not found")
    snapshot = shopping_list_snapshot(shopping_list)
    proposal = AssistantActionProposal.objects.create(
        actor=user,
        household=household,
        action_type="delete_shopping_list",
        payload={"shopping_list_id": str(shopping_list.pk)},
        snapshot=snapshot,
        preview={
            "title": "Delete shopping list?",
            "summary": f"Delete {shopping_list.name} and its {len(snapshot['items'])} items.",
            "details": snapshot,
        },
        expires_at=timezone.now() + PROPOSAL_TTL,
    )
    return proposal_card(proposal)


@transaction.atomic
def create_chore_occurrence_generation(
    *, user, household_id, chore_id, start_date, end_date
):
    from datetime import date
    from rest_framework.exceptions import ValidationError
    from apps.chores import services
    from apps.chores.models import Chore, ChoreOccurrence
    from apps.households.models import Household
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        if start.isoformat() != start_date or end.isoformat() != end_date:
            raise ValueError
        if end < start or (end - start).days > 366:
            raise ValueError
    except (TypeError, ValueError):
        raise ValidationError({"date_range": "Invalid date range."})
    household = Household.objects.select_for_update().get(pk=household_id)
    require_membership(user, household.pk, write=True)
    try:
        chore = Chore.objects.select_for_update().get(pk=chore_id, household=household)
    except (Chore.DoesNotExist, ValueError, TypeError):
        raise ValidationError({"chore_id": "Chore not found."})
    try:
        ZoneInfo(household.timezone)
        due_dates = services.scheduled_occurrence_datetimes(chore, start, end)
    except (ValueError, ZoneInfoNotFoundError, KeyError, TypeError):
        raise ValidationError({"schedule": "Invalid chore schedule or timezone."})
    if not chore.is_active or not (chore.recurrence_rule or chore.due_at):
        raise ValidationError({"schedule": "Chore must be active and scheduled."})
    assignments = list(
        chore.assignments.select_for_update()
        .order_by("membership_id")
        .values_list("membership_id", flat=True)
    )
    occurrence_rows = list(
        ChoreOccurrence.objects.select_for_update()
        .filter(chore=chore, due_at__in=due_dates)
        .order_by("due_at", "id")
        .values_list("id", "due_at")
    )
    existing_due_dates = {due_at for _, due_at in occurrence_rows}
    missing_due_dates = [
        due_at for due_at in due_dates if due_at not in existing_due_dates
    ]
    if not missing_due_dates:
        raise ValidationError("nothing remains to generate")
    snapshot = {
        "chore": {
            "id": str(chore.pk),
            "title": chore.title,
            "is_active": chore.is_active,
            "recurrence_rule": chore.recurrence_rule,
            "due_at": chore.due_at.isoformat() if chore.due_at else None,
            "assignment_ids": [str(value) for value in assignments],
        },
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "occurrence_ids": [str(occurrence_id) for occurrence_id, _ in occurrence_rows],
    }
    proposal = AssistantActionProposal.objects.create(
        actor=user,
        household=household,
        action_type="generate_chore_occurrences",
        payload={
            "chore_id": str(chore.pk),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
        snapshot=snapshot,
        preview={
            "title": "Generate chore occurrences?",
            "summary": f"Generate {len(missing_due_dates)} occurrences for {chore.title}.",
            "details": {
                "chore_title": chore.title,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "count": len(missing_due_dates),
                "due_at": [value.isoformat() for value in missing_due_dates],
            },
        },
        expires_at=timezone.now() + PROPOSAL_TTL,
    )
    return proposal_card(proposal)


@transaction.atomic
def create_membership_role_change(*, user, household_id, membership_id, role):
    from rest_framework.exceptions import ValidationError
    from apps.households.models import Household, Membership

    if role not in {Membership.Role.MEMBER, Membership.Role.VIEWER}:
        raise ValidationError({"role": "Invalid membership role."})
    household = Household.objects.select_for_update().get(pk=household_id)
    actor_membership = require_membership(user, household.pk, owner=True)
    try:
        target = (
            Membership.objects.select_for_update()
            .select_related("user")
            .get(pk=membership_id, household=household)
        )
    except (Membership.DoesNotExist, ValueError, TypeError):
        raise ValidationError({"membership_id": "Membership not found."})
    if target.pk == actor_membership.pk:
        raise ValidationError({"membership_id": "Cannot change your own membership."})
    if target.status != "active":
        raise ValidationError({"membership_id": "Membership is not active."})
    snapshot = {
        "membership_id": str(target.pk),
        "user_id": str(target.user_id),
        "name": target.user.name,
        "role": target.role,
        "status": target.status,
    }
    proposal = AssistantActionProposal.objects.create(
        actor=user,
        household=household,
        action_type="membership_role_change",
        payload={"membership_id": str(target.pk), "role": role},
        snapshot=snapshot,
        preview={
            "title": "Change membership role?",
            "summary": f"Change {target.user.name}'s role from {target.role} to {role}.",
            "details": {
                "membership_id": str(target.pk),
                "name": target.user.name,
                "from_role": target.role,
                "to_role": role,
            },
        },
        expires_at=timezone.now() + PROPOSAL_TTL,
    )
    return proposal_card(proposal)


@transaction.atomic
def create_membership_removal(*, user, household_id, membership_id):
    from rest_framework.exceptions import ValidationError
    from apps.households.models import Household, Membership

    household = Household.objects.select_for_update().get(pk=household_id)
    actor_membership = require_membership(user, household.pk, owner=True)
    try:
        target = (
            Membership.objects.select_for_update()
            .select_related("user")
            .get(pk=membership_id, household=household)
        )
    except (Membership.DoesNotExist, ValueError, TypeError):
        raise ValidationError({"membership_id": "Membership not found."})
    if target.pk == actor_membership.pk:
        raise ValidationError({"membership_id": "Cannot remove your own membership."})
    if target.status != "active":
        raise ValidationError({"membership_id": "Membership is not active."})
    if target.role == Membership.Role.OWNER:
        raise ValidationError({"membership_id": "Cannot remove an owner."})
    snapshot = {
        "membership_id": str(target.pk),
        "user_id": str(target.user_id),
        "name": target.user.name,
        "role": target.role,
        "status": target.status,
    }
    proposal = AssistantActionProposal.objects.create(
        actor=user,
        household=household,
        action_type="membership_removal",
        payload={"membership_id": str(target.pk)},
        snapshot=snapshot,
        preview={
            "title": "Remove household member?",
            "summary": f"Remove {target.user.name} from the household.",
            "details": {
                "membership_id": str(target.pk),
                "name": target.user.name,
                "role": target.role,
            },
        },
        expires_at=timezone.now() + PROPOSAL_TTL,
    )
    return proposal_card(proposal)


@transaction.atomic
def create_ownership_transfer(*, user, household_id, new_owner_membership_id):
    from rest_framework.exceptions import ValidationError
    from apps.households.models import Household, Membership

    household = Household.objects.select_for_update().get(pk=household_id)
    actor_membership = require_membership(user, household.pk, owner=True)
    memberships = list(
        Membership.objects.select_for_update()
        .select_related("user")
        .filter(household=household)
        .order_by("pk")
    )
    owners = [
        row
        for row in memberships
        if row.status == "active" and row.role == Membership.Role.OWNER
    ]
    if len(owners) != 1 or owners[0].pk != actor_membership.pk:
        raise ValidationError("Household must have exactly one active owner.")
    target = next(
        (row for row in memberships if row.pk == new_owner_membership_id), None
    )
    if target is None:
        raise ValidationError({"new_owner_membership_id": "Membership not found."})
    if target.pk == actor_membership.pk:
        raise ValidationError(
            {"new_owner_membership_id": "Cannot transfer ownership to yourself."}
        )
    if target.status != "active" or target.role != Membership.Role.MEMBER:
        raise ValidationError(
            {"new_owner_membership_id": "Target must be an active member."}
        )

    def member_snapshot(row):
        return {
            "membership_id": str(row.pk),
            "user_id": str(row.user_id),
            "name": row.user.name,
            "role": row.role,
            "status": row.status,
        }

    snapshot = {
        "old_owner": member_snapshot(actor_membership),
        "new_owner": member_snapshot(target),
    }
    proposal = AssistantActionProposal.objects.create(
        actor=user,
        household=household,
        action_type="ownership_transfer",
        payload={
            "old_owner_membership_id": str(actor_membership.pk),
            "new_owner_membership_id": str(target.pk),
        },
        snapshot=snapshot,
        preview={
            "title": "Transfer household ownership?",
            "summary": f"Transfer ownership from {actor_membership.user.name} to {target.user.name}.",
            "details": {
                "old_owner": snapshot["old_owner"],
                "new_owner": snapshot["new_owner"],
            },
        },
        expires_at=timezone.now() + PROPOSAL_TTL,
    )
    return proposal_card(proposal)


@transaction.atomic
def create_invitation_creation(*, user, household_id, role):
    from rest_framework.exceptions import ValidationError
    from apps.households.models import Household, Invitation

    if role not in {"member", "viewer"}:
        raise ValidationError({"role": "Invalid invitation role."})
    household = Household.objects.select_for_update().get(pk=household_id)
    owner = require_membership(user, household.pk, owner=True)
    if owner.status != "active":
        raise ValidationError("An active owner is required.")
    pending_ids = list(
        Invitation.objects.select_for_update()
        .filter(
            household=household,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    snapshot = {
        "owner_membership_id": str(owner.pk),
        "pending_invitation_ids": [str(i) for i in pending_ids],
    }
    proposal = AssistantActionProposal.objects.create(
        actor=user,
        household=household,
        action_type="invitation_creation",
        payload={"role": role},
        snapshot=snapshot,
        preview={
            "title": "Create household invitation?",
            "summary": f"Invite someone as {role}; expires in 7 days.",
            "details": {"role": role, "expires_in_days": 7},
        },
        expires_at=timezone.now() + PROPOSAL_TTL,
    )
    return proposal_card(proposal)


@transaction.atomic
def create_household_archive(*, user, household_id):
    from rest_framework.exceptions import PermissionDenied
    from apps.households.models import Household
    from apps.households.services import archive_snapshot

    household = Household.objects.select_for_update().get(pk=household_id)
    owner = require_membership(user, household.pk, owner=True)
    if owner.status != "active":
        raise PermissionDenied("An active owner is required.")
    snapshot = archive_snapshot(household)
    proposal = AssistantActionProposal.objects.create(
        actor=user,
        household=household,
        action_type="household_archive",
        payload={},
        snapshot=snapshot,
        preview={
            "title": "Archive household?",
            "summary": f"Archive {household.name}; its data will be retained and read-only.",
            "details": {
                "household_name": household.name,
                "active_member_count": snapshot["active_member_count"],
                "pending_invitation_count": snapshot["pending_invitation_count"],
                "impact": "Data will be retained and become read-only.",
            },
        },
        expires_at=timezone.now() + PROPOSAL_TTL,
    )
    return proposal_card(proposal)


def _invitation_snapshot(invitation):
    return {
        "invitation_id": str(invitation.pk),
        "household_id": str(invitation.household_id),
        "role": invitation.role,
        "created_by_id": str(invitation.created_by_id),
        "created_at": invitation.created_at.isoformat(),
        "expires_at": invitation.expires_at.isoformat(),
        "accepted_at": invitation.accepted_at.isoformat()
        if invitation.accepted_at
        else None,
        "revoked_at": invitation.revoked_at.isoformat()
        if invitation.revoked_at
        else None,
    }


@transaction.atomic
def create_invitation_revocation(*, user, household_id, invitation_id):
    from rest_framework.exceptions import ValidationError
    from apps.households.models import Household, Invitation

    household = Household.objects.select_for_update().get(pk=household_id)
    require_membership(user, household.pk, owner=True)
    invitation = (
        Invitation.objects.select_for_update()
        .filter(pk=invitation_id, household=household)
        .first()
    )
    if (
        invitation is None
        or invitation.accepted_at
        or invitation.revoked_at
        or invitation.expires_at <= timezone.now()
    ):
        raise ValidationError({"invitation_id": "Invitation is unavailable."})
    snapshot = _invitation_snapshot(invitation)
    proposal = AssistantActionProposal.objects.create(
        actor=user,
        household=household,
        action_type="invitation_revocation",
        payload={"invitation_id": str(invitation.pk)},
        snapshot=snapshot,
        preview={
            "title": "Revoke invitation?",
            "summary": f"Revoke the pending {invitation.role} invitation.",
            "details": {"role": invitation.role},
        },
        expires_at=timezone.now() + PROPOSAL_TTL,
    )
    return proposal_card(proposal)


def confirm_proposal(*, user, household_id, proposal_id, confirm):
    from apps.audit.models import AuditEvent
    from apps.households.models import Household
    from apps.shopping.models import ShoppingList, ShoppingListItem

    from apps.accounts.models import AccountDeactivationProposal

    account_proposal = AccountDeactivationProposal.objects.filter(
        pk=proposal_id, actor=user
    ).first()
    if account_proposal is not None:
        require_membership(user, household_id)
        from apps.accounts.services import confirm_account_deactivation_proposal

        return confirm_account_deactivation_proposal(user, proposal_id, confirm)

    with transaction.atomic():
        # Check actor-bound scope before returning proposal state to callers.
        proposal = AssistantActionProposal.objects.filter(
            pk=proposal_id, household_id=household_id
        ).first()
        if proposal is None:
            return {"status": 404, "data": {"error": "Proposal not found."}}
        household = Household.objects.select_for_update().get(pk=household_id)
        require_membership(user, household.pk)
        if (
            household.is_archived
            and proposal.status == AssistantActionProposal.Status.PENDING
            and confirm
        ):
            proposal.status = "stale"
            proposal.completed_at = timezone.now()
            proposal.save(update_fields=["status", "completed_at"])
            return {"status": 409, "data": {"status": "stale"}}
        if proposal.status == AssistantActionProposal.Status.PENDING and confirm:
            require_membership(user, household.pk, write=True)
        if proposal.action_type in {
            "membership_role_change",
            "membership_removal",
            "invitation_creation",
            "invitation_revocation",
        }:
            require_membership(user, household.pk, owner=True)
        if proposal.actor_id != user.pk:
            return {"status": 403, "data": {"error": "Proposal not found."}}
        proposal = AssistantActionProposal.objects.select_for_update().get(
            pk=proposal.pk, actor=user, household=household
        )
        if proposal.status != AssistantActionProposal.Status.PENDING:
            if proposal.status == "confirmed":
                if proposal.action_type == "invitation_creation":
                    from apps.households.models import Invitation

                    invitation = Invitation.objects.filter(
                        pk=proposal.result.get("invitation_id"), household=household
                    ).first()
                    token = invitation.get_token() if invitation else None
                    if token is None:
                        return {"status": 409, "data": {"status": "stale"}}
                    return {"status": 200, "data": {**proposal.result, "token": token}}
                return {"status": 200, "data": proposal.result}
            status = 410 if proposal.status == "expired" else 409
            return {"status": status, "data": {"status": proposal.status}}
        if not confirm:
            proposal.status = "cancelled"
            proposal.completed_at = timezone.now()
            proposal.save(update_fields=["status", "completed_at"])
            return {"status": 200, "data": {"status": "cancelled"}}
        if proposal.expires_at <= timezone.now():
            proposal.status = "expired"
            proposal.completed_at = timezone.now()
            proposal.save(update_fields=["status", "completed_at"])
            return {"status": 410, "data": {"status": "expired"}}

        if proposal.action_type == "invitation_creation":
            from apps.audit.models import AuditEvent
            from apps.households.models import Invitation, Membership

            owner = require_membership(user, household.pk, owner=True)
            pending_ids = list(
                Invitation.objects.select_for_update()
                .filter(
                    household=household,
                    accepted_at__isnull=True,
                    revoked_at__isnull=True,
                    expires_at__gt=timezone.now(),
                )
                .order_by("pk")
                .values_list("pk", flat=True)
            )
            current = {
                "owner_membership_id": str(owner.pk),
                "pending_invitation_ids": [str(i) for i in pending_ids],
            }
            if owner.status != "active" or current != proposal.snapshot:
                proposal.status = "stale"
                proposal.completed_at = timezone.now()
                proposal.save(update_fields=["status", "completed_at"])
                return {"status": 409, "data": {"status": "stale"}}
            invitation, token = Invitation.issue(
                household, user, proposal.payload["role"]
            )
            result = {
                "status": "confirmed",
                "invitation_id": str(invitation.pk),
                "role": invitation.role,
                "expiresAt": invitation.expires_at.isoformat(),
            }
            AuditEvent.objects.create(
                household=household,
                actor=user,
                action="invitation.created",
                entity_type="invitation",
                entity_id=str(invitation.pk),
                metadata={
                    "role": invitation.role,
                    "expires_at": invitation.expires_at.isoformat(),
                },
            )
            proposal.status = "confirmed"
            proposal.completed_at = timezone.now()
            proposal.result = result
            proposal.save(update_fields=["status", "completed_at", "result"])
            return {"status": 200, "data": {**result, "token": token}}

        if proposal.action_type == "household_archive":
            require_membership(user, household.pk, owner=True)
            from apps.households.services import archive_household

            result = archive_household(
                user, household.pk, proposal.snapshot, proposal.pk
            )
            if result["status"] == "stale":
                return {"status": 409, "data": result}
            proposal.status = "confirmed"
            proposal.completed_at = timezone.now()
            proposal.result = result
            proposal.save(update_fields=["status", "completed_at", "result"])
            return {"status": 200, "data": result}

        if proposal.action_type == "invitation_revocation":
            from apps.audit.models import AuditEvent
            from apps.households.models import Invitation

            require_membership(user, household.pk, owner=True)
            invitation = (
                Invitation.objects.select_for_update()
                .filter(pk=proposal.payload["invitation_id"], household=household)
                .first()
            )
            if (
                invitation is None
                or invitation.accepted_at
                or invitation.revoked_at
                or invitation.expires_at <= timezone.now()
                or _invitation_snapshot(invitation) != proposal.snapshot
            ):
                proposal.status = "stale"
                proposal.completed_at = timezone.now()
                proposal.save(update_fields=["status", "completed_at"])
                return {"status": 409, "data": {"status": "stale"}}
            invitation.revoked_at = timezone.now()
            invitation.token_ciphertext = ""
            invitation.save(update_fields=["revoked_at", "token_ciphertext"])
            result = {
                "status": "confirmed",
                "invitation_id": str(invitation.pk),
            }
            AuditEvent.objects.create(
                household=household,
                actor=user,
                action="invitation.revoked",
                entity_type="invitation",
                entity_id=str(invitation.pk),
                metadata={"role": invitation.role},
            )
            proposal.status = "confirmed"
            proposal.completed_at = timezone.now()
            proposal.result = result
            proposal.save(update_fields=["status", "completed_at", "result"])
            return {"status": 200, "data": result}

        if proposal.action_type == "generate_chore_occurrences":
            return _confirm_chore_generation(proposal, user, household)
        if proposal.action_type == "membership_role_change":
            from apps.households.models import Membership

            actor_membership = require_membership(user, household.pk, owner=True)
            membership = (
                Membership.objects.select_for_update()
                .select_related("user")
                .filter(pk=proposal.payload.get("membership_id"), household=household)
                .first()
            )
            current = (
                {
                    "membership_id": str(membership.pk),
                    "user_id": str(membership.user_id),
                    "name": membership.user.name,
                    "role": membership.role,
                    "status": membership.status,
                }
                if membership is not None
                else None
            )
            if (
                membership is None
                or membership.pk == actor_membership.pk
                or membership.status != "active"
                or current != proposal.snapshot
            ):
                proposal.status = "stale"
                proposal.completed_at = timezone.now()
                proposal.save(update_fields=["status", "completed_at"])
                return {"status": 409, "data": {"status": "stale"}}
            new_role = proposal.payload.get("role")
            if new_role not in {Membership.Role.MEMBER, Membership.Role.VIEWER}:
                proposal.status = "stale"
                proposal.completed_at = timezone.now()
                proposal.save(update_fields=["status", "completed_at"])
                return {"status": 409, "data": {"status": "stale"}}
            old_role = membership.role
            membership.role = new_role
            membership.save(update_fields=["role"])
            result = {
                "status": "confirmed",
                "membership_id": str(membership.pk),
                "role": new_role,
            }
            AuditEvent.objects.create(
                household=household,
                actor=user,
                action="membership.role_changed",
                entity_type="membership",
                entity_id=str(membership.pk),
                metadata={
                    "user_id": str(membership.user_id),
                    "from_role": old_role,
                    "to_role": new_role,
                },
            )
            proposal.status = "confirmed"
            proposal.completed_at = timezone.now()
            proposal.result = result
            proposal.save(update_fields=["status", "completed_at", "result"])
            return {"status": 200, "data": result}
        if proposal.action_type == "membership_removal":
            from apps.households.models import Membership

            require_membership(user, household.pk, owner=True)
            membership = (
                Membership.objects.select_for_update()
                .select_related("user")
                .filter(pk=proposal.payload.get("membership_id"), household=household)
                .first()
            )
            current = (
                {
                    "membership_id": str(membership.pk),
                    "user_id": str(membership.user_id),
                    "name": membership.user.name,
                    "role": membership.role,
                    "status": membership.status,
                }
                if membership is not None
                else None
            )
            if (
                membership is None
                or membership.role == Membership.Role.OWNER
                or membership.status != "active"
                or current != proposal.snapshot
            ):
                proposal.status = "stale"
                proposal.completed_at = timezone.now()
                proposal.save(update_fields=["status", "completed_at"])
                return {"status": 409, "data": {"status": "stale"}}
            membership.status = "removed"
            membership.save(update_fields=["status"])
            result = {"status": "confirmed", "membership_id": str(membership.pk)}
            AuditEvent.objects.create(
                household=household,
                actor=user,
                action="membership.removed",
                entity_type="membership",
                entity_id=str(membership.pk),
                metadata={"user_id": str(membership.user_id), "role": membership.role},
            )
            proposal.status = "confirmed"
            proposal.completed_at = timezone.now()
            proposal.result = result
            proposal.save(update_fields=["status", "completed_at", "result"])
            return {"status": 200, "data": result}
        if proposal.action_type == "ownership_transfer":
            from apps.households.models import Membership

            actor_membership = require_membership(user, household.pk, owner=True)
            memberships = list(
                Membership.objects.select_for_update()
                .select_related("user")
                .filter(household=household)
                .order_by("pk")
            )
            owners = [
                row
                for row in memberships
                if row.status == "active" and row.role == Membership.Role.OWNER
            ]
            old_owner_id = proposal.payload.get("old_owner_membership_id")
            target_id = proposal.payload.get("new_owner_membership_id")
            old_owner = next(
                (row for row in memberships if str(row.pk) == old_owner_id), None
            )
            target = next(
                (row for row in memberships if str(row.pk) == target_id), None
            )

            def member_snapshot(row):
                return {
                    "membership_id": str(row.pk),
                    "user_id": str(row.user_id),
                    "name": row.user.name,
                    "role": row.role,
                    "status": row.status,
                }

            current = {
                "old_owner": member_snapshot(old_owner) if old_owner else None,
                "new_owner": member_snapshot(target) if target else None,
            }
            if (
                len(owners) != 1
                or owners[0].pk != actor_membership.pk
                or old_owner is None
                or old_owner.pk != actor_membership.pk
                or target is None
                or target.pk == old_owner.pk
                or target.role != Membership.Role.MEMBER
                or target.status != "active"
                or current != proposal.snapshot
            ):
                proposal.status = "stale"
                proposal.completed_at = timezone.now()
                proposal.save(update_fields=["status", "completed_at"])
                return {"status": 409, "data": {"status": "stale"}}
            old_owner.role = Membership.Role.MEMBER
            target.role = Membership.Role.OWNER
            old_owner.save(update_fields=["role"])
            target.save(update_fields=["role"])
            result = {
                "status": "confirmed",
                "old_owner_membership_id": str(old_owner.pk),
                "new_owner_membership_id": str(target.pk),
            }
            AuditEvent.objects.create(
                household=household,
                actor=user,
                action="household.ownership_transferred",
                entity_type="membership",
                entity_id=str(target.pk),
                metadata={
                    "old_owner_membership_id": str(old_owner.pk),
                    "new_owner_membership_id": str(target.pk),
                },
            )
            proposal.status = "confirmed"
            proposal.completed_at = timezone.now()
            proposal.result = result
            proposal.save(update_fields=["status", "completed_at", "result"])
            return {"status": 200, "data": result}
        if proposal.action_type != "delete_shopping_list":
            return {"status": 409, "data": {"status": "stale"}}
        list_id = proposal.payload.get("shopping_list_id")
        shopping_list = (
            ShoppingList.objects.select_for_update()
            .filter(pk=list_id, household=household)
            .first()
        )
        if (
            shopping_list is None
            or shopping_list_snapshot(shopping_list) != proposal.snapshot
        ):
            proposal.status = "stale"
            proposal.completed_at = timezone.now()
            proposal.save(update_fields=["status", "completed_at"])
            return {"status": 409, "data": {"status": "stale"}}

        item_ids = [row["id"] for row in proposal.snapshot["items"]]
        ShoppingListItem.objects.filter(shopping_list=shopping_list).delete()
        list_pk = str(shopping_list.pk)
        shopping_list.delete()
        result = {"status": "confirmed", "shopping_list_id": list_pk}
        AuditEvent.objects.create(
            household=household,
            actor=user,
            action="shopping_list.deletion_confirmed",
            entity_type="shopping_list",
            entity_id=list_pk,
            metadata={
                "shopping_list_id": list_pk,
                "item_ids": sorted(item_ids),
                "item_count": len(item_ids),
            },
        )
        proposal.status = "confirmed"
        proposal.completed_at = timezone.now()
        proposal.result = result
        proposal.save(update_fields=["status", "completed_at", "result"])
        return {"status": 200, "data": result}


def _confirm_chore_generation(proposal, user, household):
    from datetime import date
    from apps.audit.models import AuditEvent
    from apps.chores import services
    from apps.chores.models import Chore, ChoreOccurrence

    chore = (
        Chore.objects.select_for_update()
        .filter(pk=proposal.payload["chore_id"], household=household)
        .first()
    )
    start, end = (
        date.fromisoformat(proposal.payload["start_date"]),
        date.fromisoformat(proposal.payload["end_date"]),
    )
    if chore is None:
        current = None
    else:
        assignments = list(
            chore.assignments.select_for_update()
            .order_by("membership_id")
            .values_list("membership_id", flat=True)
        )
        due_dates = (
            services.scheduled_occurrence_datetimes(chore, start, end)
            if chore.is_active
            else []
        )
        occurrences = list(
            ChoreOccurrence.objects.select_for_update()
            .filter(chore=chore, due_at__in=due_dates)
            .order_by("due_at", "id")
            .values_list("id", flat=True)
        )
        current = {
            "chore": {
                "id": str(chore.pk),
                "title": chore.title,
                "is_active": chore.is_active,
                "recurrence_rule": chore.recurrence_rule,
                "due_at": chore.due_at.isoformat() if chore.due_at else None,
                "assignment_ids": [str(value) for value in assignments],
            },
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "occurrence_ids": [str(value) for value in occurrences],
        }
    if current != proposal.snapshot:
        proposal.status = "stale"
        proposal.completed_at = timezone.now()
        proposal.save(update_fields=["status", "completed_at"])
        return {"status": 409, "data": {"status": "stale"}}
    count = services.generate_occurrences(chore, start, end)
    result = {
        "status": "confirmed",
        "chore_id": str(chore.pk),
        "generated_count": count,
    }
    AuditEvent.objects.create(
        household=household,
        actor=user,
        action="chore.occurrences_generated",
        entity_type="chore",
        entity_id=str(chore.pk),
        metadata={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "count": count,
        },
    )
    proposal.status = "confirmed"
    proposal.completed_at = timezone.now()
    proposal.result = result
    proposal.save(update_fields=["status", "completed_at", "result"])
    return {"status": 200, "data": result}
