from rest_framework.exceptions import NotFound, PermissionDenied

from apps.households.models import Membership


def require_membership(user, household_id, *, write=False, owner=False):
    membership = (
        Membership.objects.filter(
            user=user, household_id=household_id, status__in=("active", "archived")
        )
        .select_related("household")
        .first()
    )
    if membership is None:
        raise NotFound("Residência não encontrada")
    if (membership.status == "archived" or membership.household.is_archived) and (
        write or owner
    ):
        raise PermissionDenied("Esta residência está arquivada e é somente leitura")
    if owner and membership.role != Membership.Role.OWNER:
        raise PermissionDenied("Apenas o responsável pode realizar esta ação")
    if write and membership.role == Membership.Role.VIEWER:
        raise PermissionDenied("Este perfil tem acesso somente para leitura")
    return membership
