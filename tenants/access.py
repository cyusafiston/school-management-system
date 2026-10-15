"""Tenant access primitives for the School Management System.

This module does not enforce isolation automatically. Views, forms, admin,
services, and APIs must call these helpers and scope their querysets.
"""

from dataclasses import dataclass
from typing import Optional

from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import School, SchoolMembership


@dataclass(frozen=True)
class SchoolContext:
    school: School
    membership: SchoolMembership

    @property
    def role(self) -> str:
        return self.membership.role


def approved_memberships(user):
    """Active memberships in approved schools for an authenticated user."""
    if not user.is_authenticated or not user.is_active:
        return SchoolMembership.objects.none()

    return SchoolMembership.objects.select_related("school").filter(
        user=user,
        is_active=True,
        school__status=School.Status.APPROVED,
    )


def require_school_context(user, *, school_id: Optional[int] = None) -> SchoolContext:
    """Resolve one permitted school; refuse missing or ambiguous context.

    A platform superuser does not implicitly become a school member. Separate
    platform administration flows should be used for cross-school operations.
    """
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied("An active account is required.")

    if user.is_superuser:
        raise PermissionDenied("Use the platform administration interface.")

    memberships = approved_memberships(user)
    if school_id is not None:
        membership = memberships.filter(school_id=school_id).first()
        if membership is None:
            raise Http404("School not found.")
    else:
        matches = list(memberships[:2])
        if not matches:
            raise PermissionDenied("No active membership in an approved school.")
        if len(matches) > 1:
            raise PermissionDenied("Select a school before continuing.")
        membership = matches[0]

    return SchoolContext(school=membership.school, membership=membership)


def require_school_role(context: SchoolContext, *allowed_roles: str) -> SchoolContext:
    """Check the role of the membership in the already-resolved school."""
    if not allowed_roles or context.role not in allowed_roles:
        raise PermissionDenied("You do not have permission for this action.")
    return context


def school_queryset(model, context: SchoolContext):
    """Return only records owned by the resolved school.

    Do not use on models without a direct `school` foreign key.
    """
    return model._default_manager.filter(school=context.school)
