from django.views.decorators.http import require_POST, require_GET
from django.core.exceptions import PermissionDenied
from tenants.access import require_school_context
from decimal import Decimal, InvalidOperation
from django.http import HttpResponse, Http404 # Add HttpResponse here
from datetime import datetime, date
import calendar

from django.contrib import messages
from django.db import transaction
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required, user_passes_test, permission_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import PasswordChangeView
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse_lazy

from .models import (
    Attendance,
    ClassStream,
    DailyClassAttendance,
    Grade,
    Homework,
    Notice,
    StudentProfile,
    TeacherAssignment,
    Term,
    UserProfile,
)
# ---------------------------------------------------------------------------
# ROLE / ACCESS HELPERS
# ---------------------------------------------------------------------------

ROLE_ADMIN = "administrator"
ROLE_TEACHER = "teacher"
ROLE_STUDENT = "student"
ROLE_ACCOUNTANT = "accountant"


def get_user_role(user):
    """Return the normalized profile role."""
    profile = getattr(user, "profile", None)
    return (getattr(profile, "role", "") or "").strip().lower()


def is_admin(user):
    return bool(
        user.is_authenticated
        and (user.is_superuser or get_user_role(user) == ROLE_ADMIN)
    )


def is_teacher(user):
    return bool(user.is_authenticated and get_user_role(user) == ROLE_TEACHER)


def is_student(user):
    return bool(user.is_authenticated and get_user_role(user) == ROLE_STUDENT)


def is_accountant(user):
    return bool(
        user.is_authenticated
        and (
            get_user_role(user) == ROLE_ACCOUNTANT
            or user.groups.filter(name__iexact="Accountant").exists()
        )
    )


def deny_and_redirect(request, message="Access denied."):
    messages.error(request, message)
    return redirect("role_redirect")


def teacher_assignment_for_user(request, assignment_id):
    """Resolve an assignment through active school membership and ownership."""
    from tenants.access import require_school_role, school_queryset
    context = require_school_context(request.user)
    require_school_role(context, "teacher")
    return get_object_or_404(
        school_queryset(TeacherAssignment, context).select_related(
            "current_class", "subject", "term", "term__academic_year"
        ),
        pk=assignment_id, teacher=request.user,
        current_class__school=context.school, subject__school=context.school,
        term__school=context.school, term__academic_year__school=context.school,
    )


def assignment_students(assignment):
    """Active term enrollments, independent of a student's latest profile class."""
    return StudentProfile.objects.filter(
        school=assignment.school,
        enrollments__school=assignment.school,
        enrollments__academic_year=assignment.term.academic_year,
        enrollments__academic_year__school=assignment.school,
        enrollments__term=assignment.term,
        enrollments__term__school=assignment.school,
        enrollments__class_stream=assignment.current_class,
        enrollments__class_stream__school=assignment.school,
        enrollments__status="Active",
    ).distinct().order_by("id")


def teacher_can_access_class(user, class_stream):
    """Prevent a teacher from opening an unrelated class."""
    return TeacherAssignment.objects.filter(
        teacher=user,
        current_class=class_stream,
    ).exists()



def custom_login_view(request):
    if request.user.is_authenticated:
        logout(request)

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect_based_on_role(request)
    else:
        form = AuthenticationForm()

    return render(request, 'core/login.html', {'form': form})


def redirect_based_on_role(request):
    """
    Redirect users using their approved school membership,
    not the legacy global UserProfile role.
    """
    user = request.user

    if not user.is_authenticated:
        return redirect("login")

    # Platform superusers use the platform administration interface.
    if user.is_active and user.is_superuser:
        return redirect("admin:index")

    # School users must belong to exactly one approved school.
    try:
        context = require_school_context(user)
    except (PermissionDenied, Http404):
        logout(request)
        messages.error(
            request,
            "Your school access is unavailable. "
            "Please contact your school administrator."
        )
        return redirect("login")

    if context.role == "student":
        return redirect("student_dashboard")
    return redirect("school_home")


@login_required
def role_based_redirect_view(request):
    return redirect_based_on_role(request)


@login_required
def teacher_dashboard(request):
    """Tenant-isolated teacher dashboard."""
    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    context = require_school_context(request.user)
    require_school_role(context, "teacher")

    current_term = (
        school_queryset(Term, context)
        .filter(is_current=True)
        .order_by("pk")
        .first()
    )

    assignments = (
        school_queryset(TeacherAssignment, context)
        .filter(
            teacher=request.user,
            current_class__school=context.school,
            subject__school=context.school,
            term__school=context.school,
        )
        .select_related("subject", "current_class", "term")
    )

    if current_term:
        assignments = assignments.filter(term=current_term)

    return render(
        request,
        "core/teacher_dashboard.html",
        {
            "assignments": assignments,
            "current_term": current_term,
            "school": context.school,
        },
    )


@login_required
def teacher_classes_view(request):
    """Display only the approved teacher's school assignments."""
    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    context = require_school_context(request.user)
    require_school_role(context, "teacher")

    current_term = (
        school_queryset(Term, context)
        .filter(is_current=True)
        .order_by("pk")
        .first()
    )

    assignments = (
        school_queryset(TeacherAssignment, context)
        .filter(
            teacher=request.user,
            subject__school=context.school,
            current_class__school=context.school,
            term__school=context.school,
        )
        .select_related("subject", "current_class", "term")
    )

    if current_term:
        assignments = assignments.filter(term=current_term)

    return render(
        request,
        "core/teacher_classes.html",
        {
            "assignments": assignments,
            "current_term": current_term,
            "school": context.school,
        },
    )



@login_required
@require_POST
def finalize_grade_view(request, assignment_id, grade_id):
    """Finalize one draft grade for the teacher's own active enrollment."""
    from django.db import transaction
    from django.http import HttpResponseBadRequest
    from django.shortcuts import get_object_or_404, redirect
    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    context = require_school_context(request.user)
    require_school_role(context, "teacher")

    assignment = get_object_or_404(
        school_queryset(TeacherAssignment, context).filter(
            teacher=request.user,
            subject__school=context.school,
            current_class__school=context.school,
            term__school=context.school,
            term__academic_year__school=context.school,
        ),
        pk=assignment_id,
    )

    # The teacher's assignment must belong to the official curriculum.
    from core.models import ClassSubject

    curriculum_allowed = ClassSubject.objects.filter(
        school=context.school,
        academic_year=assignment.term.academic_year,
        class_stream=assignment.current_class,
        subject=assignment.subject,
        academic_year__school=context.school,
        class_stream__school=context.school,
        subject__school=context.school,
    ).exists()

    if not curriculum_allowed:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied(
            "This subject is not configured in the class curriculum."
        )


    if request.POST.get("confirm_finalize") != "yes":
        return HttpResponseBadRequest(
            "Grade finalization requires explicit confirmation."
        )

    with transaction.atomic():
        grade = get_object_or_404(
            school_queryset(Grade, context)
            .select_for_update()
            .filter(
                student__school=context.school,
                subject=assignment.subject,
                term=assignment.term,
                subject__school=context.school,
                term__school=context.school,
            ),
            pk=grade_id,
        )

        get_object_or_404(
            school_queryset(StudentEnrollment, context).filter(
                student=grade.student,
                student__school=context.school,
                academic_year=assignment.term.academic_year,
                academic_year__school=context.school,
                term=assignment.term,
                term__school=context.school,
                class_stream=assignment.current_class,
                class_stream__school=context.school,
                status="Active",
            )
        )

        if grade.status != "Draft":
            return HttpResponseBadRequest(
                "Only draft grades can be finalized."
            )

        from django.utils import timezone

        grade.status = "Finalized"
        grade.finalized_by = request.user
        grade.finalized_at = timezone.now()
        grade.save()

    messages.success(request, "Grade finalized successfully.")
    return redirect("input_grades", assignment_id=assignment.pk)


@login_required
def input_grades_view(request, assignment_id):
    """Secure, atomic grade entry for a teacher's own assignment."""
    from django.core.exceptions import ValidationError
    from django.db import transaction
    from django.shortcuts import get_object_or_404
    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    context = require_school_context(request.user)
    require_school_role(context, "teacher")

    assignment = get_object_or_404(
        school_queryset(TeacherAssignment, context).filter(
            teacher=request.user,
            subject__school=context.school,
            current_class__school=context.school,
            term__school=context.school,
            term__academic_year__school=context.school,
        ).select_related(
            "subject", "current_class", "term", "term__academic_year",
        ),
        pk=assignment_id,
    )

    # The teacher's assignment must belong to the official curriculum.
    from core.models import ClassSubject

    curriculum_allowed = ClassSubject.objects.filter(
        school=context.school,
        academic_year=assignment.term.academic_year,
        class_stream=assignment.current_class,
        subject=assignment.subject,
        academic_year__school=context.school,
        class_stream__school=context.school,
        subject__school=context.school,
    ).exists()

    if not curriculum_allowed:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied(
            "This subject is not configured in the class curriculum."
        )


    enrollments = (
        school_queryset(StudentEnrollment, context)
        .filter(
            academic_year=assignment.term.academic_year,
            term=assignment.term,
            class_stream=assignment.current_class,
            status="Active",
            student__school=context.school,
            academic_year__school=context.school,
            term__school=context.school,
            class_stream__school=context.school,
        )
        .select_related("student")
        .order_by("student__id")
    )

    students = [enrollment.student for enrollment in enrollments]
    student_ids = [student.pk for student in students]

    grades_map = {
        grade.student_id: grade
        for grade in school_queryset(Grade, context).filter(
            student_id__in=student_ids,
            student__school=context.school,
            subject=assignment.subject,
            term=assignment.term,
            subject__school=context.school,
            term__school=context.school,
        )
    }

    for student in students:
        student.grade = grades_map.get(student.pk)

    if request.method == "POST":
        from decimal import Decimal, InvalidOperation

        errors = []
        pending = []

        for student in students:
            cat_key = f"cat_{student.pk}"
            exam_key = f"exam_{student.pk}"

            cat_raw = request.POST.get(cat_key, "").strip()
            exam_raw = request.POST.get(exam_key, "").strip()

            if not cat_raw and not exam_raw:
                continue

            if not cat_raw or not exam_raw:
                errors.append(
                    f"{student}: Both CAT and exam marks are required."
                )
                continue

            try:
                cat_marks = Decimal(cat_raw)
                exam_marks = Decimal(exam_raw)
            except (InvalidOperation, ValueError):
                errors.append(f"{student}: Invalid numeric marks.")
                continue

            existing = grades_map.get(student.pk)

            if existing and existing.status == "Finalized":
                # Browsers submit readonly inputs too. Unchanged locked rows
                # must not prevent saving other students' draft marks.
                if (cat_marks == existing.cat_marks
                        and exam_marks == existing.exam_marks):
                    continue
                errors.append(
                    f"{student}: Finalized grades cannot be edited."
                )
                continue

            if existing:
                from copy import copy
                grade = copy(existing)
            else:
                grade = Grade(
                    school=context.school,
                    student=student,
                    subject=assignment.subject,
                    term=assignment.term,
                    status="Draft",
                )

            grade.cat_marks = cat_marks
            grade.exam_marks = exam_marks

            try:
                grade.full_clean()
            except ValidationError as exc:
                errors.append(f"{student}: {exc}")
                continue

            pending.append(grade)

        if errors:
            for error in errors:
                messages.error(request, error)
        elif not pending:
            messages.warning(request, "No grades were submitted.")
        else:
            try:
                with transaction.atomic():
                    # Use the same row lock as finalization. A grade that
                    # was finalized after the form loaded must stay locked.
                    for grade in pending:
                        if grade.pk:
                            school_queryset(Grade, context).select_for_update().get(pk=grade.pk)
                        grade.save()
            except ValidationError as exc:
                messages.error(
                    request,
                    f"Grades were not saved: {exc}",
                )
            else:
                messages.success(
                    request,
                    f"{len(pending)} grade record(s) saved successfully.",
                )
                return redirect(
                    "class_students",
                    assignment_id=assignment.pk,
                )

    return render(
        request,
        "core/input_grades.html",
        {
            "assignment": assignment,
            "students": students,
            "submitted_marks": request.POST if request.method == "POST" else None,
        },
    )


