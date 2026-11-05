from datetime import datetime, time, timedelta, timezone as dt_timezone
from django.utils.dateparse import parse_datetime
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditEvent
from apps.chores.models import Chore, ChoreAssignment, ChoreCompletion, ChoreOccurrence
from apps.households.models import Household, Membership


def _validated_payload(payload, *, creating):
    allowed = {
        "title",
        "description",
        "category",
        "recurrence_rule",
        "due_at",
        "is_active",
        "assignment_ids",
    }
    if set(payload) - allowed:
        raise ValidationError({"detail": "Campos inválidos."})
    values = dict(payload)
    if creating:
        values.setdefault("description", "")
        values.setdefault("category", "")
        values.setdefault("recurrence_rule", None)
        values.setdefault("due_at", None)
        values.setdefault("is_active", True)
        values.setdefault("assignment_ids", [])
    for field, maximum in (("title", 120), ("description", 4000), ("category", 80)):
        if field in values:
            value = values[field]
            if (
                not isinstance(value, str)
                or len(value) > maximum
                or (field == "title" and not value.strip())
            ):
                raise ValidationError({field: "Valor inválido."})
            values[field] = value.strip() if field == "title" else value
    if "is_active" in values and not isinstance(values["is_active"], bool):
        raise ValidationError({"is_active": "Valor inválido."})
    if "due_at" in values:
        due = values["due_at"]
        if due is not None:
            due = parse_datetime(due) if isinstance(due, str) else None
            if not due or not timezone.is_aware(due):
                raise ValidationError({"due_at": "Informe uma data e hora com fuso."})
            values["due_at"] = due
    if "recurrence_rule" in values:
        rule = values["recurrence_rule"]
        if rule is not None:
            valid = isinstance(rule, dict)
            if valid:
                rule = dict(rule)
                values["recurrence_rule"] = rule
                rule.setdefault("time", "09:00")
                frequency = rule.get("frequency")
                required = {
                    "daily": {"frequency", "time"},
                    "weekly": {"frequency", "time", "weekday"},
                    "monthly": {"frequency", "time", "day"},
                }.get(frequency)
                valid = required is not None and set(rule) == required
            if valid:
                try:
                    if not isinstance(rule["time"], str) or len(rule["time"]) != 5:
                        raise ValueError
                    time.fromisoformat(rule["time"])
                    if frequency == "weekly":
                        valid = (
                            type(rule["weekday"]) is int and 0 <= rule["weekday"] <= 6
                        )
                    elif frequency == "monthly":
                        valid = type(rule["day"]) is int and 1 <= rule["day"] <= 31
                except (TypeError, ValueError, KeyError):
                    valid = False
            if not valid:
                raise ValidationError(
                    {"recurrence_rule": "Regra de recorrência inválida."}
                )
    if values.get("recurrence_rule") is not None and values.get("due_at") is not None:
        raise ValidationError({"due_at": "Escolha prazo único ou recorrência."})
    if "assignment_ids" in values:
        ids = values["assignment_ids"]
        if (
            not isinstance(ids, list)
            or any(type(mid) is not int or mid <= 0 for mid in ids)
            or len(ids) != len(set(ids))
        ):
            raise ValidationError({"assignment_ids": "Responsáveis inválidos."})
    return values


def chore_data(chore):
    return {
        "id": chore.id,
        "title": chore.title,
        "description": chore.description,
        "category": chore.category,
        "recurrence_rule": chore.recurrence_rule,
        "due_at": chore.due_at.isoformat() if chore.due_at else None,
        "is_active": chore.is_active,
        "assignment_ids": list(
            chore.assignments.order_by("membership_id").values_list(
                "membership_id", flat=True
            )
        ),
    }


def create_chore(*, household, actor, payload):
    values = _validated_payload(payload, creating=True)
    ids = values.pop("assignment_ids")
    with transaction.atomic():
        Household.objects.select_for_update().get(pk=household.pk)
        active = set(
            Membership.objects.select_for_update()
            .filter(household=household, status="active", id__in=ids)
            .values_list("id", flat=True)
        )
        if len(active) != len(ids):
            raise ValidationError(
                {
                    "assignment_ids": "Responsáveis devem ser membros ativos desta residência."
                }
            )
        chore = Chore.objects.create(household=household, created_by=actor, **values)
        ChoreAssignment.objects.bulk_create(
            [ChoreAssignment(chore=chore, membership_id=mid) for mid in ids]
        )
        AuditEvent.objects.create(
            household=household,
            actor=actor,
            action="chore.created",
            entity_type="chore",
            entity_id=str(chore.id),
            metadata={},
        )
    return chore


