"""School administrator workflows. Identity and school always come from membership."""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetConfirmView
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods

from core.models import (AcademicYear, ClassStream, Grade, StudentEnrollment,
                         StudentProfile, Subject, Term, UserProfile)
from tenants.access import require_school_context, require_school_role
from tenants.models import SchoolMembership
from tenants.admin_forms import (EnrollmentForm, StaffInvitationForm, StaffMembershipForm,
                                StudentRegistrationForm, TermForm, YearForm,
                                SchoolPasswordResetForm)
from tenants.forms import ClassStreamForm, SubjectSetupForm
from tenants.admin_services import (account_is_school_owned, enroll_student, lock_school,
                                   queue_setup_email, update_staff_membership, align_registration_counter)


def administrator(request):
    context = require_school_context(request.user)
    return require_school_role(context, 'administrator')


def school_students(context):
    from django.db.models import Q
    return StudentProfile.objects.filter(
        school=context.school, user__school_memberships__school=context.school,
        user__school_memberships__role='student',
    ).filter(Q(current_class__isnull=True) | Q(current_class__school=context.school))


def page(request, context, title, **data):
    return render(request, 'tenants/administration.html', {'school': context.school, 'title': title, **data})


def form_errors(form, exc):
    form.add_error(None, 'The operation was not saved. ' + (' '.join(exc.messages) if isinstance(exc, ValidationError) else 'Check for an existing record.'))


@login_required
@require_http_methods(['GET', 'POST'])
def students(request):
    context = administrator(request)
    form = StudentRegistrationForm(request.POST if request.method == 'POST' else None, school=context.school)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                lock_school(context.school)
                if not Term.objects.filter(school=context.school, academic_year__school=context.school, is_current=True).exists():
                    raise ValidationError('Configure a current term before registering students.')
                align_registration_counter(context.school)
                student = form.save()
                user = student.user
                user.email = form.cleaned_data['email']
                user.save(update_fields=['email'])
                queue_setup_email(request, user)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, 'Student registered. Password setup email requested; no temporary password was issued.')
            return redirect('admin_student_detail', student_id=student.pk)
    records = school_students(context).select_related('user', 'current_class').order_by('last_name', 'first_name')
    return page(request, context, 'Student registration and accounts', form=form, students=records)


@login_required
@require_http_methods(['GET', 'POST'])
def student_detail(request, student_id):
    context = administrator(request)
    student = get_object_or_404(school_students(context).select_related('user'), pk=student_id)
    form = EnrollmentForm(request.POST if request.method == 'POST' else None, school=context.school)
    if request.method == 'POST' and form.is_valid():
        try:
            enroll_student(school=context.school, student=student, **form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, 'Enrollment updated. Historical records were preserved.')
            return redirect('admin_student_detail', student_id=student.pk)
    records = StudentEnrollment.objects.filter(school=context.school, student=student,
        academic_year__school=context.school, term__school=context.school,
        class_stream__school=context.school).select_related('term', 'academic_year', 'class_stream').order_by('-academic_year__name', 'term__name')
    return page(request, context, 'Student enrollment and history', form=form, student=student, enrollments=records, student_membership=SchoolMembership.objects.filter(school=context.school, user=student.user, role='student').first())


@login_required
@require_http_methods(['GET', 'POST'])
def staff(request):
    context = administrator(request)
    form = StaffInvitationForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                lock_school(context.school)
                values = {k: form.cleaned_data[k] for k in ('username', 'email', 'first_name', 'last_name')}
                user = get_user_model().objects.create_user(password=None, **values)
                role = form.cleaned_data['role']
                UserProfile.objects.filter(user=user).update(role=role.title())
                SchoolMembership.objects.create(school=context.school, user=user, role=role)
                queue_setup_email(request, user)
        except IntegrityError as exc:
            form_errors(form, exc)
        else:
            messages.success(request, 'Staff account created. Password setup email requested.')
            return redirect('admin_staff')
    records = SchoolMembership.objects.filter(school=context.school, role__in=['teacher', 'accountant']).select_related('user')
    return page(request, context, 'Teacher and accountant memberships', form=form, staff=records)


