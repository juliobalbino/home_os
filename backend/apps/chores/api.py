from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit.models import AuditEvent
from apps.chores.models import Chore, ChoreAssignment, ChoreCompletion, ChoreOccurrence
from apps.chores.services import generate_occurrences
from apps.households.models import Membership
from apps.households.permissions import require_membership


def _chore_data(chore):
    return {
        "id": chore.id,
        "title": chore.title,
        "description": chore.description,
        "category": chore.category,
        "recurrence_rule": chore.recurrence_rule,
        "due_at": chore.due_at,
        "is_active": chore.is_active,
        "assignment_ids": list(
            chore.assignments.values_list("membership_id", flat=True)
        ),
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def chores(request, household_id):
    membership = require_membership(
        request.user, household_id, write=request.method == "POST"
    )
    if request.method == "GET":
        return Response(
            [
                _chore_data(x)
                for x in Chore.objects.filter(
                    household=membership.household
                ).prefetch_related("assignments")
            ]
        )
    data = request.data
    title = data.get("title")
    description = data.get("description", "")
    category = data.get("category", "")
    rule = data.get("recurrence_rule")
    due = data.get("due_at")
    ids = data.get("assignment_ids", [])
    if (
        not isinstance(title, str)
        or not title.strip()
        or len(title) > 120
        or not isinstance(description, str)
        or len(description) > 4000
        or not isinstance(category, str)
        or len(category) > 80
        or not isinstance(ids, list)
    ):
        raise ValidationError({"detail": "Dados da tarefa inválidos."})
    if rule is not None:
        if (
            not isinstance(rule, dict)
            or rule.get("frequency") not in ("daily", "weekly", "monthly")
            or not isinstance(rule.get("time", "09:00"), str)
        ):
            raise ValidationError({"recurrence_rule": "Regra de recorrência inválida."})
        try:
            from datetime import time

            time.fromisoformat(rule.get("time", "09:00"))
            if (
                rule["frequency"] == "weekly"
                and not 0 <= int(rule.get("weekday", 0)) <= 6
            ):
                raise ValueError
            if (
                rule["frequency"] == "monthly"
                and not 1 <= int(rule.get("day", 1)) <= 31
            ):
                raise ValueError
        except (TypeError, ValueError):
            raise ValidationError({"recurrence_rule": "Regra de recorrência inválida."})
    if due:
        from django.utils.dateparse import parse_datetime

        due = parse_datetime(due) if isinstance(due, str) else None
        if not due or not timezone.is_aware(due):
            raise ValidationError({"due_at": "Informe uma data e hora com fuso."})
    if rule and due:
        raise ValidationError({"due_at": "Escolha prazo único ou recorrência."})
    if not all(isinstance(mid, int) and not isinstance(mid, bool) for mid in ids):
        raise ValidationError({"assignment_ids": "Responsáveis inválidos."})
    is_active = data.get("is_active", True)
    if not isinstance(is_active, bool):
        raise ValidationError({"is_active": "Valor inválido."})
    active_ids = set(
        Membership.objects.filter(
            household=membership.household, status="active", id__in=ids
        ).values_list("id", flat=True)
    )
    if len(active_ids) != len(set(ids)):
        raise ValidationError(
            {
                "assignment_ids": "Responsáveis devem ser membros ativos desta residência."
            }
        )
    with transaction.atomic():
        chore = Chore.objects.create(
            household=membership.household,
            title=title.strip(),
            description=description,
            category=category,
            recurrence_rule=rule,
            due_at=due,
            is_active=is_active,
            created_by=request.user,
        )
        ChoreAssignment.objects.bulk_create(
            [ChoreAssignment(chore=chore, membership_id=mid) for mid in active_ids]
        )
        AuditEvent.objects.create(
            household=membership.household,
            actor=request.user,
            action="chore.created",
            entity_type="chore",
            entity_id=str(chore.id),
            metadata={},
        )
    return Response(_chore_data(chore), status=201)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def chore_detail(request, chore_id):
    chore = Chore.objects.filter(pk=chore_id).first()
    if not chore:
        raise NotFound()
    require_membership(request.user, chore.household_id, write=True)
    for key, max_length in (("title", 120), ("description", 4000), ("category", 80)):
        if key in request.data:
            value = request.data[key]
            if (
                not isinstance(value, str)
                or len(value) > max_length
                or (key == "title" and not value.strip())
            ):
                raise ValidationError({key: "Valor inválido."})
            setattr(chore, key, value.strip() if key == "title" else value)
    if "is_active" in request.data:
        if not isinstance(request.data["is_active"], bool):
            raise ValidationError({"is_active": "Valor inválido."})
        chore.is_active = request.data["is_active"]
    if "assignment_ids" in request.data:
        ids = request.data["assignment_ids"]
        if not isinstance(ids, list) or not all(
            isinstance(mid, int) and not isinstance(mid, bool) for mid in ids
        ):
            raise ValidationError({"assignment_ids": "Responsáveis inválidos."})
        active = (
            set(
                Membership.objects.filter(
                    household_id=chore.household_id, status="active", id__in=ids
                ).values_list("id", flat=True)
            )
            if isinstance(ids, list)
            else set()
        )
        if len(active) != len(set(ids)):
            raise ValidationError({"assignment_ids": "Responsáveis inválidos."})
        with transaction.atomic():
            chore.save()
            chore.assignments.all().delete()
            ChoreAssignment.objects.bulk_create(
                [ChoreAssignment(chore=chore, membership_id=x) for x in active]
            )
    else:
        chore.save()
    AuditEvent.objects.create(
        household_id=chore.household_id,
        actor=request.user,
        action="chore.updated",
        entity_type="chore",
        entity_id=str(chore.id),
        metadata={},
    )
    return Response(_chore_data(chore))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def occurrences(request, household_id):
    member = require_membership(request.user, household_id)
    rows = ChoreOccurrence.objects.filter(
        chore__household=member.household
    ).select_related("chore", "assigned_to__user")
    return Response(
        [
            {
                "id": o.id,
                "chore_id": o.chore_id,
                "title": o.chore.title,
                "due_at": o.due_at,
                "assigned_to": o.assigned_to_id,
                "assigned_name": o.assigned_to.user.name if o.assigned_to_id else None,
                "status": o.status,
                "completions": list(
                    o.completions.values("completed_by__name", "completed_at")
                ),
            }
            for o in rows
        ]
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def generate(request, chore_id):
    chore = Chore.objects.filter(pk=chore_id).select_related("household").first()
    if not chore:
        raise NotFound()
    require_membership(request.user, chore.household_id, write=True)
    try:
        household_zone = ZoneInfo(chore.household.timezone)
        local_today = timezone.localdate(timezone=household_zone)
        start_value, end_value = request.data["start_date"], request.data["end_date"]
        start = (
            local_today if start_value == "today" else date.fromisoformat(start_value)
        )
        end = local_today if end_value == "today" else date.fromisoformat(end_value)
        created = generate_occurrences(chore, start, end)
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        raise ValidationError({"detail": "Intervalo de datas inválido."})
    return Response({"created": created})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def occurrence_action(request, occurrence_id):
    occurrence = (
        ChoreOccurrence.objects.filter(pk=occurrence_id).select_related("chore").first()
    )
    if not occurrence:
        raise NotFound()
    require_membership(request.user, occurrence.chore.household_id, write=True)
    status = request.data.get("status", "completed")
    if status not in ("completed", "skipped", "cancelled"):
        raise ValidationError({"status": "Status inválido."})
    with transaction.atomic():
        occurrence = ChoreOccurrence.objects.select_for_update().get(pk=occurrence_id)
        occurrence.status = status
        occurrence.save(update_fields=["status"])
        if status == "completed":
            ChoreCompletion.objects.create(
                occurrence=occurrence, completed_by=request.user
            )
        AuditEvent.objects.create(
            household_id=occurrence.chore.household_id,
            actor=request.user,
            action=f"chore_occurrence.{status}",
            entity_type="chore_occurrence",
            entity_id=str(occurrence.id),
            metadata={},
        )
    return Response({"id": occurrence.id, "status": occurrence.status})