def update_chore(*, chore, actor, payload):
    values = _validated_payload(payload, creating=False)
    ids = values.pop("assignment_ids", None)
    with transaction.atomic():
        Household.objects.select_for_update().get(pk=chore.household_id)
        chore = Chore.objects.select_for_update().get(
            pk=chore.pk, household_id=chore.household_id
        )
        merged_due_at = values.get("due_at", chore.due_at)
        merged_recurrence = values.get("recurrence_rule", chore.recurrence_rule)
        if merged_due_at is not None and merged_recurrence is not None:
            raise ValidationError({"due_at": "Escolha prazo único ou recorrência."})
        if ids is not None:
            active = set(
                Membership.objects.select_for_update()
                .filter(household_id=chore.household_id, status="active", id__in=ids)
                .values_list("id", flat=True)
            )
            if len(active) != len(ids):
                raise ValidationError({"assignment_ids": "Responsáveis inválidos."})
        for key, value in values.items():
            setattr(chore, key, value)
        chore.save()
        if ids is not None:
            chore.assignments.all().delete()
            ChoreAssignment.objects.bulk_create(
                [ChoreAssignment(chore=chore, membership_id=mid) for mid in ids]
            )
        AuditEvent.objects.create(
            household_id=chore.household_id,
            actor=actor,
            action="chore.updated",
            entity_type="chore",
            entity_id=str(chore.id),
            metadata={},
        )
    return chore


def set_occurrence_status(*, occurrence, actor, status):
    if status not in ("completed", "skipped", "cancelled"):
        raise ValidationError({"status": "Status inválido."})
    with transaction.atomic():
        occurrence = (
            ChoreOccurrence.objects.select_for_update()
            .select_related("chore")
            .get(pk=occurrence.pk)
        )
        if occurrence.status != status:
            occurrence.status = status
            occurrence.save(update_fields=["status"])
            if status == "completed":
                ChoreCompletion.objects.create(
                    occurrence=occurrence, completed_by=actor
                )
            AuditEvent.objects.create(
                household_id=occurrence.chore.household_id,
                actor=actor,
                action=f"chore_occurrence.{status}",
                entity_type="chore_occurrence",
                entity_id=str(occurrence.id),
                metadata={},
            )
    return occurrence


def scheduled_occurrence_datetimes(chore, start_date, end_date):
    """Return exact UTC occurrence timestamps for an inclusive local date range."""
    if end_date < start_date or (end_date - start_date).days > 366:
        raise ValueError("Date range must be ordered and no longer than 367 days.")
    if not chore.is_active:
        raise ValueError("Chore must be active.")
    tz = ZoneInfo(chore.household.timezone)
    rule = chore.recurrence_rule
    due_dates = []
    if rule:
        due_time = time.fromisoformat(rule.get("time", "09:00"))
        day = start_date
        while day <= end_date:
            frequency = rule["frequency"]
            matches = (
                frequency == "daily"
                or frequency == "weekly"
                and day.weekday() == rule["weekday"]
                or frequency == "monthly"
                and day.day == rule["day"]
            )
            if matches:
                due_dates.append(
                    timezone.make_aware(datetime.combine(day, due_time), tz).astimezone(
                        dt_timezone.utc
                    )
                )
            day += timedelta(days=1)
    elif chore.due_at and start_date <= chore.due_at.astimezone(tz).date() <= end_date:
        due_dates.append(chore.due_at.astimezone(dt_timezone.utc))
    return due_dates


def generate_occurrences(chore, start_date, end_date):
    """Generate local-calendar occurrences for inclusive household-local dates."""
    due_dates = scheduled_occurrence_datetimes(chore, start_date, end_date)
    created = 0
    with transaction.atomic():
        Household.objects.select_for_update().get(pk=chore.household_id)
        assigned = chore.assignments.order_by("membership_id").first()
        for due_at in due_dates:
            _, was_created = ChoreOccurrence.objects.get_or_create(
                chore=chore,
                due_at=due_at,
                defaults={"assigned_to": assigned.membership if assigned else None},
            )
            created += was_created
    return created
