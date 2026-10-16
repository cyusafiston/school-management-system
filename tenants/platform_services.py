"""Explicit platform lifecycle; no implicit school access for operators."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .audit import audit_event
from .models import School, SchoolMembership

TRANSITIONS = {
    'approve': ({'pending'}, 'approved'),
    'reject': ({'pending'}, 'rejected'),
    'suspend': ({'approved'}, 'suspended'),
    'reactivate': ({'suspended'}, 'approved'),
}


def require_operator(user):
    if not (user.is_authenticated and user.is_active and user.is_staff and user.is_superuser):
        raise PermissionDenied('An active platform operator is required.')


def transition_school(*, actor, school_id, action, request=None):
    require_operator(actor)
    if action not in TRANSITIONS:
        raise ValidationError('Unknown school lifecycle action.')
    allowed, target = TRANSITIONS[action]
    with transaction.atomic():
        school = School.objects.select_for_update().get(pk=school_id)
        if school.status not in allowed:
            raise ValidationError('This action is not valid for the current school status.')
        if action == 'approve':
            initial = SchoolMembership.objects.select_related('user').filter(
                school=school, user_id=school.created_by_id, role='administrator', is_active=True).first()
            if (not initial or not initial.user.is_active or initial.user.is_staff or initial.user.is_superuser
                    or not initial.user.email or type(initial.user).objects.filter(email__iexact=initial.user.email).count() != 1 or SchoolMembership.objects.filter(user=initial.user).exclude(school=school).exists()):
                raise ValidationError('Review the initial administrator account and email before approval.')
        school.status = target
        school.reviewed_by = actor
        school.reviewed_at = timezone.now()
        school.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
        audit_event('school.'+action, actor=actor, school_id=school.pk,
                    model='School', object_id=school.pk, changes={'status': target})
        if action == 'approve' and request is not None:
            from .admin_services import queue_setup_email
            queue_setup_email(request, initial.user)
        # Suspension preserves all memberships and historical records. Access
        # helpers check status on every request; reactivation never revives a
        # membership that the school separately deactivated.
        return school