@login_required
def class_students_view(request, assignment_id):
    """Show active students for a teacher's own school assignment."""
    from django.shortcuts import get_object_or_404
    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    context = require_school_context(request.user)
    require_school_role(context, "teacher")

    assignment = get_object_or_404(
        school_queryset(TeacherAssignment, context).filter(
            teacher=request.user,
            subject__school=context.school,
            current_class__school=context.school,
            term__school=context.school,
            term__academic_year__school=context.school,
        ).select_related(
            "subject",
            "current_class",
            "term",
            "term__academic_year",
        ),
        pk=assignment_id,
    )

    enrollments = (
        school_queryset(StudentEnrollment, context)
        .filter(
            academic_year=assignment.term.academic_year,
            term=assignment.term,
            class_stream=assignment.current_class,
            status="Active",
            student__school=context.school,
            academic_year__school=context.school,
            term__school=context.school,
            class_stream__school=context.school,
        )
        .select_related("student")
        .order_by("student__id")
    )

    from django.db.models import Count

    enrollments = list(enrollments)
    student_ids = [enrollment.student_id for enrollment in enrollments]
    grades = {
        grade.student_id: grade
        for grade in school_queryset(Grade, context).filter(
            student_id__in=student_ids,
            student__school=context.school,
            subject=assignment.subject,
            term=assignment.term,
        )
    }
    attendance_counts = {}
    for row in (
        school_queryset(Attendance, context)
        .filter(assignment=assignment, student_id__in=student_ids,
                student__school=context.school)
        .values("student_id", "status")
        .annotate(total=Count("pk"))
    ):
        attendance_counts[(row["student_id"], row["status"])] = row["total"]

    student_data = [
        {
            "student": enrollment.student,
            "grade": grades.get(enrollment.student_id),
            "present": attendance_counts.get((enrollment.student_id, "Present"), 0),
            "absent": attendance_counts.get((enrollment.student_id, "Absent"), 0),
            "late": attendance_counts.get((enrollment.student_id, "Late"), 0),
        }
        for enrollment in enrollments
    ]

    return render(
        request,
        "core/class_students.html",
        {
            "assignment": assignment,
            "class_stream": assignment.current_class,
            "subject": assignment.subject,
            "student_data": student_data,
        },
    )


@login_required
def take_attendance_view(request, assignment_id):
    from datetime import date as attendance_date_type
    from django.core.exceptions import ValidationError
    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    context = require_school_context(request.user)
    require_school_role(context, "teacher")

    assignment = get_object_or_404(
        school_queryset(TeacherAssignment, context)
        .select_related("current_class", "subject", "term"),
        pk=assignment_id,
        teacher=request.user,
        subject__school=context.school,
        current_class__school=context.school,
        term__school=context.school,
        term__academic_year__school=context.school,
    )

    students = assignment_students(assignment)

    raw_date = (
        request.POST.get("attendance_date")
        if request.method == "POST"
        else request.GET.get("date")
    ) or date.today().isoformat()

    try:
        attendance_date = attendance_date_type.fromisoformat(
            str(raw_date)
        )
    except (ValueError, TypeError):
        if request.method == "POST":
            messages.error(request, "Invalid attendance date.")
            return redirect(
                "class_students",
                assignment_id=assignment.id,
            )
        raise Http404("Invalid attendance date.")

    if request.method == "POST":
        valid_statuses = {"Present", "Absent", "Late"}
        student_list = list(students)
        statuses = {}

        for student in student_list:
            status = request.POST.get(
                f"status_{student.id}"
            )
            if status not in valid_statuses:
                messages.error(
                    request,
                    "Every student must have a valid "
                    "attendance status.",
                )
                return redirect(
                    request.path
                    + "?date="
                    + attendance_date.isoformat()
                )
            statuses[student.id] = status

        try:
            with transaction.atomic():
                TeacherAssignment.objects.select_for_update().get(pk=assignment.pk)
                for student in student_list:
                    Attendance.objects.update_or_create(
                        school=context.school,
                        student=student,
                        assignment=assignment,
                        date=attendance_date,
                        defaults={
                            "status": statuses[student.id],
                            "recorded_by": request.user,
                        },
                    )
        except ValidationError:
            messages.error(
                request,
                "Attendance could not be saved. "
                "Please check the selected records.",
            )
            return redirect(
                request.path
                + "?date="
                + attendance_date.isoformat()
            )

        messages.success(
            request,
            f"Attendance for {attendance_date} "
            "saved successfully!",
        )
        return redirect(
            "class_students",
            assignment_id=assignment.id,
        )

    existing_attendance = {
        attendance.student_id: attendance.status
        for attendance in school_queryset(
            Attendance, context
        ).filter(
            assignment=assignment,
            date=attendance_date,
        )
    }

    student_data = [
        {
            "student": student,
            "status": existing_attendance.get(
                student.id, "Present"
            ),
        }
        for student in students
    ]

    return render(
        request,
        "core/take_attendance.html",
        {
            "assignment": assignment,
            "student_data": student_data,
            "attendance_date": attendance_date,
        },
    )



@login_required
def student_academic_profile_view(request, student_id):
    if not is_teacher(request.user):
        messages.error(request, "Access denied.")
        return redirect('/login/')

    student = get_object_or_404(StudentProfile, id=student_id)

    if not teacher_can_access_class(request.user, student.current_class):
        return deny_and_redirect(
            request,
            "Access denied. You can only view students in your assigned classes.",
        )

    grades = student.grades.select_related("subject", "term").all()

    context = {
        'student': student,
        'grades': grades,
    }
    return render(request, 'core/student_academic_profile.html', context)


@login_required
def admin_attendance_report_view(request):
    """School-isolated daily attendance report."""
    from datetime import date, datetime
    from django.shortcuts import render, get_object_or_404
    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    school_context = require_school_context(request.user)
    require_school_role(school_context, "administrator")

    selected_date_str = request.GET.get(
        "date", str(date.today())
    )

    try:
        parsed_date = datetime.strptime(
            selected_date_str, "%Y-%m-%d"
        ).date()
    except (ValueError, TypeError):
        parsed_date = date.today()

    selected_date_str = str(parsed_date)

    day = parsed_date.day
    suffix = (
        "th" if 11 <= day <= 13
        else {1: "st", 2: "nd", 3: "rd"}.get(
            day % 10, "th"
        )
    )

    formatted_date_display = parsed_date.strftime(
        f"%B {day}{suffix}, %Y"
    )

    classes = school_queryset(
        ClassStream, school_context
    )

    class_id = request.GET.get("class_id", "")

    if class_id:
        selected_class = get_object_or_404(
            classes, pk=class_id
        )
        class_id = str(selected_class.pk)

    students = school_queryset(
        StudentProfile, school_context
    ).filter(
        current_class__school=school_context.school
    )

    school_attendance_qs = school_queryset(
        DailyClassAttendance, school_context
    ).filter(
        date=parsed_date,
        student__school=school_context.school,
        current_class__school=school_context.school,
    )

    total_school_students = school_queryset(
        StudentProfile, school_context
    ).count()

    total_records = school_attendance_qs.count()
    present_count = school_attendance_qs.filter(
        status="Present"
    ).count()
    late_count = school_attendance_qs.filter(
        status="Late"
    ).count()
    absent_count = school_attendance_qs.filter(
        status="Absent"
    ).count()

    class_summaries = []

    for class_obj in classes:
        class_records = school_attendance_qs.filter(
            current_class=class_obj
        )

        first_record = class_records.select_related(
            "submitted_by"
        ).first()

        submitted_by = (
            first_record.submitted_by.username
            if first_record and first_record.submitted_by
            else None
        )

        class_summaries.append({
            "class_obj": class_obj,
            "total_students": students.filter(
                current_class=class_obj
            ).count(),
            "present_count": class_records.filter(
                status="Present"
            ).count(),
            "late_count": class_records.filter(
                status="Late"
            ).count(),
            "absent_count": class_records.filter(
                status="Absent"
            ).count(),
            "is_submitted": first_record is not None,
            "submitted_by": submitted_by,
        })

    attendance_qs = school_attendance_qs.select_related(
        "student",
        "current_class",
        "submitted_by",
    )

    if class_id:
        attendance_qs = attendance_qs.filter(
            current_class_id=class_id
        )

    context = {
        "formatted_date_display": formatted_date_display,
        "class_summaries": class_summaries,
        "attendance_records": attendance_qs,
        "selected_date": selected_date_str,
        "selected_class_id": class_id,
        "classes": classes,
        "total_school_students": total_school_students,
        "total_records": total_records,
        "present_count": present_count,
        "late_count": late_count,
        "absent_count": absent_count,
    }

    return render(
        request,
        "core/admin_attendance_report.html",
        context,
    )



