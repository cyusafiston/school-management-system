from core.views import generate_student_report_card as report_card_pdf_view

"""
URL configuration for the School Management System.

SAAS TRANSITION - TEMPORARY SECURITY CONFIGURATION

Enabled:
- Platform superuser administration
- Authentication and password recovery
- Role-based login redirect
- Membership-protected school landing page

Legacy school-management routes are temporarily disabled until
school-level authorization and database isolation are implemented.
"""

from django.contrib import admin

# Platform Admin is reserved for active platform superusers.
# School administrators use their school dashboards instead.
def platform_admin_has_permission(request):
    user = request.user
    return bool(
        user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.is_superuser
    )


admin.site.has_permission = platform_admin_has_permission

from django.contrib.auth import views as auth_views
from django.contrib.auth.views import LogoutView
from django.urls import path

from core import views
from tenants.platform_admin import configure_platform_admin
from tenants.views import school_home, register_school, academic_setup


# Restrict the existing Django admin to platform superusers.
configure_platform_admin()


urlpatterns = [
    path(
        "student/report-card/download/",
        report_card_pdf_view,
        name="student_report_card",
    ),


    # SECURED SCHOOL TEACHER DASHBOARD
    path(
        "school/teacher/dashboard/",
        views.teacher_dashboard,
        name="teacher_dashboard",
    ),

    path(
        "school/teacher/classes/",
        views.teacher_classes_view,
        name="teacher_classes",
    ),

    path(
        "school/teacher/classes/<int:assignment_id>/students/",
        views.class_students_view,
        name="class_students",
    ),


    # SECURED TEACHER SUBJECT ATTENDANCE
    path(
        "school/teacher/classes/<int:assignment_id>/attendance/",
        views.take_attendance_view,
        name="take_attendance",
    ),


    # SECURED TEACHER DAILY ATTENDANCE
    path(
        "school/teacher/attendance/daily/",
        views.take_daily_attendance,
        name="take_daily_attendance",
    ),
    path(
        "school/teacher/attendance/daily/<int:class_id>/",
        views.take_daily_attendance,
        name="take_daily_attendance_class",
    ),

    # SECURED TEACHER GRADE ENTRY
    path(
        "school/teacher/classes/<int:assignment_id>/grades/",
        views.input_grades_view,
        name="input_grades",
    ),

    path(
        "school/teacher/classes/<int:assignment_id>/grades/<int:grade_id>/finalize/",
        views.finalize_grade_view,
        name="finalize_grade",
    ),


    # ============================================================
    # PLATFORM ADMINISTRATION
    # ============================================================
    path(
        "admin/",
        admin.site.urls,
    ),

    # ============================================================
    # AUTHENTICATION
    # ============================================================
    # Public school application
    path(
        "register-school/",
        register_school,
        name="register_school",
    ),


    path(
        "login/",
        views.custom_login_view,
        name="login",
    ),

    path(
        "logout/",
        LogoutView.as_view(next_page="/login/"),
        name="logout",
    ),

    # ============================================================
    # PASSWORD RESET / FORGOT PASSWORD
    # ============================================================
    path(
        "forgot-password/",
        auth_views.PasswordResetView.as_view(
            template_name="core/password_reset_form.html",
            email_template_name="core/password_reset_email.html",
            subject_template_name="core/password_reset_subject.txt",
            success_url="/forgot-password/sent/",
        ),
        name="password_reset",
    ),

    path(
        "forgot-password/sent/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="core/password_reset_done.html",
        ),
        name="password_reset_done",
    ),

    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="core/password_reset_confirm.html",
            success_url="/reset-password-complete/",
        ),
        name="password_reset_confirm",
    ),

    path(
        "reset-password-complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="core/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),

    # ============================================================
    # ROLE-BASED REDIRECT
    # ============================================================
    path(
        "dashboard/redirect/",
        views.role_based_redirect_view,
        name="role_redirect",
    ),

    path(
        "school/academic-setup/",
        academic_setup,
        name="academic_setup",
    ),

    # ============================================================
    # SCHOOL PORTAL - TENANT PROTECTED
    # ============================================================
    path(
        "school/",
        school_home,
        name="school_home",
    ),
    path(
        "school/curriculum/",
        __import__(
            "tenants.views",
            fromlist=["curriculum_management"]
        ).curriculum_management,
        name="curriculum_management",
    ),
    # ============================================================
