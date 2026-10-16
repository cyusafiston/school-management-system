from decimal import Decimal

from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
    RelatedDropdownFilter,
)
from unfold.decorators import action, display
from unfold.enums import ActionVariant
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .models import (
    AcademicYear,
    Attendance,
    ClassStream,
    DailyClassAttendance,
    FeeCategory,
    FeeStructure,
    Grade,
    Homework,
    Notice,
    Payment,
    StudentEnrollment,
    StudentFee,
    StudentProfile,
    Subject,
    TeacherAssignment,
    Term,
    UserProfile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rwf(value):
    """120000 -> '120,000 RWF'"""
    return f"{Decimal(value or 0):,.0f} RWF"


def get_current_term():
    return Term.objects.filter(is_current=True).select_related("academic_year").first()


class BaseAdmin(ModelAdmin):
    """Shared defaults for every model admin."""
    list_per_page = 25
    compressed_fields = True
    warn_unsaved_form = True


# ---------------------------------------------------------------------------
# Users & groups (re-registered so they are styled by Unfold)
# ---------------------------------------------------------------------------

admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    list_display = ("username", "first_name", "last_name", "email", "is_staff", "is_active")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")
    list_per_page = 25


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


# ---------------------------------------------------------------------------
# Academic structure
# ---------------------------------------------------------------------------

@admin.register(AcademicYear)
class AcademicYearAdmin(BaseAdmin):
    list_display = ("name", "is_current")
    list_filter = ("is_current",)


@admin.register(Term)
class TermAdmin(BaseAdmin):
    list_display = ("name", "academic_year", "is_current")
    list_filter = (("academic_year", RelatedDropdownFilter), "is_current")
    list_select_related = ("academic_year",)


@admin.register(ClassStream)
class ClassStreamAdmin(BaseAdmin):
    list_display = ("name", "code", "student_count")
    search_fields = ("name", "code")
    readonly_fields = ("code",)
    actions_row = ["view_collections"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_students=Count("studentprofile"))

    @display(description=_("Students"), ordering="_students")
    def student_count(self, obj):
        return obj._students

    @action(description=_("Collections"), url_path="collections", icon="payments")
    def view_collections(self, request, object_id):
        return redirect(reverse("class_collection_detail", args=[object_id]))


@admin.register(Subject)
class SubjectAdmin(BaseAdmin):
    list_display = ("name", "code", "max_cat_marks", "max_exam_marks")
    search_fields = ("name", "code")
    readonly_fields = ("code",)


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

class StudentEnrollmentInline(TabularInline):
    model = StudentEnrollment
    tab = True
    extra = 0
    fields = ("academic_year", "term", "class_stream", "status")


class StudentFeeInline(TabularInline):
    model = StudentFee
    tab = True
    extra = 0
    can_delete = False
    verbose_name_plural = _("Assigned fees")
    fields = ("academic_year", "term", "expected_display", "created_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    @display(description=_("Total expected"))
    def expected_display(self, obj):
        return rwf(obj.total_expected)


class PaymentInline(TabularInline):
    model = Payment
    tab = True
    extra = 0
    can_delete = False
    show_change_link = True
    ordering = ("-date_paid",)
    verbose_name_plural = _("Payment history")
    fields = ("receipt_number", "amount_display", "payment_method", "term", "date_paid", "status_display")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    @display(description=_("Amount"))
    def amount_display(self, obj):
        return rwf(obj.amount_paid)

    @display(description=_("Status"))
    def status_display(self, obj):
        return "Voided" if obj.is_voided else "Valid"


@admin.register(StudentProfile)
class StudentProfileAdmin(BaseAdmin):
    list_display = (
        "student_display",
        "current_class",
        "gender",
        "age",
        "father_phone",
        "mother_phone",
        "date_enrolled",
    )
    list_display_links = ("student_display",)
    list_select_related = ("current_class",)
    list_filter_submit = True
    list_filter = (
        ("current_class", RelatedDropdownFilter),
        ("gender", ChoicesDropdownFilter),
        ("date_enrolled", RangeDateFilter),
    )
    search_fields = (
        "first_name",
        "last_name",
        "registration_number",
        "father_name",
        "father_phone",
        "mother_name",
        "mother_phone",
    )
    list_editable = ("current_class",)
    readonly_fields = ("registration_number", "age")
    inlines = [StudentEnrollmentInline, StudentFeeInline, PaymentInline]

    fieldsets = (
        (_("Personal information"), {"fields": (("first_name", "last_name"), ("date_of_birth", "age"), "gender")}),
        (_("Academic details"), {"fields": ("registration_number", "current_class")}),
        (_("Father"), {"fields": (("father_name", "father_phone"),)}),
        (_("Mother"), {"fields": (("mother_name", "mother_phone"),)}),
    )

    actions_row = ["view_statement", "view_finances"]
    actions_detail = ["view_statement", "view_finances", "new_payment"]

    @display(description=_("Student"), header=True)
    def student_display(self, obj):
        initials = f"{obj.first_name[:1]}{obj.last_name[:1]}".upper()
        return [f"{obj.first_name} {obj.last_name}", obj.registration_number, initials]

    @action(description=_("Statement"), url_path="statement", icon="receipt_long")
    def view_statement(self, request, object_id):
        return redirect(reverse("student_financial_statement", args=[object_id]))

    @action(description=_("Finances"), url_path="finances", icon="account_balance_wallet")
    def view_finances(self, request, object_id):
        return redirect(reverse("student_financial_profile", args=[object_id]))

    @action(description=_("Record payment"), url_path="new-payment", icon="add_card", variant=ActionVariant.PRIMARY)
    def new_payment(self, request, object_id):
        return redirect(reverse("record_payment"))


# ---------------------------------------------------------------------------
# Grades, teachers, homework, notices
# ---------------------------------------------------------------------------

@admin.register(Grade)
class GradeAdmin(BaseAdmin):
    list_display = ("student", "subject", "term", "cat_marks", "exam_marks", "marks_obtained", "grade_letter", "status")
    list_select_related = ("student", "subject", "term")
    list_filter = (
        ("term", RelatedDropdownFilter),
        ("subject", RelatedDropdownFilter),
        "status",
        "grade_letter",
    )
    search_fields = ("student__first_name", "student__last_name", "student__registration_number", "subject__name")
    list_editable = ("cat_marks", "exam_marks", "status")
    autocomplete_fields = ("student",)


@admin.register(UserProfile)
class UserProfileAdmin(BaseAdmin):
    list_display = ("user", "role", "phone_number")
    list_filter = ("role",)
    search_fields = ("user__username", "user__first_name", "user__last_name", "phone_number")


@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(BaseAdmin):
    list_display = ("teacher", "subject", "current_class", "term")
    list_select_related = ("teacher", "subject", "current_class", "term")
    list_filter = (
        ("term", RelatedDropdownFilter),
        ("current_class", RelatedDropdownFilter),
        ("subject", RelatedDropdownFilter),
    )
    search_fields = ("teacher__username", "subject__name", "current_class__name")


@admin.register(StudentEnrollment)
class StudentEnrollmentAdmin(BaseAdmin):
    list_display = ("student", "class_stream", "academic_year", "term", "status", "date_enrolled")
    list_select_related = ("student", "class_stream", "academic_year", "term")
    list_filter = (
        ("academic_year", RelatedDropdownFilter),
        ("term", RelatedDropdownFilter),
        ("class_stream", RelatedDropdownFilter),
        "status",
    )
    search_fields = ("student__first_name", "student__last_name", "student__registration_number")
    list_editable = ("status",)
    autocomplete_fields = ("student",)


@admin.register(Homework)
class HomeworkAdmin(BaseAdmin):
    list_display = ("title", "assignment", "due_date", "created_at")
    list_filter = ("due_date", "created_at", ("assignment__subject", RelatedDropdownFilter))
    search_fields = ("title", "description", "assignment__subject__name")
    readonly_fields = ("created_at",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "assignment", "assignment__subject", "assignment__current_class", "assignment__teacher"
        )


@admin.register(Notice)
class NoticeAdmin(BaseAdmin):
    list_display = ("title", "target_class", "created_at", "expires_at")
    list_filter = (("target_class", RelatedDropdownFilter), "created_at", "expires_at")
    search_fields = ("title", "content")


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

@admin.register(DailyClassAttendance)
class DailyClassAttendanceAdmin(BaseAdmin):
    list_display = ("student", "current_class", "date", "status", "submitted_by", "is_locked")
    list_filter = ("date", "status", ("current_class", RelatedDropdownFilter), "is_locked")
    search_fields = ("student__first_name", "student__last_name", "student__registration_number", "submitted_by__username")
    list_editable = ("status", "is_locked")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("student", "current_class", "submitted_by")

    def changelist_view(self, request, extra_context=None):
        # The attendance report page replaces the raw changelist
        return redirect("admin_attendance_report")


@admin.register(Attendance)
class AttendanceAdmin(BaseAdmin):
    list_display = ("student", "date", "status", "recorded_by")
    list_filter = ("date", "status")
    search_fields = ("student__first_name", "student__last_name", "student__registration_number")
    list_editable = ("status",)
    autocomplete_fields = ("student",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("student", "recorded_by")


# ---------------------------------------------------------------------------
# Finance
# ---------------------------------------------------------------------------

@admin.register(FeeCategory)
class FeeCategoryAdmin(BaseAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)


@admin.register(FeeStructure)
class FeeStructureAdmin(BaseAdmin):
    list_display = ("class_stream", "category", "amount_display", "term", "academic_year")
    list_select_related = ("academic_year", "term", "class_stream", "category")
    list_filter = (
        ("academic_year", RelatedDropdownFilter),
        ("term", RelatedDropdownFilter),
        ("class_stream", RelatedDropdownFilter),
        ("category", RelatedDropdownFilter),
    )
    search_fields = ("class_stream__name", "category__name")
    ordering = ("-academic_year__name", "term__name", "class_stream__id", "category__name")

    fieldsets = (
        (_("Applies to"), {"fields": ("academic_year", "term", "class_stream")}),
        (_("Fee"), {"fields": ("category", "amount")}),
    )

    @display(description=_("Amount"), ordering="amount")
    def amount_display(self, obj):
        return rwf(obj.amount)


@admin.register(StudentFee)
class StudentFeeAdmin(BaseAdmin):
    list_display = ("student", "academic_year", "term", "expected_display", "paid_display", "balance_display", "status_badge")
    list_select_related = ("student", "academic_year", "term")
    list_filter_submit = True
    list_filter = (
        ("academic_year", RelatedDropdownFilter),
        ("term", RelatedDropdownFilter),
        ("total_expected", RangeNumericFilter),
    )
    search_fields = ("student__first_name", "student__last_name", "student__registration_number")
    autocomplete_fields = ("student",)
    readonly_fields = ("created_at",)

    fieldsets = (
        (_("Student"), {"fields": ("student",)}),
        (_("Period"), {"fields": (("academic_year", "term"),)}),
        (_("Amount"), {"fields": ("total_expected", "created_at")}),
    )

    actions_list = ["generate_fees", "new_payment", "debtors"]
    actions_row = ["view_statement", "view_finances"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _paid=Sum(
                "student__payments__amount_paid",
                filter=Q(student__payments__is_voided=False, student__payments__term=F("term")),
            )
        )

    def _balance(self, obj):
        return (obj.total_expected or 0) - (obj._paid or 0)

    @display(description=_("Expected"), ordering="total_expected")
    def expected_display(self, obj):
        return rwf(obj.total_expected)

    @display(description=_("Paid"), ordering="_paid")
    def paid_display(self, obj):
        return rwf(obj._paid)

    @display(description=_("Balance"))
    def balance_display(self, obj):
        return rwf(abs(self._balance(obj)))

    @display(
        description=_("Status"),
        label={"Paid": "success", "Partial": "warning", "Unpaid": "danger", "Overpaid": "info"},
    )
    def status_badge(self, obj):
        balance = self._balance(obj)
        if balance < 0:
            return "Overpaid"
        if balance == 0:
            return "Paid"
        return "Partial" if (obj._paid or 0) > 0 else "Unpaid"

    # -- list actions -------------------------------------------------------

    @action(
        description=_("Generate fees for current term"),
        url_path="generate-fees",
        permissions=["generate_fees"],
        icon="auto_awesome",
        variant=ActionVariant.PRIMARY,
    )
    def generate_fees(self, request):
        """Create a StudentFee for every active enrollment in the current term using its class FeeStructure."""
        changelist = reverse("admin:core_studentfee_changelist")
        term = get_current_term()
        if not term:
            self.message_user(request, _("No current term is set."), messages.ERROR)
            return redirect(changelist)

        class_totals = {
            row["class_stream"]: row["total"]
            for row in FeeStructure.objects.filter(term=term).values("class_stream").annotate(total=Sum("amount"))
        }
        already_assigned = set(StudentFee.objects.filter(term=term).values_list("student_id", flat=True))

        new_fees, skipped, seen = [], 0, set()
        for enrollment in StudentEnrollment.objects.filter(term=term, status="Active"):
            student_id = enrollment.student_id
            if student_id in already_assigned or student_id in seen:
                continue
            seen.add(student_id)
            total = class_totals.get(enrollment.class_stream_id)
            if not total:
                skipped += 1
                continue
            new_fees.append(
                StudentFee(student_id=student_id, academic_year=term.academic_year, term=term, total_expected=total)
            )

        StudentFee.objects.bulk_create(new_fees, ignore_conflicts=True)
        self.message_user(
            request,
            _("%(created)d fee record(s) created for %(term)s. %(skipped)d student(s) skipped (no fee structure for their class).")
            % {"created": len(new_fees), "term": term, "skipped": skipped},
            messages.SUCCESS if new_fees else messages.WARNING,
        )
        return redirect(changelist)

    def has_generate_fees_permission(self, request, object_id=None):
        return request.user.has_perm("core.add_studentfee")

    @action(description=_("Record payment"), url_path="new-payment", icon="add_card")
    def new_payment(self, request):
        return redirect(reverse("record_payment"))

    @action(description=_("Debtors list"), url_path="debtors", icon="warning")
    def debtors(self, request):
        return redirect(reverse("debtors_list"))

    # -- row actions --------------------------------------------------------

    @action(description=_("Statement"), url_path="statement", icon="receipt_long")
    def view_statement(self, request, object_id):
        fee = get_object_or_404(StudentFee, pk=object_id)
        return redirect(reverse("student_financial_statement", args=[fee.student_id]))

    @action(description=_("Finances"), url_path="finances", icon="account_balance_wallet")
    def view_finances(self, request, object_id):
        fee = get_object_or_404(StudentFee, pk=object_id)
        return redirect(reverse("student_financial_profile", args=[fee.student_id]))


@admin.register(Payment)
class PaymentAdmin(BaseAdmin):
    list_display = ("receipt_number", "student", "amount_display", "method_badge", "term", "date_paid", "received_by", "status_badge")
    list_display_links = ("receipt_number",)
    list_select_related = ("student", "term", "academic_year", "received_by")
    list_filter_submit = True
    list_filter = (
        "is_voided",
        ("payment_method", ChoicesDropdownFilter),
        ("academic_year", RelatedDropdownFilter),
        ("term", RelatedDropdownFilter),
        ("date_paid", RangeDateTimeFilter),
        ("amount_paid", RangeNumericFilter),
    )
    search_fields = (
        "receipt_number",
        "reference_number",
        "student__first_name",
        "student__last_name",
        "student__registration_number",
    )
    date_hierarchy = "date_paid"
    ordering = ("-date_paid",)
    autocomplete_fields = ("student",)

    fieldsets = (
        (_("Payment details"), {"fields": ("student", ("academic_year", "term"), "amount_paid", ("payment_method", "reference_number"))}),
        (_("Receipt"), {"fields": ("receipt_number", "received_by", "date_paid", "notes")}),
        (_("Void audit trail"), {"fields": ("is_voided", "void_reason", "voided_at", "voided_by"), "classes": ["collapse"]}),
    )

    actions_list = ["record_payment", "daily_report"]
    actions_row = ["print_receipt", "view_statement", "void_payment"]
    actions_detail = ["print_receipt", "view_statement", "void_payment"]

    # -- data protection ----------------------------------------------------

    def get_readonly_fields(self, request, obj=None):
        always = ("receipt_number", "received_by", "date_paid", "is_voided", "void_reason", "voided_at", "voided_by")
        if obj:  # once recorded, money fields are frozen - void and re-enter instead
            return always + ("student", "academic_year", "term", "amount_paid", "payment_method", "reference_number", "notes")
        return always

    def has_delete_permission(self, request, obj=None):
        # Payments are voided, never deleted (keeps the audit trail intact)
        return False

    def has_add_permission(self, request):
        # Collection must pass school authorization, bill locking and replay checks.
        return False

    def save_model(self, request, obj, form, change):
        if not change and not obj.received_by_id:
            obj.received_by = request.user
        super().save_model(request, obj, form, change)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        term = get_current_term()
        if term:
            initial.setdefault("term", term.pk)
            initial.setdefault("academic_year", term.academic_year_id)
        return initial

    # -- columns ------------------------------------------------------------

    @display(description=_("Amount"), ordering="amount_paid")
    def amount_display(self, obj):
        return rwf(obj.amount_paid)

    @display(
        description=_("Method"),
        ordering="payment_method",
        label={"Cash": "success", "Mobile Money": "warning", "Bank Deposit": "info", "Check": "primary"},
    )
    def method_badge(self, obj):
        return obj.payment_method

    @display(description=_("Status"), ordering="is_voided", label={"Valid": "success", "Voided": "danger"})
    def status_badge(self, obj):
        return "Voided" if obj.is_voided else "Valid"

    # -- actions ------------------------------------------------------------

    @action(description=_("Record payment"), url_path="record-payment", icon="add_card", variant=ActionVariant.PRIMARY)
    def record_payment(self, request):
        return redirect(reverse("record_payment"))

    @action(description=_("Daily collections"), url_path="daily-report", icon="bar_chart")
    def daily_report(self, request):
        return redirect(reverse("daily_collection_report"))

    @action(description=_("Receipt"), url_path="receipt", icon="print")
    def print_receipt(self, request, object_id):
        return redirect(reverse("payment_receipt", args=[object_id]))

    @action(description=_("Statement"), url_path="statement", icon="receipt_long")
    def view_statement(self, request, object_id):
        payment = get_object_or_404(Payment, pk=object_id)
        return redirect(reverse("student_financial_statement", args=[payment.student_id]))

    @action(description=_("Void"), url_path="void", permissions=["void"], icon="block", variant=ActionVariant.DANGER)
    def void_payment(self, request, object_id):
        payment = get_object_or_404(Payment, pk=object_id)
        if payment.is_voided:
            self.message_user(request, _("This payment has already been voided."), messages.WARNING)
            return redirect(reverse("admin:core_payment_changelist"))
        return redirect(reverse("void_payment", args=[object_id]))

    def has_void_permission(self, request, object_id=None):
        return request.user.has_perm("core.can_void_payment")