from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.households.models import Household, Invitation, Membership
from apps.households.permissions import require_membership
from apps.accounts.models import User
from apps.assistant.proposals import create_invitation_creation


def serialize(household, membership):
    return {
        "id": str(household.id),
        "name": household.name,
        "currency": household.currency,
        "timezone": household.timezone,
        "role": membership.role,
        "isArchived": household.is_archived,
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def households(request):
    if request.method == "GET":
        memberships = Membership.objects.filter(
            user=request.user, status__in=("active", "archived")
        ).select_related("household")
        return Response([serialize(m.household, m) for m in memberships])
    name = str(request.data.get("name", "")).strip()
    if not name or len(name) > 120:
        return Response(
            {"name": ["Informe um nome de até 120 caracteres."]}, status=400
        )
    try:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            if Membership.objects.filter(user=request.user, status="active").exists():
                return Response(
                    {"detail": "Você já participa de uma residência."}, status=409
                )
            household = Household.objects.create(name=name, created_by=request.user)
            membership = Membership.objects.create(
                household=household, user=request.user, role=Membership.Role.OWNER
            )
    except IntegrityError:
        return Response({"detail": "Você já participa de uma residência."}, status=409)
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
        household_id=household_id, status__in=("active", "archived")
    ).select_related("user")
    return Response(
        [
            {"id": m.id, "name": m.user.name, "email": m.user.email, "role": m.role}
            for m in qs
        ]
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def invitations(request, household_id):
    require_membership(request.user, household_id, owner=True)
    role = request.data.get("role", "member")
    if role not in ("member", "viewer"):
        return Response({"role": ["Papel inválido."]}, status=400)
    proposal = create_invitation_creation(
        user=request.user, household_id=household_id, role=role
    )
    return Response(proposal, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def accept_invitation(request, token):
    digest = Invitation.hash_token(token)
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        invitation = (
            Invitation.objects.select_for_update()
            .filter(
                token_hash=digest,
                accepted_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .first()
        )
        if invitation is None:
            return Response(
                {"detail": "Convite inválido, expirado ou já utilizado."}, status=404
            )
        household = Household.objects.select_for_update().get(
            pk=invitation.household_id
        )
        if household.is_archived:
            return Response({"detail": "Esta residência está arquivada."}, status=409)
        if (
            Membership.objects.filter(user=request.user, status="active")
            .exclude(household_id=invitation.household_id)
            .exists()
        ):
            return Response(
                {
                    "detail": "Você já participa de outra residência e não pode aceitar este convite."
                },
                status=409,
            )
        membership = (
            Membership.objects.select_for_update()
            .filter(household=invitation.household, user=request.user)
            .first()
        )
        if membership is not None and membership.status == "active":
            return Response(
                {"detail": "Você já participa desta residência."}, status=409
            )
        if membership is None:
            Membership.objects.create(
                household=invitation.household,
                user=request.user,
                role=invitation.role,
                status="active",
            )
        else:
            membership.role = invitation.role
            membership.status = "active"
            membership.joined_at = timezone.now()
            membership.save(update_fields=["role", "status", "joined_at"])
        invitation.accepted_at = timezone.now()
        invitation.token_ciphertext = ""
        invitation.save(update_fields=["accepted_at", "token_ciphertext"])
    return Response(
        {"householdId": str(invitation.household_id), "role": invitation.role}
    )