@login_required
@require_http_methods(['GET', 'POST'])
def staff_edit(request, membership_id):
    context = administrator(request)
    membership = get_object_or_404(SchoolMembership.objects.select_related('user'), pk=membership_id, school=context.school, role__in=['teacher', 'accountant'])
    form = StaffMembershipForm(request.POST if request.method == 'POST' else None,
        initial={'role': membership.role, 'is_active': membership.is_active})
    if request.method == 'POST' and form.is_valid():
        try:
            update_staff_membership(school=context.school, membership_id=membership.pk,
                role=form.cleaned_data['role'], active=form.cleaned_data['is_active'])
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, 'School membership updated.')
            return redirect('admin_staff')
    return page(request, context, 'Edit staff membership', form=form, target_membership=membership)


@login_required
@require_POST
def account_recovery(request, membership_id):
    context = administrator(request)
    membership = get_object_or_404(SchoolMembership.objects.select_related('user'), pk=membership_id, school=context.school)
    if membership.role not in ('teacher', 'accountant', 'student') or not account_is_school_owned(membership.user, context.school):
        raise PermissionDenied('This account cannot be recovered through school administration.')
    # A disabled account remains disabled; recovery never revives it or changes flags.
    eligible = list(SchoolPasswordResetForm().get_users(membership.user.email))
    if membership.user not in eligible:
        messages.error(request, 'Recovery unavailable. Check the account email and active school membership.')
    else:
        with transaction.atomic():
            queue_setup_email(request, membership.user)
        messages.success(request, 'Account recovery email requested.')
    return redirect('admin_students' if membership.role == 'student' else 'admin_staff')


class SchoolPasswordResetConfirmView(PasswordResetConfirmView):
    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        if user and user in SchoolPasswordResetForm().get_users(user.email):
            return user
        return None


@login_required
@require_http_methods(['GET', 'POST'])
def academic_periods(request):
    context = administrator(request)
    form_kind = request.POST.get('action', 'create_year')
    form_class = {'create_year': YearForm, 'create_term': TermForm}.get(form_kind)
    if not form_class:
        raise Http404('Unknown period operation.')
    form = form_class(request.POST if request.method == 'POST' else None, school=context.school)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                lock_school(context.school)
                # Revalidate inside the school lock for concurrent duplicate creation.
                form.instance.full_clean()
                form.save()
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, 'Academic period created.')
            return redirect('admin_periods')
    return page(request, context, 'Academic years and terms', form=form, period_action=form_kind,
        year_form=YearForm(school=context.school), term_form=TermForm(school=context.school),
        years=AcademicYear.objects.filter(school=context.school).order_by('-name'),
        terms=Term.objects.filter(school=context.school, academic_year__school=context.school).select_related('academic_year'))


@login_required
@require_POST
def activate_term(request, term_id):
    context = administrator(request)
    term = get_object_or_404(Term, pk=term_id, school=context.school, academic_year__school=context.school)
    if request.POST.get('confirm') != 'yes':
        from django.http import HttpResponseBadRequest
        return HttpResponseBadRequest('Explicit transition confirmation is required.')
    with transaction.atomic():
        lock_school(context.school)
        Term.objects.filter(school=context.school, is_current=True).update(is_current=False)
        Term.objects.filter(pk=term.pk, school=context.school).update(is_current=True)
        AcademicYear.objects.filter(school=context.school).update(is_current=False)
        AcademicYear.objects.filter(pk=term.academic_year_id, school=context.school).update(is_current=True)
        # New term enrollment is separate; no old rows are rewritten or deleted.
    messages.success(request, 'Current term changed. Enroll or roll forward students into this term before portal access.')
    return redirect('admin_periods')


@login_required
@require_http_methods(['GET', 'POST'])
def academic_edit(request, kind, record_id):
    context = administrator(request)
    model, form_class = {'class': (ClassStream, ClassStreamForm), 'subject': (Subject, SubjectSetupForm)}.get(kind, (None, None))
    if model is None:
        raise Http404('Unknown academic record.')
    record = get_object_or_404(model, pk=record_id, school=context.school)
    old_max = (record.max_cat_marks, record.max_exam_marks) if kind == 'subject' else None
    form = form_class(request.POST if request.method == 'POST' else None, school=context.school, instance=record)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                lock_school(context.school)
                if kind == 'subject' and old_max != (form.instance.max_cat_marks, form.instance.max_exam_marks) and Grade.objects.filter(school=context.school, subject=record).exists():
                    raise ValidationError('Recorded grades prevent changing subject maxima.')
                form.save()
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, 'Academic record updated.')
            return redirect('academic_setup')
    return page(request, context, 'Edit academic record', form=form)


