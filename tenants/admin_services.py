"""Administration services; no global privilege changes or destructive history edits."""
import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from core.models import (Attendance, DailyClassAttendance, Grade, StudentEnrollment,
                         StudentProfile, TeacherAssignment, UserProfile)
from tenants.models import School, SchoolMembership

logger = logging.getLogger(__name__)


def lock_school(school):
    return School.objects.select_for_update().get(pk=school.pk)


def align_registration_counter(school):
    """Preserve imported registration numbers without trapping automatic numbering."""
    import re
    from django.utils import timezone
    from tenants.models import StudentRegistrationCounter
    year = timezone.localdate().year
    prefix = f"STU/{year}/"
    largest = 0
    for number in StudentProfile.objects.filter(school=school, registration_number__startswith=prefix).values_list('registration_number', flat=True):
        match = re.fullmatch(re.escape(prefix) + r"(\d+)", number)
        if match:
            largest = max(largest, int(match.group(1)))
    if largest >= 2147483647:
        raise ValidationError('Registration numbering requires operator review.')
    counter, _ = StudentRegistrationCounter.objects.get_or_create(school=school, year=year)
    if counter.last_number < largest:
        counter.last_number = largest
        counter.save(update_fields=['last_number'])


def account_is_school_owned(user, school):
    return (not user.is_staff and not user.is_superuser and
            not SchoolMembership.objects.filter(user=user).exclude(school=school).exists())


def queue_setup_email(request, user):
    """Send only to the saved email after successful transaction commit."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
    origin = getattr(settings, 'ACCOUNT_PUBLIC_ORIGIN', '').rstrip('/')
    link = origin + path if origin else request.build_absolute_uri(path)
    recipient = user.email
    def deliver():
        deliver_account_mail('Set up or recover your school account',
            f'Hello {user.get_full_name() or user.username},\n\nYour username is {user.username}.\n'
            f'Choose your password using this single-use, expiring link:\n{link}\n\n'
            'If you did not expect this message, contact your school. No password has been changed.',
            recipient)
    transaction.on_commit(deliver)


def deliver_account_mail(subject, body, recipient, from_email=None, html_message=None):
    # The existing settings default to a console backend. Never print live reset
    # tokens to application logs or write them as plaintext development files.
    if settings.EMAIL_BACKEND in {
        'django.core.mail.backends.console.EmailBackend',
        'django.core.mail.backends.filebased.EmailBackend',
        'django.core.mail.backends.dummy.EmailBackend',
    }:
        logger.warning('Account email requires a configured delivery backend; setup link was not logged or written.')
        return False
    try:
        sent = send_mail(subject, body, from_email or settings.DEFAULT_FROM_EMAIL,
                         [recipient], html_message=html_message)
        if not sent:
            logger.warning('School account email was not accepted by the email backend.')
        return bool(sent)
    except Exception:
        logger.warning('School account email delivery failed; administrator retry required.')
        return False


def enroll_student(*, school, student, term, class_stream, action='enroll'):
    if student.school_id != school.pk or term.school_id != school.pk or term.academic_year.school_id != school.pk or class_stream.school_id != school.pk:
        raise ValidationError('Enrollment records must belong to your school.')
    with transaction.atomic():
        lock_school(school)
        student = StudentProfile.objects.select_for_update().get(pk=student.pk, school=school)
        row = StudentEnrollment.objects.select_for_update().filter(student=student, term=term).first()
        if row and (row.school_id != school.pk or row.academic_year_id != term.academic_year_id
                    or row.class_stream.school_id != school.pk):
            raise ValidationError('Existing enrollment relationships require data-integrity review.')
        if action in ('transfer', 'complete', 'withdraw'):
            if row is None or row.school_id != school.pk or row.status != 'Active':
                raise ValidationError('An active enrollment in this school is required.')
            row.status = {'transfer': 'Transferred', 'complete': 'Completed', 'withdraw': 'Dropped'}[action]
            row.full_clean()
            row.save(update_fields=['status'])
            if term.is_current:
                StudentProfile.objects.filter(pk=student.pk).update(current_class=None)
                if action in ('transfer', 'withdraw'):
                    SchoolMembership.objects.filter(school=school, user=student.user).update(is_active=False)
            return row
        if action != 'enroll':
            raise ValidationError('Invalid enrollment action.')
        if row:
            if row.school_id != school.pk or row.academic_year_id != term.academic_year_id:
                raise ValidationError('Existing enrollment needs data-integrity review.')
            if row.status != 'Active':
                raise ValidationError('Historical enrollment cannot be reopened or overwritten.')
            if row.class_stream_id == class_stream.pk:
                raise ValidationError('This enrollment already exists.')
            activity = Grade.objects.filter(student=student, term=term).exists() or Attendance.objects.filter(student=student, assignment__term=term).exists() or DailyClassAttendance.objects.filter(student=student, current_class=row.class_stream).exists()
            if activity:
                raise ValidationError('Recorded academic history prevents changing this enrollment class. Use a new term or request a reviewed correction.')
            row.class_stream = class_stream
        else:
            row = StudentEnrollment(school=school, student=student, term=term,
                academic_year=term.academic_year, class_stream=class_stream, status='Active')
        row.full_clean()
        row.save()
        if term.is_current:
            StudentProfile.objects.filter(pk=student.pk).update(current_class=class_stream)
        return row


def update_staff_membership(*, school, membership_id, role, active):
    if role not in ('teacher', 'accountant'):
        raise ValidationError('Only teacher and accountant roles can be managed here.')
    with transaction.atomic():
        lock_school(school)
        membership = SchoolMembership.objects.select_for_update().select_related('user').get(pk=membership_id, school=school)
        if membership.role not in ('teacher', 'accountant') or not account_is_school_owned(membership.user, school):
            raise PermissionDenied('This account cannot be managed through school staff administration.')
        if membership.role == 'teacher' and role != 'teacher' and TeacherAssignment.objects.filter(school=school, teacher=membership.user, term__is_current=True).exists():
            raise ValidationError('Current teaching assignments must be resolved before changing this role.')
        membership.role = role
        membership.is_active = active
        membership.full_clean()
        membership.save(update_fields=['role', 'is_active'])
        # This account has exactly one school owner. Keep legacy model choice
        # validation compatible without changing global staff/superuser flags.
        UserProfile.objects.filter(user=membership.user).update(role=role.title())
        return membership