@login_required
def admin_subject_attendance_report_view(request):
    """School-isolated subject attendance report."""
    from datetime import date, datetime
    from django.shortcuts import render, get_object_or_404
    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    school_context = require_school_context(request.user)
    require_school_role(school_context, "administrator")

    selected_date = request.GET.get(
        "date", str(date.today())
    )

    try:
        parsed_date = datetime.strptime(
            selected_date, "%Y-%m-%d"
        ).date()
    except (ValueError, TypeError):
        parsed_date = date.today()

    selected_date = str(parsed_date)

    classes = school_queryset(
        ClassStream, school_context
    )

    class_id = request.GET.get("class_id", "")

    if class_id:
        selected_class = get_object_or_404(
            classes, pk=class_id
        )
        class_id = str(selected_class.pk)

    attendance_qs = school_queryset(
        Attendance, school_context
    ).filter(
        date=parsed_date,
        student__school=school_context.school,
        assignment__school=school_context.school,
        assignment__current_class__school=school_context.school,
        assignment__subject__school=school_context.school,
    ).select_related(
        "student",
        "assignment__current_class",
        "assignment__subject",
        "recorded_by",
    )

    if class_id:
        attendance_qs = attendance_qs.filter(
            assignment__current_class_id=class_id
        )

    context = {
        "attendance_records": attendance_qs,
        "selected_date": selected_date,
        "selected_class_id": class_id,
        "classes": classes,
        "total_records": attendance_qs.count(),
        "present_count": attendance_qs.filter(
            status="Present"
        ).count(),
        "late_count": attendance_qs.filter(
            status="Late"
        ).count(),
        "absent_count": attendance_qs.filter(
            status="Absent"
        ).count(),
    }

    return render(
        request,
        "core/admin_subject_attendance_report.html",
        context,
    )



@login_required
def take_daily_attendance(request, class_id=None):
    from django.core.exceptions import ValidationError
    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    context = require_school_context(request.user)
    require_school_role(context, "teacher")

    assignments = school_queryset(
        TeacherAssignment, context
    ).filter(
        teacher=request.user,
        current_class__school=context.school,
        subject__school=context.school,
        term__school=context.school,
        term__is_current=True,
        term__academic_year__school=context.school,
    )

    assigned_class_ids = assignments.values_list(
        "current_class_id", flat=True
    )

    classes = school_queryset(
        ClassStream, context
    ).filter(
        pk__in=assigned_class_ids
    ).distinct().order_by("name")

    selected_class = None
    students = []
    already_submitted = False
    attendance_by_student = {}
    current_date = date.today()

    if class_id is not None:
        selected_class = get_object_or_404(
            classes,
            pk=class_id,
        )

        assignment = assignments.filter(current_class=selected_class).select_related("term__academic_year").first()
        students = list(assignment_students(assignment))

        today_records = school_queryset(
            DailyClassAttendance, context
        ).filter(
            current_class=selected_class,
            date=current_date,
            student__school=context.school,
        )

        attendance_by_student = {
            record.student_id: record
            for record in today_records.order_by("pk")
        }

        already_submitted = bool(attendance_by_student)

        for student in students:
            student.today_attendance = (
                attendance_by_student.get(student.pk)
            )

        if request.method == "POST":
            if already_submitted:
                messages.error(
                    request,
                    "Attendance has already been submitted "
                    "for this class today.",
                )
            elif not students:
                messages.error(
                    request,
                    "No students are assigned to this class.",
                )
            else:
                valid_statuses = {
                    "Present", "Late", "Absent"
                }

                statuses = {}

                for student in students:
                    status = request.POST.get(
                        f"status_{student.id}"
                    )
                    if status not in valid_statuses:
                        messages.error(
                            request,
                            "Every student must have a valid "
                            "attendance status.",
                        )
                        break
                    statuses[student.id] = status
                else:
                    try:
                        with transaction.atomic():
                            # Serialize roll calls even when no attendance rows exist yet.
                            school_queryset(ClassStream, context).select_for_update().get(pk=selected_class.pk)
                            if school_queryset(DailyClassAttendance, context).filter(
                                current_class=selected_class, date=current_date,
                            ).exists():
                                raise ValidationError("Attendance is already locked for today.")
                            for student in students:
                                record = DailyClassAttendance(
                                    school=context.school,
                                    student=student,
                                    current_class=selected_class,
                                    status=statuses[student.id],
                                    submitted_by=request.user,
                                    is_locked=True,
                                )
                                record.save()
                    except ValidationError:
                        messages.error(
                            request,
                            "Attendance could not be saved. "
                            "Please verify the student records.",
                        )
                    else:
                        messages.success(
                            request,
                            f"Attendance for "
                            f"{selected_class.name} "
                            "submitted and locked successfully!",
                        )
                        return redirect(
                            "take_daily_attendance_class",
                            class_id=selected_class.pk,
                        )

    if request.method == "POST" and selected_class is None:
        from django.http import HttpResponseBadRequest
        return HttpResponseBadRequest("Select an assigned class first.")

    return render(
        request,
        "core/take_daily_attendance.html",
        {
            "classes": classes,
            "selected_class": selected_class,
            "students": students,
            "already_submitted": already_submitted,
            "attendance_by_student": attendance_by_student,
            "today": current_date,
        },
    )



@login_required
def teacher_homework_view(request, assignment_id, homework_id=None):
    from core.teacher_forms import HomeworkForm
    assignment = teacher_assignment_for_user(request, assignment_id)
    homework = None
    if homework_id is not None:
        homework = get_object_or_404(
            Homework, pk=homework_id, school=assignment.school, assignment=assignment,
        )
    if homework is None:
        homework = Homework(school=assignment.school, assignment=assignment)
    editing = homework if homework.pk else None
    form = HomeworkForm(request.POST if request.method == "POST" else None, request.FILES or None, instance=homework)
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.school = assignment.school
        record.assignment = assignment
        record.save()
        messages.success(request, "Homework saved successfully.")
        return redirect("teacher_homework", assignment_id=assignment.pk)
    return render(request, "core/teacher_homework.html", {
        "assignment": assignment, "form": form, "editing": editing,
        "homeworks": Homework.objects.filter(school=assignment.school, assignment=assignment).order_by("-created_at"),
    })


@login_required
@require_POST
def teacher_homework_delete(request, assignment_id, homework_id):
    assignment = teacher_assignment_for_user(request, assignment_id)
    homework = get_object_or_404(Homework, pk=homework_id, school=assignment.school, assignment=assignment)
    homework.delete()
    messages.success(request, "Homework deleted.")
    return redirect("teacher_homework", assignment_id=assignment.pk)


@login_required
def teacher_homework_download(request, assignment_id, homework_id):
    from django.http import FileResponse
    from pathlib import Path
    assignment = teacher_assignment_for_user(request, assignment_id)
    homework = get_object_or_404(Homework, pk=homework_id, school=assignment.school, assignment=assignment)
    if not homework.file:
        raise Http404("No attachment.")
    try:
        response = FileResponse(homework.file.open("rb"), as_attachment=True,
                                filename=Path(homework.file.name).name)
    except FileNotFoundError:
        raise Http404("Attachment is unavailable.")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def student_dashboard(request):
    from core import student_portal as portal
    context = portal.student_context(request, selected=False)
    subject_attendance, daily = portal.personal_attendance(context)
    data = portal.page_context(context)
    data.update(grades_list=portal.grades(context), subjects=portal.curriculum(context),
                recent_homeworks=portal.homework(context)[:5], recent_notices=portal.notices(context)[:5],
                homework_count=portal.homework(context).count(), subject_count=portal.curriculum(context).count(),
                attendance_count=subject_attendance.count(), daily_count=daily.count())
    return render(request, "core/student_dashboard.html", data)


@login_required
@require_GET
def student_subjects(request):
    from core import student_portal as portal
    context = portal.student_context(request)
    data = portal.page_context(context)
    data.update(subjects=portal.curriculum(context), assignments=portal.assignments(context))
    return render(request, "core/student_subjects.html", data)


@login_required
@require_GET
def student_homework_view(request):
    from core import student_portal as portal
    context = portal.student_context(request)
    data = portal.page_context(context)
    data.update(homework_list=portal.homework(context))
    return render(request, "core/student_homework.html", data)


@login_required
@require_GET
def student_homework_download(request, homework_id):
    from core import student_portal as portal
    from django.http import FileResponse
    from pathlib import Path
    context = portal.student_context(request)
    record = get_object_or_404(portal.homework(context), pk=homework_id)
    if not record.file:
        raise Http404("No attachment.")
    try:
        response = FileResponse(record.file.open("rb"), as_attachment=True,
                                filename=Path(record.file.name).name)
    except FileNotFoundError:
        raise Http404("Attachment is unavailable.")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def student_grades(request):
    from core import student_portal as portal
    context = portal.student_context(request)
    data = portal.page_context(context)
    data.update(grades_list=portal.grades(context))
    return render(request, "core/student_grades.html", data)


@login_required
@require_GET
def student_attendance_view(request):
    from core import student_portal as portal
    context = portal.student_context(request)
    subject, daily = portal.personal_attendance(context)
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        if not 1 <= year <= 9999 or not 1 <= month <= 12:
            raise ValueError
    except (ValueError, TypeError):
        raise Http404("Invalid attendance month.")
    data = portal.page_context(context)
    data.update(subject_attendance=subject.filter(date__year=year, date__month=month),
                daily_attendance=daily.filter(date__year=year, date__month=month),
                current_year=year, current_month=month)
    return render(request, "core/student_attendance.html", data)


@login_required
@require_GET
def student_notices(request):
    from core import student_portal as portal
    context = portal.student_context(request, selected=False)
    data = portal.page_context(context)
    data.update(notices=portal.notices(context))
    return render(request, "core/student_notices.html", data)


@login_required
@require_GET
def student_schedule(request):
    # The existing schema has subject allocations, but no day/time/room fields.
    from core import student_portal as portal
    context = portal.student_context(request)
    data = portal.page_context(context)
    data.update(assignments=portal.assignments(context))
    return render(request, "core/student_schedule.html", data)


@login_required
@require_GET
def student_profile_view(request):
    from core import student_portal as portal
    context = portal.student_context(request, selected=False)
    return render(request, "core/student_profile.html", portal.page_context(context))