@login_required
@require_http_methods(['GET', 'POST'])
def rollover(request):
    from tenants.admin_forms import RolloverForm
    context = administrator(request)
    form = RolloverForm(request.POST if request.method == 'POST' else None, school=context.school)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                lock_school(context.school)
                source, target = form.cleaned_data['source'], form.cleaned_data['target']
                rows = list(StudentEnrollment.objects.select_for_update().filter(
                    school=context.school, term=source, academic_year=source.academic_year,
                    class_stream__school=context.school, student__school=context.school,
                    student__user__school_memberships__school=context.school,
                    student__user__school_memberships__role='student',
                    student__user__is_active=True,
                    student__user__school_memberships__is_active=True,
                    status__in=['Active', 'Completed']).select_related('student', 'class_stream'))
                if not rows:
                    raise ValidationError('No eligible enrollments were found.')
                for row in rows:
                    if StudentEnrollment.objects.filter(student=row.student, term=target).exists():
                        raise ValidationError("A target enrollment already exists. No students were rolled forward.")
                    enroll_student(school=context.school, student=row.student, term=target,
                        class_stream=form.cleaned_data['target_class'] or row.class_stream)
                    if row.status == 'Active':
                        row.status = 'Completed'
                        row.save(update_fields=['status'])
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, f'{len(rows)} enrollments rolled forward. Prior records were retained.')
            return redirect('admin_periods')
    return page(request, context, 'Roll enrollments forward', form=form)


@login_required
@require_POST
def student_access(request, student_id):
    context = administrator(request)
    student = get_object_or_404(StudentProfile.objects.select_related('user'), pk=student_id, school=context.school)
    if not account_is_school_owned(student.user, context.school):
        raise PermissionDenied('This account cannot be managed here.')
    with transaction.atomic():
        lock_school(context.school)
        membership = get_object_or_404(SchoolMembership.objects.select_for_update(),
            school=context.school, user=student.user, role='student')
        membership.is_active = request.POST.get('is_active') == 'on'
        membership.save(update_fields=['is_active'])
    messages.success(request, 'Student school access updated.')
    return redirect('admin_student_detail', student_id=student.pk)


@login_required
@require_http_methods(['GET', 'POST'])
def reassign_teacher(request, assignment_id):
    from core.models import TeacherAssignment
    from tenants.admin_forms import TeacherReassignmentForm
    context = administrator(request)
    assignment = get_object_or_404(TeacherAssignment, pk=assignment_id, school=context.school,
        current_class__school=context.school, subject__school=context.school,
        term__school=context.school, term__academic_year__school=context.school)
    form = TeacherReassignmentForm(request.POST if request.method == 'POST' else None, school=context.school)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                lock_school(context.school)
                assignment = TeacherAssignment.objects.select_for_update().get(pk=assignment.pk)
                teacher = form.cleaned_data['teacher']
                if TeacherAssignment.objects.filter(school=context.school, teacher=teacher,
                    current_class=assignment.current_class, subject=assignment.subject,
                    term=assignment.term).exclude(pk=assignment.pk).exists():
                    raise ValidationError('The teacher already has this assignment.')
                assignment.teacher = teacher
                assignment.save()
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, 'Teaching responsibility reassigned; academic records retained.')
            return redirect('teacher_assignment_management')
    return page(request, context, 'Reassign teaching responsibility', form=form)


@login_required
@require_http_methods(['GET', 'POST'])
def notices(request, notice_id=None):
    from core.models import Notice
    from django.db.models import Q
    from tenants.admin_forms import NoticeForm
    context = administrator(request)
    records = Notice.objects.filter(school=context.school).filter(
        Q(target_class__isnull=True) | Q(target_class__school=context.school))
    record = get_object_or_404(records, pk=notice_id) if notice_id is not None else None
    form = NoticeForm(request.POST if request.method == 'POST' else None, school=context.school, instance=record)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'School notice saved.')
        return redirect('admin_notices')
    return page(request, context, 'School notices', form=form, notices=records.order_by('-created_at'))
