from datetime import datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.chores.models import ChoreOccurrence
from apps.households.models import Household


def generate_occurrences(chore, start_date, end_date):
    """Generate local-calendar occurrences for inclusive household-local dates."""
    if end_date < start_date or (end_date - start_date).days > 366:
        raise ValueError("Date range must be ordered and no longer than 367 days.")
    if not chore.is_active:
        return 0
    tz = ZoneInfo(chore.household.timezone)
    rule = chore.recurrence_rule
    created = 0
    with transaction.atomic():
        Household.objects.select_for_update().get(pk=chore.household_id)
        day = start_date
        while day <= end_date:
            local = datetime.combine(day, time.min)
            if rule:
                frequency = rule["frequency"]
                due_time = time.fromisoformat(rule.get("time", "09:00"))
                matches = (
                    frequency == "daily"
                    or frequency == "weekly"
                    and day.weekday() == rule.get("weekday", day.weekday())
                    or frequency == "monthly"
                    and day.day == rule.get("day", day.day)
                )
                if matches:
                    local = datetime.combine(day, due_time)
                    assigned = chore.assignments.order_by("membership_id").first()
                    _, was_created = ChoreOccurrence.objects.get_or_create(
                        chore=chore,
                        due_at=timezone.make_aware(local, tz).astimezone(
                            dt_timezone.utc
                        ),
                        defaults={
                            "assigned_to": assigned.membership if assigned else None
                        },
                    )
                    created += was_created
            elif (
                chore.due_at
                and start_date <= chore.due_at.astimezone(tz).date() <= end_date
            ):
                _, was_created = ChoreOccurrence.objects.get_or_create(
                    chore=chore,
                    due_at=chore.due_at,
                    defaults={
                        "assigned_to": chore.assignments.order_by("membership_id")
                        .first()
                        .membership
                        if chore.assignments.exists()
                        else None
                    },
                )
                created += was_created
                break
            day += timedelta(days=1)
    return created
