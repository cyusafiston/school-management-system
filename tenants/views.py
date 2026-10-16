
import uuid

from django.contrib import messages
from django.contrib.auth import login
from django.db import transaction
from django.shortcuts import redirect
from django.utils.text import slugify

from .forms import SchoolRegistrationForm
from .models import School, SchoolMembership

"""Tenant-specific views for the School Management System."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .access import require_school_context


@login_required
def school_home(request):
    """
    Safe landing page for a user belonging to one approved school.

    This page does not access any unscoped core school records.
    """
    context = require_school_context(request.user)

    return render(
        request,
        "tenants/school_home.html",
        {
            "school": context.school,
            "membership": context.membership,
            "school_role": context.role,
        },
    )


def register_school(request):
    """Register a school application awaiting platform approval."""
    if request.user.is_authenticated:
        return redirect("role_redirect")

    if request.method == "POST":
        form = SchoolRegistrationForm(request.POST)

        if form.is_valid():
            with transaction.atomic():
                user = form.save(commit=False)
                user.is_staff = False
                user.is_superuser = False
                user.is_active = True
                user.save()

                school_name = form.cleaned_data["school_name"]
                base_slug = slugify(school_name)[:170] or "school"

                school = School.objects.create(
                    name=school_name,
                    slug=f"{base_slug}-{uuid.uuid4().hex[:12]}",
                    email=form.cleaned_data.get("school_email", ""),
                    phone_number=form.cleaned_data.get("school_phone", ""),
                    address=form.cleaned_data.get("school_address", ""),
                    status=School.Status.PENDING,
                    created_by=user,
                )

                SchoolMembership.objects.create(
                    school=school,
                    user=user,
                    role=SchoolMembership.Role.ADMINISTRATOR,
                    is_active=True,
                )

            messages.success(
                request,
                "Your school application has been submitted. "
                "Please wait for platform approval before signing in.",
            )
            return redirect("login")
    else:
        form = SchoolRegistrationForm()

    return render(
        request,
        "tenants/register_school.html",
        {"form": form},
    )


@login_required
def curriculum_management(request):
    """School administrator curriculum management."""
    from django.contrib import messages
    from django.db import IntegrityError, transaction
    from django.core.exceptions import ValidationError
    from django.shortcuts import redirect
    from core.models import AcademicYear, ClassStream, ClassSubject
    from tenants.access import require_school_context, require_school_role
    from tenants.forms import ClassSubjectForm

    context = require_school_context(request.user)
    require_school_role(context, "administrator")

    school = context.school

    if request.method == "POST":
        form = ClassSubjectForm(request.POST, school=school)

        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
            except (IntegrityError, ValidationError):
                form.add_error(
                    None,
                    "This curriculum assignment already exists or is invalid."
                )
            else:
                messages.success(
                    request,
                    "Curriculum subject assigned successfully."
                )
                return redirect("curriculum_management")
    else:
        form = ClassSubjectForm(school=school)

    academic_years = AcademicYear.objects.filter(
        school=school
    ).order_by("-name")

    classes = ClassStream.objects.filter(
        school=school
    ).order_by("name")

    curriculum = ClassSubject.objects.filter(
        school=school,
        academic_year__school=school,
        class_stream__school=school,
        subject__school=school,
    ).select_related(
        "academic_year",
        "class_stream",
        "subject",
    ).order_by(
        "-academic_year__name",
        "class_stream__name",
        "subject__name",
    )

    return render(
        request,
        "tenants/curriculum_management.html",
        {
            "school": school,
            "academic_years": academic_years,
            "classes": classes,
            "curriculum": curriculum,
            "form": form,
        },
    )


@login_required
def remove_curriculum_assignment(request, assignment_id):
    """Remove a curriculum assignment from the administrator's school."""
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect
    from django.views.decorators.http import require_POST
    from core.models import ClassSubject
    from tenants.access import require_school_context, require_school_role

    context = require_school_context(request.user)
    require_school_role(context, "administrator")

    # Enforce POST without permitting deletion through GET.
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])

    assignment = get_object_or_404(
        ClassSubject,
        pk=assignment_id,
        school=context.school,
        academic_year__school=context.school,
        class_stream__school=context.school,
        subject__school=context.school,
    )

    assignment.delete()

    messages.success(
        request,
        "Curriculum assignment removed successfully."
    )

    return redirect("curriculum_management")


@login_required
def edit_curriculum_requirement(request, assignment_id):
    """Edit a curriculum subject's required/optional status."""
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect
    from core.models import ClassSubject
    from tenants.access import require_school_context, require_school_role
    from tenants.forms import ClassSubjectRequirementForm

    context = require_school_context(request.user)
    require_school_role(context, "administrator")

    assignment = get_object_or_404(
        ClassSubject,
        pk=assignment_id,
        school=context.school,
        academic_year__school=context.school,
        class_stream__school=context.school,
        subject__school=context.school,
    )

    if request.method == "POST":
        form = ClassSubjectRequirementForm(
            request.POST,
            school=context.school,
            instance=assignment,
        )

        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Curriculum requirement updated successfully."
            )
            return redirect("curriculum_management")
    else:
        form = ClassSubjectRequirementForm(
            school=context.school,
            instance=assignment,
        )

    return render(
        request,
        "tenants/edit_curriculum_requirement.html",
        {
            "school": context.school,
            "assignment": assignment,
            "form": form,
        },
    )



# ============================================================
# SCHOOL ACADEMIC SETUP
# ============================================================

@login_required
def academic_setup(request):
    """Manage classes and subjects within one approved school."""
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError, transaction
    from django.shortcuts import render, redirect

    from core.models import ClassStream, Subject
    from tenants.access import require_school_context, require_school_role
    from tenants.forms import ClassStreamForm, SubjectSetupForm

    context = require_school_context(request.user)
    require_school_role(context, "administrator")

    school = context.school

    class_form = ClassStreamForm(school=school)
    subject_form = SubjectSetupForm(school=school)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create_class":
            class_form = ClassStreamForm(request.POST, school=school)

            if class_form.is_valid():
                try:
                    with transaction.atomic():
                        class_form.save()
                except (IntegrityError, ValidationError):
                    class_form.add_error(
                        None,
                        "Unable to create this class. Please check the details."
                    )
                else:
                    messages.success(request, "Class created successfully.")
                    return redirect("academic_setup")

        elif action == "create_subject":
            subject_form = SubjectSetupForm(request.POST, school=school)

            if subject_form.is_valid():
                try:
                    with transaction.atomic():
                        subject_form.save()
                except (IntegrityError, ValidationError):
                    subject_form.add_error(
                        None,
                        "Unable to create this subject. Please check the details."
                    )
                else:
                    messages.success(request, "Subject created successfully.")
                    return redirect("academic_setup")

        else:
            from django.http import HttpResponseBadRequest
            return HttpResponseBadRequest("Invalid academic setup action.")

    classes = ClassStream.objects.filter(
        school=school
    ).order_by("name")

    subjects = Subject.objects.filter(
        school=school
    ).order_by("name")

    return render(
        request,
        "tenants/academic_setup.html",
        {
            "school": school,
            "school_role": context.role,
            "class_form": class_form,
            "subject_form": subject_form,
            "classes": classes,
            "subjects": subjects,
        },
    )
