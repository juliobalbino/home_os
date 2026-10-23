from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.households.models import Household, Invitation, Membership
from apps.households.permissions import require_membership


def serialize(household, membership):
    return {
        "id": str(household.id),
        "name": household.name,
        "currency": household.currency,
        "timezone": household.timezone,
        "role": membership.role,
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def households(request):
    if request.method == "GET":
        memberships = Membership.objects.filter(
            user=request.user, status="active"
        ).select_related("household")
        return Response([serialize(m.household, m) for m in memberships])
    name = str(request.data.get("name", "")).strip()
    if not name or len(name) > 120:
        return Response(
            {"name": ["Informe um nome de até 120 caracteres."]}, status=400
        )
    with transaction.atomic():
        household = Household.objects.create(name=name, created_by=request.user)
        membership = Membership.objects.create(
            household=household, user=request.user, role=Membership.Role.OWNER
        )
    return Response(serialize(household, membership), status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def household_detail(request, household_id):
    membership = require_membership(request.user, household_id)
    return Response(serialize(membership.household, membership))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def members(request, household_id):
    require_membership(request.user, household_id)
    qs = Membership.objects.filter(
        household_id=household_id, status="active"
    ).select_related("user")
    return Response(
        [{"name": m.user.name, "email": m.user.email, "role": m.role} for m in qs]
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def invitations(request, household_id):
    require_membership(request.user, household_id, owner=True)
    role = request.data.get("role", "member")
    if role not in ("member", "viewer"):
        return Response({"role": ["Papel inválido."]}, status=400)
    invitation, token = Invitation.issue(
        Household.objects.get(pk=household_id), request.user, role
    )
    return Response({"token": token, "expiresAt": invitation.expires_at}, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def accept_invitation(request, token):
    digest = Invitation.hash_token(token)
    with transaction.atomic():
        invitation = (
            Invitation.objects.select_for_update()
            .filter(
                token_hash=digest,
                accepted_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .first()
        )
        if invitation is None:
            return Response(
                {"detail": "Convite inválido, expirado ou já utilizado."}, status=404
            )
        membership, created = Membership.objects.get_or_create(
            household=invitation.household,
            user=request.user,
            defaults={"role": invitation.role, "status": "active"},
        )
        if not created:
            return Response(
                {"detail": "Você já participa desta residência."}, status=409
            )
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at"])
    return Response(
        {"householdId": str(invitation.household_id), "role": invitation.role}
    )