@login_required
def student_password_change(request):
    from core import student_portal as portal
    from django.contrib.auth.forms import PasswordChangeForm
    from django.contrib.auth import update_session_auth_hash
    context = portal.student_context(request, selected=False)
    form = PasswordChangeForm(request.user, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Your password has been changed.")
        return redirect("student_dashboard")
    data = portal.page_context(context)
    data["form"] = form
    return render(request, "core/student_change_password.html", data)


from django.template.loader import get_template
from xhtml2pdf import pisa


def get_student_report_data(student, school, academic_year_id, term_id):
    """
    Retrieve tenant-scoped academic records for one student's term report.

    This helper does not generate a PDF or modify database records.
    """
    from core.models import AcademicYear, Term, StudentEnrollment, Grade, Attendance
    from django.http import Http404

    academic_year = get_object_or_404(
        AcademicYear,
        pk=academic_year_id,
        school=school,
    )

    term = get_object_or_404(
        Term,
        pk=term_id,
        school=school,
        academic_year=academic_year,
    )

    enrollment = get_object_or_404(
        StudentEnrollment.objects.select_related("class_stream"),
        school=school,
        student=student,
        student__school=school,
        class_stream__school=school,
        academic_year=academic_year,
        term=term,
        status__in=["Active", "Completed"],
    )

    grades = (
        Grade.objects.filter(
            school=school,
            student=student,
            term=term,
            subject__school=school,
            status="Finalized",
        )
        .select_related("subject")
        .order_by("subject__name")
    )

    attendance = Attendance.objects.filter(
        school=school,
        student=student,
        assignment__school=school,
        assignment__term=term,
        assignment__current_class=enrollment.class_stream,
        assignment__current_class__school=school,
        assignment__subject__school=school,
    )

    return {
        "school": school,
        "academic_year": academic_year,
        "term": term,
        "enrollment": enrollment,
        "grades": grades,
        "attendance": attendance,
    }


def student_report_context(request):
    """Reuse the existing curriculum/completeness and cumulative report rules."""
    from core import student_portal as portal
    from core.models import AcademicYear, Term, StudentEnrollment, Grade, Attendance, ClassSubject
    from decimal import Decimal, ROUND_HALF_UP
    from django.http import Http404
    from django.utils import timezone

    resolved = portal.student_context(request, selected=False)
    school = resolved.school
    student = resolved.student
    if "term_id" in request.GET:
        raise Http404("Use the reporting term selector.")

    term_param = request.GET.get("term", resolved.term.name[-1])
    scope = request.GET.get("scope", "term")

    if term_param not in ("1", "2", "3"):
        raise Http404("Invalid reporting term.")

    if scope not in ("term", "annual"):
        raise Http404("Invalid report scope.")

    if scope == "annual" or term_param == "3":
        term_numbers = (1, 2, 3)
        report_title = "Annual Academic & Attendance Report"
        current_term_label = "Term 1, 2 & 3 (Annual)"
        report_scope = "annual"
    elif term_param == "2":
        term_numbers = (1, 2)
        report_title = "Cumulative Term 2 Report"
        current_term_label = "Term 1 & 2 (Cumulative)"
        report_scope = "cumulative"
    else:
        term_numbers = (1,)
        report_title = "Term 1 Academic & Attendance Report"
        current_term_label = "Term 1"
        report_scope = "term"

    academic_year = resolved.enrollment.academic_year
    if request.GET.get("academic_year", str(academic_year.pk)) != str(academic_year.pk):
        raise Http404("Reporting year not found.")

    selected_terms = list(
        Term.objects.filter(
            school=school,
            academic_year=academic_year,
            name__in=[
                f"Term {number}" for number in term_numbers
            ],
        ).order_by("name")
    )

    term_by_number = {
        int(term.name[-1]): term
        for term in selected_terms
    }

    if len(term_by_number) != len(term_numbers):
        raise Http404("Required reporting terms are not configured.")

    report_data = [
        get_student_report_data(
            student,
            school,
            academic_year.pk,
            term_by_number[number].pk,
        )
        for number in term_numbers
    ]

    all_grades = []
    attendance_querysets = []

    for data in report_data:
        all_grades.extend(list(data["grades"]))
        attendance_querysets.append(data["attendance"])

    subject_summary = {}

    # Build expected subjects from the school's official curriculum.
    # The student's enrollment determines the class for each term.
    # Required subjects must have grades; optional subjects do not.
    for number, data in zip(term_numbers, report_data):
        curriculum_assignments = (
            ClassSubject.objects.filter(
                school=school,
                academic_year=academic_year,
                class_stream=data["enrollment"].class_stream,
                subject__school=school,
            )
            .select_related("subject")
        )

        for assignment in curriculum_assignments:
            subject_summary.setdefault(
                assignment.subject_id,
                {
                    "subject": assignment.subject,
                    "terms": {},
                    "required_terms": set(),
                    "optional_terms": set(),
                },
            )

            if assignment.is_required:
                subject_summary[assignment.subject_id][
                    "required_terms"
                ].add(number)
            else:
                subject_summary[assignment.subject_id][
                    "optional_terms"
                ].add(number)

    for grade in all_grades:
        number = int(grade.term.name[-1])
        key = grade.subject_id

        if key not in subject_summary:
            subject_summary[key] = {
                "subject": grade.subject,
                "terms": {},
                "required_terms": set(),
                "optional_terms": set(),
            }

        subject_summary[key]["terms"][number] = {
            "grade_obj": grade,
            "cat_marks": grade.cat_marks,
            "max_cat": grade.subject.max_cat_marks,
            "exam_marks": grade.exam_marks,
            "max_exam": grade.subject.max_exam_marks,
            "marks_obtained": grade.marks_obtained,
            "max_marks": grade.max_marks,
            "percentage": grade.percentage,
        }

    def letter_for(percentage):
        if percentage >= 80:
            return "A", "Excellent"
        if percentage >= 70:
            return "B", "Very Good"
        if percentage >= 60:
            return "C", "Good"
        if percentage >= 50:
            return "D", "Satisfactory"
        return "F", "Fail"

    table_rows = []
    completed_percentages = []
    blocking_incomplete = False

    for item in sorted(
        subject_summary.values(),
        key=lambda entry: entry["subject"].name.lower(),
    ):
        required_terms = item["required_terms"]
        optional_terms = item["optional_terms"]
        configured_terms = required_terms | optional_terms

        percentages = [
            item["terms"][number]["percentage"]
            for number in term_numbers
            if number in configured_terms
            and number in item["terms"]
            and item["terms"][number]["percentage"] is not None
        ]

        missing_required = any(
            number not in item["terms"]
            or item["terms"][number]["percentage"] is None
            for number in required_terms
        )

        unconfigured_grade = any(
            number not in configured_terms
            for number in item["terms"]
        )

        if unconfigured_grade:
            complete = False
            blocking_incomplete = True
            final_pct = None
            letter = "?"
            remarks = "Subject not configured in curriculum"

        elif missing_required:
            complete = False
            blocking_incomplete = True
            final_pct = None
            letter = "?"
            remarks = "Incomplete required results"

        elif percentages:
            complete = True
            final_pct = (
                sum(percentages, Decimal("0.00"))
                / Decimal(len(percentages))
            ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

            letter, remarks = letter_for(final_pct)
            completed_percentages.append(final_pct)

        else:
            complete = True
            final_pct = None
            letter = "-"
            remarks = "Optional - not assessed"

        table_rows.append({
            "subject_name": item["subject"].name,
            "terms": item["terms"],
            "final_percentage": final_pct,
            "grade_letter": letter,
            "remarks": remarks,
            "is_complete": complete,
        })

    all_subjects_complete = (
        bool(table_rows)
        and not blocking_incomplete
        and bool(completed_percentages)
    )

    if all_subjects_complete:
        average_percentage = (
            sum(completed_percentages, Decimal("0.00"))
            / Decimal(len(completed_percentages))
        ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

        avg_grade_letter = letter_for(average_percentage)[0]
    else:
        average_percentage = None
        avg_grade_letter = "?"

    from functools import reduce
    from operator import or_
    attendance_records = reduce(or_, attendance_querysets)

    total_records = attendance_records.count()
    present_count = attendance_records.filter(
        status="Present"
    ).count()
    late_count = attendance_records.filter(
        status="Late"
    ).count()
    absent_count = attendance_records.filter(
        status="Absent"
    ).count()

    attendance_percentage = (
        round(
            (present_count + late_count) * 100 / total_records,
            1,
        )
        if total_records
        else None
    )

    context = {
        "school": school,
        "academic_year": academic_year,
        "student_profile": student,
        "student_enrollment": report_data[-1]["enrollment"],
        "attendance_records": attendance_records,
        "grades": all_grades,
        "table_rows": table_rows,
        "average_percentage": average_percentage,
        "avg_grade_letter": avg_grade_letter,
        "attendance_percentage": attendance_percentage,
        "present_count": present_count,
        "late_count": late_count,
        "absent_count": absent_count,
        "total_records": total_records,
        "current_term": current_term_label,
        "report_title": report_title,
        "report_scope": report_scope,
        "term_param": term_param,
        "date_range": str(academic_year.name),
        "issue_date": timezone.localdate().strftime("%B %d, %Y"),
        "report_complete": all_subjects_complete,
        "attendance_unit": "class attendance records",
    }

    return context


@login_required
@require_GET
def generate_student_report_card(request):
    context = student_report_context(request)
    student = context["student_profile"]
    academic_year = context["academic_year"]
    term_param = context["term_param"]
    template = get_template("core/report_card_pdf.html")
    html = template.render(context)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="Report_Card_{student.pk}_'
        f'{academic_year.pk}_Term{term_param}.pdf"'
    )

    pisa_status = pisa.CreatePDF(html, dest=response)

    if pisa_status.err:
        return HttpResponse(
            "Error generating PDF report",
            status=400,
        )

    response["Cache-Control"] = "private, no-store"
    return response

@login_required
def teacher_schedule_view(request):
    if not is_teacher(request.user):
        messages.error(request, "Access denied.")
        return redirect('/login/')

    current_term = Term.objects.filter(is_current=True).first()
    assignments = TeacherAssignment.objects.filter(teacher=request.user)
    if current_term:
        assignments = assignments.filter(term=current_term)

    context = {
        'assignments': assignments,
        'current_term': current_term,
    }
    return render(request, 'core/teacher_schedule.html', context)


@login_required
def teacher_notices_view(request):
    if not is_teacher(request.user):
        messages.error(request, "Access denied.")
        return redirect('/login/')

    today = timezone.now().date()
    # Fetch general notices or notices targeted for staff/teachers
    notices = Notice.objects.filter(
        Q(expires_at__gte=today) | Q(expires_at__isnull=True)
    ).order_by('-created_at')

    context = {
        'notices': notices,
    }
    return render(request, 'core/teacher_notices.html', context)
@login_required
def teacher_grades_list_view(request):
    if not is_teacher(request.user):
        messages.error(request, "Access denied.")
        return redirect('/login/')

    current_term = Term.objects.filter(is_current=True).first()
    assignments = TeacherAssignment.objects.filter(teacher=request.user)
    if current_term:
        assignments = assignments.filter(term=current_term)

    return render(request, 'core/teacher_grades_list.html', {'assignments': assignments, 'current_term': current_term})


@login_required
def teacher_homework_list_view(request):
    if not is_teacher(request.user):
        messages.error(request, "Access denied.")
        return redirect('/login/')

    current_term = Term.objects.filter(is_current=True).first()
    assignments = TeacherAssignment.objects.filter(teacher=request.user)
    if current_term:
        assignments = assignments.filter(term=current_term)

    return render(request, 'core/teacher_homework_list.html', {'assignments': assignments, 'current_term': current_term})
@login_required
def teacher_enter_grades_view(request, assignment_id):
    """Compatibility wrapper for the secured grade-entry workflow."""
    return input_grades_view(request, assignment_id)




@login_required
def teacher_homework_manage_view(request, assignment_id):
    return teacher_homework_view(request, assignment_id)


class StudentPasswordChangeView(PasswordChangeView):
  template_name = (
      'core/change_password.html'  # We will create this template in a later step
  )
  success_url = reverse_lazy(
      'student_dashboard'
  )  # Where they go after a successful change
  from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse_lazy


class TeacherPasswordChangeView(PasswordChangeView):
  template_name = 'core/change_password.html'
  success_url = reverse_lazy('teacher_dashboard')
  from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render

def is_accountant_or_admin(user):
    return is_accountant(user) or is_admin(user)


from decimal import Decimal

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum
from django.shortcuts import render

from .models import (
    FeeStructure,
    Payment,
    StudentFee,
    StudentProfile,
    Term,
)


def is_accountant_or_admin(user):
    """
    Allow access to:
    - Superusers
    - Administrators
    - Accountants
    - Bursars
    - Users belonging to the Accountant Django group
    """

    if not user.is_authenticated:
        return False

    # Superuser always has access
    if user.is_superuser:
        return True

    # Try the project's UserProfile relationship.
    # Your SMS has been using `user.profile`.
    profile = getattr(user, "profile", None)

    if profile is not None:
        role = str(getattr(profile, "role", "")).strip().lower()

        if role in {
            "accountant",
            "administrator",
            "admin",
            "bursar",
        }:
            return True

    # Fallback: allow Accountant Django group
    if user.groups.filter(name__iexact="Accountant").exists():
        return True

    return False


from decimal import Decimal
from django.utils import timezone
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum
from django.shortcuts import render
from .models import StudentProfile, Term, StudentFee, FeeStructure, Payment


@login_required
def accountant_dashboard(request):
    """
    Tenant-safe accountant dashboard.

    Financial figures are limited to the authenticated user's
    approved school and its current academic term.
    """
    from decimal import Decimal

    from django.db.models import Sum
    from django.shortcuts import render
    from django.utils import timezone

    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    from .models import (
        AcademicYear,
        Term,
        StudentProfile,
        StudentFee,
        Payment,
    )

    # 1. Resolve the user's approved school membership.
    school_context = require_school_context(request.user)

    # 2. Only school administrators and accountants may access
    #    the financial dashboard.
    require_school_role(
        school_context,
        "administrator",
        "accountant",
    )

    school = school_context.school
    zero = Decimal("0.00")

    # 3. Scope every queryset to the authorized school.
    students = school_queryset(
        StudentProfile,
        school_context,
    )

    student_fees = school_queryset(
        StudentFee,
        school_context,
    )

    payments = school_queryset(
        Payment,
        school_context,
    )

    total_students = students.count()

    # 4. Resolve the current academic year and term
    #    within this school only.
    current_year = (
        school_queryset(AcademicYear, school_context)
        .filter(is_current=True)
        .first()
    )

    current_term = None

    if current_year is not None:
        current_term = (
            school_queryset(Term, school_context)
            .filter(
                academic_year=current_year,
                is_current=True,
            )
            .first()
        )

    # 5. Initialize safe empty-state financial values.
    total_expected = zero
    total_collected = zero
    outstanding_balance = zero
    total_overpaid = zero
    today_collections = zero
    today_transactions = 0

    recent_payments = payments.none()

    finance_ready = current_term is not None

    finance_message = (
        "Financial records are available for the current term."
        if finance_ready
        else (
            "Financial setup is incomplete. "
            "Configure a current academic year and term "
            "before viewing current-term totals."
        )
    )

    if current_term is not None:

        # 6. Restrict financial records to the SAME school,
        #    academic year, and term.
        period_fees = student_fees.filter(
            academic_year=current_year,
            term=current_term,
            student__school=school,
            academic_year__school=school,
            term__school=school,
        )

        period_payments = payments.filter(
            academic_year=current_year,
            term=current_term,
            student__school=school,
            academic_year__school=school,
            term__school=school,
            is_voided=False,
        )

        # 7. Expected fees come from student obligations.
        #    FeeStructure templates are deliberately not
        #    counted as actual student debt.
        total_expected = (
            period_fees.aggregate(
                total=Sum("total_expected")
            )["total"]
            or zero
        )

        # 8. Exclude voided payments from collected revenue.
        total_collected = (
            period_payments.aggregate(
                total=Sum("amount_paid")
            )["total"]
            or zero
        )

        # 9. Calculate outstanding and overpaid amounts
        #    per student, avoiding cross-student offsets.
        expected_by_student = dict(
            period_fees.values("student_id")
            .annotate(total=Sum("total_expected"))
            .values_list("student_id", "total")
        )

        paid_by_student = dict(
            period_payments.values("student_id")
            .annotate(total=Sum("amount_paid"))
            .values_list("student_id", "total")
        )

        student_ids = (
            set(expected_by_student)
            | set(paid_by_student)
        )

        for student_id in student_ids:
            expected = expected_by_student.get(
                student_id, zero
            ) or zero

            paid = paid_by_student.get(
                student_id, zero
            ) or zero

            difference = expected - paid

            if difference > zero:
                outstanding_balance += difference
            elif difference < zero:
                total_overpaid += -difference

        # 10. Today's collections for this school and term.
        today = timezone.localdate()

        today_payments = period_payments.filter(
            date_paid__date=today
        )

        today_collections = (
            today_payments.aggregate(
                total=Sum("amount_paid")
            )["total"]
            or zero
        )

        today_transactions = today_payments.count()

        # 11. Recent non-voided transactions.
        recent_payments = (
            period_payments
            .select_related("student", "received_by")
            .order_by("-date_paid", "-id")[:5]
        )

    # 12. Preserve the template's existing context keys.
    context = {
        "school": school,
        "total_expected": total_expected,
        "total_collected": total_collected,
        "outstanding_balance": outstanding_balance,
        "total_overpaid": total_overpaid,
        "today_collections": today_collections,
        "today_transactions": today_transactions,
        "total_students": total_students,
        "current_term": current_term,
        "recent_payments": recent_payments,
        "finance_ready": finance_ready,
        "finance_message": finance_message,
    }

    return render(
        request,
        "core/accountant_dashboard.html",
        context,
    )

from django import forms
from django.contrib import messages
from django.shortcuts import redirect


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = [
            "student",
            "academic_year",
            "term",
            "amount_paid",
            "payment_method",
            "reference_number",
            "notes",
        ]
        widgets = {
            "student": forms.Select(attrs={
                "class": "w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            }),
            "academic_year": forms.Select(attrs={
                "class": "w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            }),
            "term": forms.Select(attrs={
                "class": "w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            }),
            "amount_paid": forms.NumberInput(attrs={
                "class": "w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500",
                "placeholder": "Enter amount in RWF"
            }),
            "payment_method": forms.Select(attrs={
                "class": "w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            }),
            "reference_number": forms.TextInput(attrs={
                "class": "w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500",
                "placeholder": "Optional (e.g., Bank Slip, MoMo code)"
            }),
            "notes": forms.Textarea(attrs={
                "class": "w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500",
                "rows": 3,
                "placeholder": "Optional remarks..."
            }),
        }

    def __init__(self, *args, school_context=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Assign the authorized school before validation.
        if school_context is not None:
            self.instance.school = school_context.school

        from core.models import StudentProfile, AcademicYear, Term
        from tenants.access import school_queryset

        self.fields["student"].queryset = StudentProfile.objects.none()
        self.fields["academic_year"].queryset = AcademicYear.objects.none()
        self.fields["term"].queryset = Term.objects.none()

        if school_context is None:
            return

        self.fields["student"].queryset = school_queryset(
            StudentProfile,
            school_context,
        )

        self.fields["academic_year"].queryset = school_queryset(
            AcademicYear,
            school_context,
        )

        self.fields["term"].queryset = school_queryset(
            Term,
            school_context,
        ).filter(
            academic_year__school=school_context.school,
        )

    def clean(self):
        cleaned_data = super().clean()

        from decimal import Decimal
        from django.db.models import Sum
        from core.models import StudentFee, Payment

        student = cleaned_data.get("student")
        academic_year = cleaned_data.get("academic_year")
        term = cleaned_data.get("term")
        amount = cleaned_data.get("amount_paid")
        school = self.instance.school

        if academic_year and term:
            if term.academic_year_id != academic_year.pk:
                self.add_error(
                    "term",
                    "The selected term does not belong to "
                    "the selected academic year.",
                )
                return cleaned_data

        if not all((
            school, student, academic_year, term
        )):
            return cleaned_data

        bill = StudentFee.objects.filter(
            school=school,
            student=student,
            academic_year=academic_year,
            term=term,
        ).first()

        if bill is None:
            self.add_error(
                "student",
                "This student has no generated fee bill "
                "for the selected term.",
            )
            return cleaned_data

        paid = Payment.objects.filter(
            school=school,
            student=student,
            academic_year=academic_year,
            term=term,
            is_voided=False,
        )

        if self.instance.pk:
            paid = paid.exclude(pk=self.instance.pk)

        total_paid = (
            paid.aggregate(total=Sum("amount_paid"))["total"]
            or Decimal("0.00")
        )

        balance = bill.total_expected - total_paid

        if amount is not None and amount <= 0:
            self.add_error(
                "amount_paid",
                "Payment must be greater than zero.",
            )
        elif amount is not None and amount > balance:
            self.add_error(
                "amount_paid",
                f"Payment exceeds the outstanding balance "
                f"of {balance} RWF.",
            )

        return cleaned_data

from django.db import transaction


@login_required
def record_payment(request):
    """
    Record a payment for the authenticated user's school only.
    """
    from django.contrib import messages
    from django.db import transaction
    from django.shortcuts import render, redirect

    from tenants.access import (
        require_school_context,
        require_school_role,
    )

    # Resolve the approved school from the user's membership.
    school_context = require_school_context(request.user)

    # Only administrators and accountants can record payments.
    require_school_role(
        school_context,
        "administrator",
        "accountant",
    )

    if request.method == "POST":
        form = PaymentForm(
            request.POST,
            school_context=school_context,
        )

        if form.is_valid():
            try:
                with transaction.atomic():
                    from decimal import Decimal
                    from django.db.models import Sum
                    from django.core.exceptions import ValidationError
                    from core.models import StudentFee, Payment

                    payment = form.save(commit=False)

                    # Never trust a school ID from POST data.
                    payment.school = school_context.school
                    payment.received_by = request.user

                    # Lock the specific student's bill until commit.
                    bill = (
                        StudentFee.objects.select_for_update()
                        .get(
                            school=school_context.school,
                            student=payment.student,
                            academic_year=payment.academic_year,
                            term=payment.term,
                        )
                    )

                    # Recalculate while holding the bill lock.
                    already_paid = (
                        Payment.objects.filter(
                            school=school_context.school,
                            student=payment.student,
                            academic_year=payment.academic_year,
                            term=payment.term,
                            is_voided=False,
                        )
                        .aggregate(total=Sum("amount_paid"))["total"]
                        or Decimal("0.00")
                    )

                    remaining = bill.total_expected - already_paid

                    if (
                        payment.amount_paid <= 0
                        or payment.amount_paid > remaining
                    ):
                        raise ValidationError(
                            "Payment exceeds the available balance "
                            "or has an invalid amount."
                        )

                    # Save only after the locked balance check.
                    payment.save()

                messages.success(
                    request,
                    (
                        f"Successfully recorded payment of "
                        f"{payment.amount_paid} RWF for "
                        f"{payment.student}."
                    ),
                )

                return redirect(
                    "payment_receipt",
                    payment_id=payment.pk,
                )

            except Exception:
                # Do not expose internal database errors to users.
                messages.error(
                    request,
                    "Unable to record this payment. "
                    "Please verify the details and try again.",
                )

    else:
        form = PaymentForm(
            school_context=school_context,
        )

    return render(
        request,
        "core/record_payment.html",
        {
            "form": form,
            "school": school_context.school,
        },
    )

from decimal import Decimal
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum
from django.shortcuts import render
from .models import StudentEnrollment, Payment, StudentFee, FeeStructure, Term

@login_required
def debtors_list(request):
    """
    Show outstanding student balances for the authorized school's
    current academic year and term.
    """
    from decimal import Decimal

    from django.db.models import Sum
    from django.shortcuts import render

    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    from .models import (
        AcademicYear,
        Term,
        StudentEnrollment,
        StudentFee,
        FeeStructure,
        Payment,
    )

    school_context = require_school_context(request.user)

    require_school_role(
        school_context,
        "administrator",
        "accountant",
    )

    school = school_context.school
    zero = Decimal("0.00")

    current_year = (
        school_queryset(AcademicYear, school_context)
        .filter(is_current=True)
        .first()
    )

    current_term = None

    if current_year is not None:
        current_term = (
            school_queryset(Term, school_context)
            .filter(
                academic_year=current_year,
                is_current=True,
            )
            .first()
        )

    debtors_data = []

    if current_term is not None:
        enrollments = (
            school_queryset(StudentEnrollment, school_context)
            .filter(
                academic_year=current_year,
                term=current_term,
                student__school=school,
                class_stream__school=school,
                academic_year__school=school,
                term__school=school,
            )
            .select_related(
                "student",
                "class_stream",
                "academic_year",
                "term",
            )
            .order_by("student_id", "-date_enrolled", "-pk")
        )

        # Use one enrollment per student for the current term.
        seen_students = set()

        for enrollment in enrollments:
            student = enrollment.student

            if student.pk in seen_students:
                continue

            seen_students.add(student.pk)

            expected_sum = (
                school_queryset(StudentFee, school_context)
                .filter(
                    student=student,
                    academic_year=current_year,
                    term=current_term,
                    student__school=school,
                    academic_year__school=school,
                    term__school=school,
                )
                .aggregate(total=Sum("total_expected"))["total"]
            )

            if expected_sum is None:
                expected_sum = (
                    school_queryset(FeeStructure, school_context)
                    .filter(
                        class_stream=enrollment.class_stream,
                        academic_year=current_year,
                        term=current_term,
                        class_stream__school=school,
                        academic_year__school=school,
                        term__school=school,
                    )
                    .aggregate(total=Sum("amount"))["total"]
                )

            expected = expected_sum if expected_sum is not None else zero

            paid_sum = (
                school_queryset(Payment, school_context)
                .filter(
                    student=student,
                    academic_year=current_year,
                    term=current_term,
                    student__school=school,
                    academic_year__school=school,
                    term__school=school,
                    is_voided=False,
                )
                .aggregate(total=Sum("amount_paid"))["total"]
            )

            paid = paid_sum if paid_sum is not None else zero
            balance = expected - paid

            if balance > zero:
                debtors_data.append({
                    "student": student,
                    "class": enrollment.class_stream,
                    "expected": expected,
                    "paid": paid,
                    "balance": balance,
                })

    context = {
        "debtors": debtors_data,
        "current_term": current_term,
        "school": school,
        "finance_ready": current_term is not None,
    }

    return render(
        request,
        "core/debtors_list.html",
        context,
    )
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test, permission_required
from django.contrib import messages
from django.utils import timezone
from .models import Payment, StudentEnrollment

@login_required
def payment_receipt(request, payment_id):
    """
    Display a payment receipt only to an authorized
    administrator or accountant of the payment's school.
    """
    from django.shortcuts import get_object_or_404, render

    from core.models import Payment, StudentEnrollment

    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    # Resolve the authenticated user's approved school.
    school_context = require_school_context(request.user)

    # Students and teachers cannot access accountant receipts.
    require_school_role(
        school_context,
        "administrator",
        "accountant",
    )

    # Never retrieve payments across school boundaries.
    payment = get_object_or_404(
        school_queryset(Payment, school_context).select_related(
            "student",
            "academic_year",
            "term",
            "received_by",
        ),
        pk=payment_id,
    )

    # Find the student's class only within the same school,
    # academic year and term.
    enrollment = (
        school_queryset(StudentEnrollment, school_context)
        .filter(
            student=payment.student,
            academic_year=payment.academic_year,
            term=payment.term,
            class_stream__school=school_context.school,
        )
        .select_related("class_stream")
        .first()
    )

    class_name = (
        enrollment.class_stream.name
        if enrollment and enrollment.class_stream
        else "N/A"
    )

    context = {
        "payment": payment,
        "class_name": class_name,
        "school": school_context.school,
    }

    return render(
        request,
        "core/payment_receipt.html",
        context,
    )


@login_required
def void_payment_view(request, payment_id):
    """
    Securely void a payment within the authenticated user's school.

    Only school administrators and accountants may void payments.
    The original payment is retained with its audit information.
    """
    from django.contrib import messages
    from django.db import transaction
    from django.shortcuts import get_object_or_404, redirect, render
    from django.utils import timezone

    from core.models import Payment
    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    school_context = require_school_context(request.user)

    require_school_role(
        school_context,
        "administrator",
        "accountant",
    )

    payments = school_queryset(Payment, school_context)

    # Reject payment IDs belonging to other schools.
    payment = get_object_or_404(payments, pk=payment_id)

    if request.method == "GET":
        return render(
            request,
            "core/void_payment_confirm.html",
            {
                "payment": payment,
                "school": school_context.school,
            },
        )

    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["GET", "POST"])

    reason = request.POST.get("void_reason", "").strip()

    if not reason:
        messages.error(
            request,
            "A reason is required to void a payment.",
        )
        return redirect("school_home")

    with transaction.atomic():
        # Lock the record to prevent simultaneous void operations.
        payment = get_object_or_404(
            school_queryset(Payment, school_context)
            .select_for_update(),
            pk=payment_id,
        )

        if payment.is_voided:
            messages.error(
                request,
                "This payment has already been voided.",
            )
            return redirect("school_home")

        payment.is_voided = True
        payment.void_reason = reason
        payment.voided_at = timezone.now()
        payment.voided_by = request.user

        # Payment.save() performs model-level validation.
        payment.save()

    messages.success(
        request,
        f"Payment {payment.receipt_number} was successfully voided.",
    )

    return redirect("school_home")
from decimal import Decimal
from django.db.models import Sum
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import StudentProfile, StudentEnrollment, StudentFee, FeeStructure, Payment, Term


@login_required
def student_financial_profile(request, student_id):
    """
    Display a student's financial profile within the authorized school.

    Only active school administrators and accountants may access it.
    All student, enrollment, term, fee, and payment queries are
    restricted to the authenticated user's school.
    """
    from decimal import Decimal

    from django.db.models import Sum
    from django.shortcuts import get_object_or_404, render

    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    from .models import (
        StudentProfile,
        StudentEnrollment,
        StudentFee,
        FeeStructure,
        Payment,
        Term,
    )

    # 1. Identify the authorized school.
    school_context = require_school_context(request.user)

    # 2. Restrict access to financial staff and administrators.
    require_school_role(
        school_context,
        "administrator",
        "accountant",
    )

    # 3. Retrieve the student ONLY from this school.
    # Another school's student ID will return HTTP 404.
    student = get_object_or_404(
        school_queryset(StudentProfile, school_context),
        pk=student_id,
    )

    # 4. Retrieve the school's current term.
    current_term = (
        school_queryset(Term, school_context)
        .filter(
            is_current=True,
            academic_year__school=school_context.school,
        )
        .first()
    )

    # 5. Retrieve the student's latest enrollment at this school.
    enrollment = (
        school_queryset(StudentEnrollment, school_context)
        .filter(
            student=student,
            academic_year__school=school_context.school,
            term__school=school_context.school,
            class_stream__school=school_context.school,
        )
        .select_related(
            "class_stream",
            "academic_year",
            "term",
        )
        .order_by("-date_enrolled", "-pk")
        .first()
    )

    # Preserve the original behavior:
    # Prefer the latest enrollment's term, otherwise current term.
    term_to_use = enrollment.term if enrollment else current_term

    # 6. Calculate expected fees.
    expected_sum = None

    if term_to_use:
        expected_sum = (
            school_queryset(StudentFee, school_context)
            .filter(
                student=student,
                term=term_to_use,
                academic_year__school=school_context.school,
            )
            .aggregate(total=Sum("total_expected"))["total"]
        )

        # Preserve the original fee-structure fallback.
        if (
            expected_sum is None
            and enrollment
            and enrollment.class_stream_id
        ):
            expected_sum = (
                school_queryset(FeeStructure, school_context)
                .filter(
                    class_stream=enrollment.class_stream,
                    term=term_to_use,
                    academic_year__school=school_context.school,
                )
                .aggregate(total=Sum("amount"))["total"]
            )

    expected = Decimal(str(expected_sum or "0.00"))

    # 7. Retrieve ONLY this school's payment records.
    # Include voided payments in the audit ledger.
    payments = (
        school_queryset(Payment, school_context)
        .filter(
            student=student,
            academic_year__school=school_context.school,
            term__school=school_context.school,
        )
        .select_related(
            "academic_year",
            "term",
            "received_by",
            "voided_by",
        )
        .order_by("-date_paid")
    )

    # 8. Exclude voided payments from the paid amount.
    valid_payments = payments.filter(is_voided=False)

    if term_to_use:
        paid_sum = (
            valid_payments
            .filter(term=term_to_use)
            .aggregate(total=Sum("amount_paid"))["total"]
        )
    else:
        paid_sum = (
            valid_payments
            .aggregate(total=Sum("amount_paid"))["total"]
        )

    paid = Decimal(str(paid_sum or "0.00"))

    # 9. Calculate outstanding balance.
    balance = expected - paid

    # 10. Render the financial profile.
    context = {
        "student": student,
        "enrollment": enrollment,
        "term": term_to_use,
        "expected": expected,
        "paid": paid,
        "balance": balance,
        "payments": payments,
        "school": school_context.school,
    }

    return render(
        request,
        "core/student_financial_profile.html",
        context,
    )

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Payment
from datetime import datetime

@login_required
def daily_collections(request):
    # Get the date from GET parameters, default to today's date
    date_str = request.GET.get('date')
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = timezone.now().date()
    else:
        selected_date = timezone.now().date()

    # Filter payments for the selected date
    payments = Payment.objects.filter(date_paid__date=selected_date).select_related('student', 'term', 'academic_year')

    # Calculate totals
    total_collected = sum(p.amount_paid for p in payments)
    
    # Optional breakdown by method
    method_totals = {}
    for p in payments:
        method = p.get_payment_method_display() if hasattr(p, 'get_payment_method_display') else p.payment_method
        method_totals[method] = method_totals.get(method, 0) + p.amount_paid

    context = {
        'payments': payments,
        'selected_date': selected_date,
        'total_collected': total_collected,
        'method_totals': method_totals,
    }
    return render(request, 'core/daily_collections.html', context)
from decimal import Decimal
from django.db.models import Sum
from core.models import StudentFee, FeeStructure, Term

def generate_student_fees_for_term(*, school, term):
    """
    Generate student fee obligations for one school and term.

    Existing obligations are preserved. The caller must
    separately authorize the school before invoking this
    service.
    """
    from decimal import Decimal

    from django.core.exceptions import ValidationError
    from django.db import transaction
    from django.db.models import Sum

    from .models import (
        StudentProfile,
        StudentFee,
        FeeStructure,
    )

    if school is None or term is None:
        raise ValidationError(
            "School and term are required."
        )

    if term.school_id != school.pk:
        raise ValidationError(
            "The selected term does not belong to this school."
        )

    if term.academic_year.school_id != school.pk:
        raise ValidationError(
            "The academic year does not belong to this school."
        )

    structures = FeeStructure.objects.filter(
        school=school,
        term=term,
        academic_year=term.academic_year,
        class_stream__school=school,
        category__school=school,
    )

    totals = dict(
        structures.values("class_stream_id")
        .annotate(total=Sum("amount"))
        .values_list("class_stream_id", "total")
    )

    students = StudentProfile.objects.filter(
        school=school,
        current_class__school=school,
        current_class_id__in=totals.keys(),
    )

    created_count = 0

    with transaction.atomic():
        for student in students:
            total = totals.get(
                student.current_class_id,
                Decimal("0.00"),
            )

            if total is None:
                continue

            existing = StudentFee.objects.filter(
                school=school,
                student=student,
                academic_year=term.academic_year,
                term=term,
            ).exists()

            if existing:
                continue

            StudentFee.objects.create(
                school=school,
                student=student,
                academic_year=term.academic_year,
                term=term,
                total_expected=total,
            )

            created_count += 1

    return created_count

# views.py (Finance)
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.utils import timezone
from django.contrib import messages
from .models import Payment

from decimal import Decimal
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import get_object_or_404, render
from .models import StudentProfile, StudentEnrollment, Payment, StudentFee, FeeStructure, Term


@login_required
def student_financial_statement(request, student_id):
    """School-scoped financial statement with student self-access."""
    from decimal import Decimal
    from django.db.models import Sum
    from django.core.exceptions import PermissionDenied
    from django.shortcuts import get_object_or_404, render
    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    context = require_school_context(request.user)

    student = get_object_or_404(
        school_queryset(StudentProfile, context).filter(
            user__school_memberships__school=context.school,
            user__school_memberships__is_active=True,
        ).distinct(),
        pk=student_id,
    )

    is_owner = student.user_id == request.user.pk

    if is_owner:
        require_school_role(
            context, "student", "administrator", "accountant"
        )
    else:
        require_school_role(
            context, "administrator", "accountant"
        )

    enrollments = school_queryset(
        StudentEnrollment, context
    ).filter(
        student=student,
        academic_year__school=context.school,
        term__school=context.school,
        class_stream__school=context.school,
    ).select_related(
        "class_stream", "term", "academic_year"
    )

    payments = school_queryset(
        Payment, context
    ).filter(
        student=student,
        academic_year__school=context.school,
        term__school=context.school,
    ).order_by("-date_paid")

    total_expected = Decimal("0.00")

    for enrollment in enrollments:
        expected_sum = school_queryset(
            StudentFee, context
        ).filter(
            student=student,
            academic_year=enrollment.academic_year,
            term=enrollment.term,
        ).aggregate(
            total=Sum("total_expected")
        )["total"]

        if expected_sum is None:
            expected_sum = school_queryset(
                FeeStructure, context
            ).filter(
                academic_year=enrollment.academic_year,
                term=enrollment.term,
                class_stream=enrollment.class_stream,
                category__school=context.school,
            ).aggregate(
                total=Sum("amount")
            )["total"] or Decimal("0.00")

        total_expected += Decimal(str(expected_sum))

    total_paid = payments.filter(
        is_voided=False
    ).aggregate(
        total=Sum("amount_paid")
    )["total"] or Decimal("0.00")

    outstanding_balance = max(
        total_expected - total_paid,
        Decimal("0.00"),
    )

    return render(
        request,
        "core/student_statement.html",
        {
            "student": student,
            "enrollments": enrollments,
            "payments": payments,
            "total_expected": total_expected,
            "total_paid": total_paid,
            "outstanding_balance": outstanding_balance,
        },
    )

from decimal import Decimal
from django.utils import timezone
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum
from django.shortcuts import render
from .models import Payment

@login_required
def daily_collection_report(request):
    """
    School-scoped daily collection report.
    Excludes voided payments from all financial totals.
    """
    from datetime import datetime
    from decimal import Decimal

    from django.db.models import Sum
    from django.shortcuts import render
    from django.utils import timezone

    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )
    from .models import Payment

    school_context = require_school_context(request.user)
    require_school_role(
        school_context,
        "administrator",
        "accountant",
    )

    date_str = request.GET.get("date", "").strip()

    try:
        report_date = (
            datetime.strptime(date_str, "%Y-%m-%d").date()
            if date_str
            else timezone.localdate()
        )
    except ValueError:
        report_date = timezone.localdate()

    payments = (
        school_queryset(Payment, school_context)
        .filter(
            date_paid__date=report_date,
            is_voided=False,
            student__school=school_context.school,
            academic_year__school=school_context.school,
            term__school=school_context.school,
        )
        .select_related("student", "term", "academic_year")
        .order_by("-date_paid", "-pk")
    )

    method_summaries = (
        payments.values("payment_method")
        .annotate(total=Sum("amount_paid"))
        .order_by("payment_method")
    )

    total_sum = payments.aggregate(
        total=Sum("amount_paid")
    )["total"]

    total_collection = (
        total_sum if total_sum is not None
        else Decimal("0.00")
    )

    return render(
        request,
        "core/daily_collection_report.html",
        {
            "report_date": report_date,
            "payments": payments,
            "method_summaries": method_summaries,
            "total_collection": total_collection,
            "total_transactions": payments.count(),
            "school": school_context.school,
        },
    )
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Q
# Make sure to import your Student model (adjust app name as needed)
from .models import StudentProfile as Student


@login_required
def student_search(request):
    """
    Search students belonging only to the authenticated user's school.

    Accessible to school administrators and accountants.
    """
    from django.db.models import Q
    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )
    from .models import StudentProfile

    school_context = require_school_context(request.user)

    require_school_role(
        school_context,
        "administrator",
        "accountant",
    )

    query = request.GET.get("q", "").strip()

    students = StudentProfile.objects.none()

    if query:
        students = (
            school_queryset(StudentProfile, school_context)
            .filter(
                Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(registration_number__icontains=query)
            )
            .order_by("id")[:50]
        )

    context = {
        "query": query,
        "students": students,
        "school": school_context.school,
    }

    return render(
        request,
        "accountant/student_search.html",
        context,
    )

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from .models import Payment, ClassStream, StudentFee, FeeStructure, Term

@login_required
def class_collections_report(request):
    """
    School-scoped class collections for the current academic term.
    """
    from decimal import Decimal

    from django.db.models import Sum
    from django.shortcuts import render

    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    from .models import (
        AcademicYear,
        Term,
        ClassStream,
        StudentEnrollment,
        StudentFee,
        FeeStructure,
        Payment,
    )

    school_context = require_school_context(request.user)
    require_school_role(
        school_context,
        "administrator",
        "accountant",
    )

    school = school_context.school
    zero = Decimal("0.00")

    current_year = (
        school_queryset(AcademicYear, school_context)
        .filter(is_current=True)
        .first()
    )

    current_term = None

    if current_year is not None:
        current_term = (
            school_queryset(Term, school_context)
            .filter(
                academic_year=current_year,
                is_current=True,
            )
            .first()
        )

    class_data = []

    if current_term is not None:
        classes = (
            school_queryset(ClassStream, school_context)
            .order_by("name", "pk")
        )

        enrollments = (
            school_queryset(StudentEnrollment, school_context)
            .filter(
                academic_year=current_year,
                term=current_term,
                student__school=school,
                class_stream__school=school,
                academic_year__school=school,
                term__school=school,
            )
            .select_related("student", "class_stream")
            .order_by("student_id", "-date_enrolled", "-pk")
        )

        # Keep the latest enrollment per student for this term.
        students_by_class = {}
        seen_students = set()

        for enrollment in enrollments:
            if enrollment.student_id in seen_students:
                continue

            seen_students.add(enrollment.student_id)

            students_by_class.setdefault(
                enrollment.class_stream_id, []
            ).append(enrollment.student)

        for class_stream in classes:
            students = students_by_class.get(class_stream.pk, [])

            total_expected = zero
            total_collected = zero
            transaction_count = 0

            structure_sum = (
                school_queryset(FeeStructure, school_context)
                .filter(
                    class_stream=class_stream,
                    academic_year=current_year,
                    term=current_term,
                    class_stream__school=school,
                    academic_year__school=school,
                    term__school=school,
                )
                .aggregate(total=Sum("amount"))["total"]
            )

            structure_expected = (
                structure_sum
                if structure_sum is not None
                else zero
            )

            for student in students:
                expected_sum = (
                    school_queryset(StudentFee, school_context)
                    .filter(
                        student=student,
                        academic_year=current_year,
                        term=current_term,
                        student__school=school,
                        academic_year__school=school,
                        term__school=school,
                    )
                    .aggregate(total=Sum("total_expected"))["total"]
                )

                expected = (
                    expected_sum
                    if expected_sum is not None
                    else structure_expected
                )

                payments = (
                    school_queryset(Payment, school_context)
                    .filter(
                        student=student,
                        academic_year=current_year,
                        term=current_term,
                        student__school=school,
                        academic_year__school=school,
                        term__school=school,
                        is_voided=False,
                    )
                )

                paid_sum = payments.aggregate(
                    total=Sum("amount_paid")
                )["total"]

                total_expected += expected
                total_collected += (
                    paid_sum if paid_sum is not None else zero
                )
                transaction_count += payments.count()

            balance = total_expected - total_collected

            collection_rate = (
                round(
                    float(
                        total_collected / total_expected * 100
                    ),
                    1,
                )
                if total_expected > zero
                else 0.0
            )

            class_data.append({
                "class_id": class_stream.pk,
                "class_name": class_stream.name,
                "total_students": len(students),
                "total_expected": total_expected,
                "total_collected": total_collected,
                "balance": balance,
                "collection_rate": collection_rate,
                "transaction_count": transaction_count,
            })

    return render(
        request,
        "accountant/class_collections_report.html",
        {
            "class_data": class_data,
            "school": school,
            "current_year": current_year,
            "current_term": current_term,
            "finance_ready": current_term is not None,
        },
    )

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from .models import Payment, ClassStream, StudentFee, FeeStructure, Term

@login_required
def class_collection_detail(request, class_id):
    """
    School-scoped class financial details for the current term.
    """
    from decimal import Decimal

    from django.db.models import Sum
    from django.shortcuts import get_object_or_404, render

    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    from .models import (
        AcademicYear,
        Term,
        ClassStream,
        StudentEnrollment,
        StudentFee,
        FeeStructure,
        Payment,
    )

    school_context = require_school_context(request.user)

    require_school_role(
        school_context,
        "administrator",
        "accountant",
    )

    school = school_context.school
    zero = Decimal("0.00")

    # A foreign school's class ID must return HTTP 404.
    class_stream = get_object_or_404(
        school_queryset(ClassStream, school_context),
        pk=class_id,
    )

    current_year = (
        school_queryset(AcademicYear, school_context)
        .filter(is_current=True)
        .first()
    )

    current_term = None

    if current_year is not None:
        current_term = (
            school_queryset(Term, school_context)
            .filter(
                academic_year=current_year,
                is_current=True,
            )
            .first()
        )

    student_details = []
    class_total_expected = zero
    class_total_collected = zero

    if current_term is not None:
        enrollments = (
            school_queryset(StudentEnrollment, school_context)
            .filter(
                class_stream=class_stream,
                academic_year=current_year,
                term=current_term,
                student__school=school,
                class_stream__school=school,
                academic_year__school=school,
                term__school=school,
            )
            .select_related("student")
            .order_by("student_id", "-date_enrolled", "-pk")
        )

        # Match the summary report's deduplication rule.
        seen_students = set()

        structure_sum = (
            school_queryset(FeeStructure, school_context)
            .filter(
                class_stream=class_stream,
                academic_year=current_year,
                term=current_term,
                class_stream__school=school,
                academic_year__school=school,
                term__school=school,
            )
            .aggregate(total=Sum("amount"))["total"]
        )

        structure_expected = (
            structure_sum
            if structure_sum is not None
            else zero
        )

        for enrollment in enrollments:
            student = enrollment.student

            if student.pk in seen_students:
                continue

            seen_students.add(student.pk)

            expected_sum = (
                school_queryset(StudentFee, school_context)
                .filter(
                    student=student,
                    academic_year=current_year,
                    term=current_term,
                    student__school=school,
                    academic_year__school=school,
                    term__school=school,
                )
                .aggregate(total=Sum("total_expected"))["total"]
            )

            expected = (
                expected_sum
                if expected_sum is not None
                else structure_expected
            )

            payments = (
                school_queryset(Payment, school_context)
                .filter(
                    student=student,
                    academic_year=current_year,
                    term=current_term,
                    student__school=school,
                    academic_year__school=school,
                    term__school=school,
                    is_voided=False,
                )
            )

            paid_sum = payments.aggregate(
                total=Sum("amount_paid")
            )["total"]

            collected = (
                paid_sum if paid_sum is not None else zero
            )

            balance = expected - collected

            class_total_expected += expected
            class_total_collected += collected

            student_details.append({
                "student": student,
                "expected": expected,
                "collected": collected,
                "balance": balance,
                "payments_count": payments.count(),
            })

    class_balance = (
        class_total_expected - class_total_collected
    )

    return render(
        request,
        "accountant/class_collection_detail.html",
        {
            "class_stream": class_stream,
            "student_details": student_details,
            "class_total_expected": class_total_expected,
            "class_total_collected": class_total_collected,
            "class_balance": class_balance,
            "school": school,
            "current_year": current_year,
            "current_term": current_term,
            "finance_ready": current_term is not None,
        },
    )

from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from .models import StudentProfile

@login_required
def accountant_student_profile(request, student_id):
    """Only school accountants/admins may view school student profiles."""
    from django.shortcuts import get_object_or_404, render
    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )

    context = require_school_context(request.user)
    require_school_role(
        context, "administrator", "accountant"
    )

    student = get_object_or_404(
        school_queryset(StudentProfile, context),
        pk=student_id,
    )

    return render(
        request,
        "accountant/student_profile.html",
        {"student": student},
    )

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from core.models import StudentProfile, StudentFee, Payment, FeeStructure, Term, StudentEnrollment

@login_required
def student_finances_view(request):
    # Ensure the logged-in user is mapped to a student profile
    try:
        student = request.user.studentprofile
    except AttributeError:
        student = get_object_or_404(StudentProfile, user=request.user)

    # Get active term
    current_term = Term.objects.filter(is_current=True).first()

    # 1. Fee Overview & Breakdown Calculations
    student_fees = StudentFee.objects.filter(student=student, term=current_term) if current_term else StudentFee.objects.none()
    total_expected = student_fees.aggregate(sum=Sum('total_expected'))['sum'] or 0

    fee_breakdown = []

    if current_term and not student_fees.exists():
        # No StudentFee assigned manually yet — fall back to the class's FeeStructure
        enrollment = StudentEnrollment.objects.filter(
            student=student, term=current_term
        ).select_related('class_stream').first()

        if enrollment and enrollment.class_stream:
            structure_items = FeeStructure.objects.filter(
                academic_year=current_term.academic_year,
                term=current_term,
                class_stream=enrollment.class_stream,
            ).select_related('category')

            total_expected = structure_items.aggregate(sum=Sum('amount'))['sum'] or 0
            fee_breakdown = structure_items

    # Calculate total paid using 'amount_paid' and ignoring voided payments
    payments_query = Payment.objects.filter(student=student, is_voided=False)
    if current_term:
        payments_query = payments_query.filter(term=current_term)

    total_paid = payments_query.aggregate(sum=Sum('amount_paid'))['sum'] or 0

    balance = total_expected - total_paid

    # Determine status
    if total_expected == 0:
        fee_status = "NO FEES SET"
    elif balance == 0:
        fee_status = "PAID"
    elif balance < 0:
        fee_status = "CREDIT"
    else:
        fee_status = "PARTIALLY PAID"

    # 2. Valid Payment History & Receipts
    payments = Payment.objects.filter(student=student, is_voided=False).order_by('-date_paid')

    context = {
        'student': student,
        'current_term': current_term,
        'total_expected': total_expected,
        'total_paid': total_paid,
        'balance': abs(balance),
        'raw_balance': balance,
        'fee_status': fee_status,
        'student_fees': student_fees,
        'fee_breakdown': fee_breakdown,
        'payments': payments,
    }
    return render(request, 'student/finances.html', context)


@login_required
def fee_configuration(request):
    """School-specific fee category and structure management."""
    from decimal import Decimal, InvalidOperation
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError, transaction
    from django.shortcuts import redirect, render

    from tenants.access import (
        require_school_context,
        require_school_role,
        school_queryset,
    )
    from .models import (
        AcademicYear, Term, ClassStream,
        FeeCategory, FeeStructure,
    )

    school_context = require_school_context(request.user)
    require_school_role(school_context, "administrator")
    school = school_context.school

    years = school_queryset(
        AcademicYear, school_context
    ).order_by("-id")

    terms = school_queryset(
        Term, school_context
    ).select_related("academic_year").order_by("-id")

    classes = school_queryset(
        ClassStream, school_context
    ).order_by("name")

    categories = school_queryset(
        FeeCategory, school_context
    ).order_by("name")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "generate_fees":
            raw_term_id = request.POST.get("term", "").strip()

            if not raw_term_id.isdecimal():
                messages.error(request, "Select a valid term.")
            else:
                selected_term = terms.filter(
                    pk=int(raw_term_id)
                ).first()

                if selected_term is None:
                    messages.error(
                        request,
                        "The selected term does not belong to your school.",
                    )
                else:
                    try:
                        created_count = generate_student_fees_for_term(
                            school=school,
                            term=selected_term,
                        )
                    except ValidationError:
                        messages.error(
                            request,
                            "Student fees could not be generated.",
                        )
                    else:
                        messages.success(
                            request,
                            f"{created_count} student fee "
                            "obligation(s) created. "
                            "Existing obligations were preserved.",
                        )
                        return redirect("fee_configuration")

        elif action == "create_category":
            name = request.POST.get("name", "").strip()
            description = request.POST.get(
                "description", ""
            ).strip()

            if not name:
                messages.error(
                    request, "Category name is required."
                )
            else:
                try:
                    with transaction.atomic():
                        FeeCategory.objects.create(
                            school=school,
                            name=name,
                            description=description,
                        )
                except (ValidationError, IntegrityError):
                    messages.error(
                        request,
                        "Category could not be created. "
                        "The name may already exist.",
                    )
                else:
                    messages.success(
                        request, "Fee category created."
                    )
                    return redirect("fee_configuration")

        elif action == "create_structure":
            def selected_record(queryset, field_name):
                raw_id = request.POST.get(field_name, "").strip()

                if not raw_id.isdecimal():
                    return None

                return queryset.filter(pk=int(raw_id)).first()

            year = selected_record(years, "academic_year")
            term = selected_record(terms, "term")
            class_stream = selected_record(classes, "class_stream")
            category = selected_record(categories, "category")

            try:
                amount = Decimal(
                    request.POST.get("amount", "").strip()
                )
            except (InvalidOperation, ValueError):
                amount = None

            if (
                not all((year, term, class_stream, category))
                or amount is None
                or not amount.is_finite()
                or amount <= 0
                or term.academic_year_id != year.pk
            ):
                messages.error(
                    request,
                    "Select valid school records and "
                    "enter a positive amount.",
                )
            elif FeeStructure.objects.filter(
                school=school,
                academic_year=year,
                term=term,
                class_stream=class_stream,
                category=category,
            ).exists():
                messages.error(
                    request,
                    "This fee structure already exists.",
                )
            else:
                try:
                    with transaction.atomic():
                        FeeStructure.objects.create(
                            school=school,
                            academic_year=year,
                            term=term,
                            class_stream=class_stream,
                            category=category,
                            amount=amount,
                        )
                except (ValidationError, IntegrityError):
                    messages.error(
                        request,
                        "Fee structure could not be saved.",
                    )
                else:
                    messages.success(
                        request, "Fee structure created."
                    )
                    return redirect("fee_configuration")
        else:
            messages.error(request, "Invalid action.")

    structures = school_queryset(
        FeeStructure, school_context
    ).select_related(
        "academic_year", "term",
        "class_stream", "category"
    ).order_by("-id")

    return render(
        request,
        "core/fee_configuration.html",
        {
            "school": school,
            "years": years,
            "terms": terms,
            "classes": classes,
            "categories": categories,
            "structures": structures,
        },
    )
