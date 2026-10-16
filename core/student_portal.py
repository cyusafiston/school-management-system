"""School membership, identity and enrollment boundaries for student pages."""
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db.models import F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from core.models import (Attendance, ClassSubject, DailyClassAttendance, Grade,
                         Homework, Notice, StudentEnrollment, StudentProfile, Term,
                         TeacherAssignment)
from tenants.access import require_school_context, require_school_role


@dataclass(frozen=True)
class StudentContext:
    school: object
    student: object
    enrollment: object

    @property
    def term(self):
        return self.enrollment.term


def enrollments(student, school):
    return StudentEnrollment.objects.filter(
        school=school, student=student, student__school=school,
        academic_year__school=school, term__school=school,
        class_stream__school=school,
        term__academic_year_id=F('academic_year_id'),
    ).select_related('term', 'academic_year', 'class_stream')


def student_context(request, *, selected=True):
    membership = require_school_context(request.user)
    require_school_role(membership, 'student')
    student = get_object_or_404(StudentProfile, school=membership.school, user=request.user)
    # Explicitly reject attempted identity/tenant overrides; identity is server-derived.
    for key, expected in (('student_id', student.pk), ('school_id', membership.school.pk)):
        if key in request.GET and request.GET[key] != str(expected):
            raise Http404('Student context not found.')
    current = enrollments(student, membership.school).filter(status='Active', term__is_current=True)
    matches = list(current[:2])
    if len(matches) != 1:
        raise PermissionDenied('An active enrollment in the current school term is required.')
    enrollment = matches[0]
    if not selected and 'term_id' in request.GET and request.GET['term_id'] != str(enrollment.term_id):
        raise Http404('Only the current enrollment is available here.')
    if selected and 'term_id' in request.GET:
        try:
            term_id = int(request.GET['term_id'])
        except (TypeError, ValueError):
            raise Http404('Invalid term.')
        enrollment = get_object_or_404(
            enrollments(student, membership.school).filter(status__in=['Active', 'Completed']),
            term_id=term_id,
        )
    return StudentContext(membership.school, student, enrollment)


def curriculum(context):
    return ClassSubject.objects.filter(
        school=context.school, academic_year=context.enrollment.academic_year,
        academic_year__school=context.school, class_stream=context.enrollment.class_stream,
        class_stream__school=context.school, subject__school=context.school,
    ).select_related('subject').order_by('subject__name')


def assignments(context):
    return TeacherAssignment.objects.filter(
        school=context.school, term=context.term,
        term__school=context.school, term__academic_year=context.enrollment.academic_year,
        term__academic_year__school=context.school,
        current_class=context.enrollment.class_stream,
        current_class__school=context.school, subject__school=context.school,
        subject_id__in=curriculum(context).values('subject_id'),
    ).select_related('subject', 'teacher', 'term', 'current_class').order_by('subject__name', 'pk')


def grades(context):
    return Grade.objects.filter(
        school=context.school, student=context.student, student__school=context.school,
        term=context.term, term__school=context.school,
        term__academic_year=context.enrollment.academic_year,
        subject_id__in=curriculum(context).values('subject_id'),
        subject__school=context.school, status='Finalized',
    ).select_related('subject', 'term').order_by('subject__name')


def homework(context):
    return Homework.objects.filter(
        school=context.school, assignment__in=assignments(context),
    ).select_related('assignment__subject').order_by('-created_at', '-pk')


def notices(context):
    return Notice.objects.filter(school=context.school).filter(
        Q(target_class__isnull=True) | Q(target_class=context.enrollment.class_stream, target_class__school=context.school),
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.localdate())).order_by('-created_at', '-pk')


def personal_attendance(context):
    allowed = Q(pk__in=[])
    history = enrollments(context.student, context.school)
    for enrollment in history:
        allowed |= Q(assignment__term=enrollment.term, assignment__current_class=enrollment.class_stream)
    subject = Attendance.objects.filter(
        allowed, school=context.school, student=context.student,
        student__school=context.school, assignment__school=context.school,
        assignment__subject__school=context.school, assignment__term__school=context.school,
        assignment__term__academic_year__school=context.school,
        assignment__current_class__school=context.school,
    ).select_related('assignment__subject', 'assignment__term').order_by('-date', '-pk')
    daily = DailyClassAttendance.objects.filter(
        school=context.school, student=context.student, student__school=context.school,
        current_class__school=context.school,
        current_class_id__in=history.values('class_stream_id'),
    ).select_related('current_class').order_by('-date', '-pk')
    return subject, daily


def page_context(context):
    return {'school': context.school, 'student_profile': context.student,
            'student_enrollment': context.enrollment, 'class_stream': context.enrollment.class_stream,
            'current_term': context.term,
            'enrollment_options': enrollments(context.student, context.school).filter(status__in=['Active', 'Completed']).order_by('-academic_year__name', 'term__name')}