# SCHOOL FINANCE - TENANT-PROTECTED PAYMENT WORKFLOW
# ============================================================

    path(
        "school/finance/reports/daily/",
        views.daily_collection_report,
        name="daily_collection_report",
    ),

    path(
        "school/finance/debtors/",
        views.debtors_list,
        name="debtors_list",
    ),
path(
    "school/finance/configuration/",
    views.fee_configuration,
    name="fee_configuration",
),

path(
    "school/finance/dashboard/",
    views.accountant_dashboard,
    name="accountant_dashboard",
),

path(
    "school/finance/students/search/",
    views.student_search,
    name="student_search",
),

path(
    "school/finance/students/<int:student_id>/profile/",
    views.student_financial_profile,
    name="student_financial_profile",
),



path(
    "school/finance/payments/new/",
    views.record_payment,
    name="record_payment",
),

path(
    "school/finance/payments/<int:payment_id>/receipt/",
    views.payment_receipt,
    name="payment_receipt",
),

path(
    "school/finance/payments/<int:payment_id>/void/",
    views.void_payment_view,
    name="void_payment",
),


    path(
        "school/finance/reports/classes/",
        views.class_collections_report,
        name="class_collections_report",
    ),
    path(
        "school/finance/reports/classes/<int:class_id>/",
        views.class_collection_detail,
        name="class_collection_detail",
    ),
    path(
        "school/curriculum/remove/<int:assignment_id>/",
        __import__(
            "tenants.views",
            fromlist=["remove_curriculum_assignment"]
        ).remove_curriculum_assignment,
        name="remove_curriculum_assignment",
    ),
    path(
        "school/curriculum/edit/<int:assignment_id>/",
        __import__(
            "tenants.views",
            fromlist=["edit_curriculum_requirement"]
        ).edit_curriculum_requirement,
        name="edit_curriculum_requirement",
    ),

    path(
        "school/attendance/reports/daily/",
        views.admin_attendance_report_view,
        name="admin_attendance_report",
    ),
    path(
        "school/attendance/reports/subjects/",
        views.admin_subject_attendance_report_view,
        name="admin_subject_attendance_report",
    ),
]


# ================================================================
# TEMPORARILY DISABLED LEGACY ROUTES
# ================================================================
#
# Teacher dashboard and management
# Student dashboard and academic records
# Accountant dashboard and payments
# Financial reports and receipts
# Student search and profiles
# Attendance and grades
# Homework and notices
#
# These routes will be restored individually after implementing:
#
# 1. Approved school membership verification
# 2. School-specific role permissions
# 3. School-filtered database queries
# 4. Cross-school object access protection
# 5. Automated tenant-isolation security tests
#
# IMPORTANT:
# Do not restore these routes until their views are tenant-safe.
#
# Uploaded media is also not served through an unrestricted
# development URL here. Private files will require access controls.
# ================================================================


# STEP 887 - SCHOOL TEACHER MANAGEMENT
from tenants.views import teacher_management

urlpatterns.insert(
    0,
    path(
        "school/teachers/",
        teacher_management,
        name="teacher_management",
    ),
)


# STEP 909 - SCHOOL TEACHER ASSIGNMENT MANAGEMENT
from tenants.views import teacher_assignment_management

urlpatterns.insert(
    0,
    path(
        "school/teachers/assignments/",
        teacher_assignment_management,
        name="teacher_assignment_management",
    ),
)
