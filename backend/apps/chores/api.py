from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.chores.models import Chore, ChoreOccurrence
from apps.chores.services import (
    generate_occurrences,
    create_chore,
    update_chore,
    set_occurrence_status,
    chore_data,
)
from apps.households.permissions import require_membership


def _chore_data(chore):
    return chore_data(chore)


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
    chore = create_chore(
        household=membership.household, actor=request.user, payload=request.data
    )
    return Response(_chore_data(chore), status=201)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def chore_detail(request, chore_id):
    chore = Chore.objects.filter(pk=chore_id).first()
    if not chore:
        raise NotFound()
    require_membership(request.user, chore.household_id, write=True)
    chore = update_chore(chore=chore, actor=request.user, payload=request.data)
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
    occurrence = set_occurrence_status(
        occurrence=occurrence, actor=request.user, status=status
    )
    return Response({"id": occurrence.id, "status": occurrence.status})
