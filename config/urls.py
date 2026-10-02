from django.conf import settings
from django.views.static import serve
from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path
from django.contrib.auth import views as auth_views

from core import views
from core.views import student_finances_view


urlpatterns = [
    # ============================================================
    # ADMIN
    # ============================================================
    path('admin/', admin.site.urls),

    # ============================================================
    # AUTHENTICATION
    # ============================================================
    path(
        'login/',
        views.custom_login_view,
        name='login'
    ),

    path(
        'logout/',
        LogoutView.as_view(next_page='/login/'),
        name='logout'
    ),

    # ------------------------------------------------------------
    # Password Reset / Forgot Password
    # ------------------------------------------------------------
    path(
        'forgot-password/',
        auth_views.PasswordResetView.as_view(
            template_name='core/password_reset_form.html',
            email_template_name='core/password_reset_email.html',
            subject_template_name='core/password_reset_subject.txt',
            success_url='/forgot-password/sent/',
        ),
        name='password_reset',
    ),

    path(
        'forgot-password/sent/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='core/password_reset_done.html',
        ),
        name='password_reset_done',
    ),

    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='core/password_reset_confirm.html',
            success_url='/reset-password-complete/',
        ),
        name='password_reset_confirm',
    ),

    path(
        'reset-password-complete/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='core/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),

    # ============================================================
    # ROLE & DASHBOARD
    # ============================================================
    path(
        'dashboard/redirect/',
        views.role_based_redirect_view,
        name='role_redirect'
    ),

    path(
        'accountant/dashboard/',
        views.accountant_dashboard,
        name='accountant_dashboard'
    ),

    path(
        'teacher/dashboard/',
        views.teacher_dashboard,
        name='teacher_dashboard'
    ),

    path(
        'teacher/grades/<int:assignment_id>/',
        views.input_grades_view,
        name='input_grades'
    ),

    path(
        'teacher/class/<int:assignment_id>/students/',
        views.class_students_view,
        name='class_students'
    ),

    path(
        'teacher/class/<int:assignment_id>/attendance/',
        views.take_attendance_view,
        name='take_attendance'
    ),

    path(
        'teacher/student/<int:student_id>/profile/',
        views.student_academic_profile_view,
        name='student_academic_profile'
    ),

    # ============================================================
    # ATTENDANCE
    # ============================================================
    path(
        'school-admin/attendance/report/',
        views.admin_attendance_report_view,
        name='admin_attendance_report'
    ),

    path(
        'school-admin/subject-attendance/report/',
        views.admin_subject_attendance_report_view,
        name='admin_subject_attendance_report'
    ),

    path(
        'attendance/daily/',
        views.take_daily_attendance,
        name='take_daily_attendance'
    ),

    path(
        'attendance/daily/<int:class_id>/',
        views.take_daily_attendance,
        name='take_daily_attendance_class'
    ),

    # ============================================================
    # STUDENT PORTAL
    # ============================================================
    path(
        'student/dashboard/',
        views.student_dashboard,
        name='student_dashboard'
    ),

    path(
        'student/change-password/',
        views.StudentPasswordChangeView.as_view(),
        name='change_password'
    ),

    path(
        'teacher/change-password/',
        views.TeacherPasswordChangeView.as_view(),
        name='teacher_change_password'
    ),

    path(
        'student/homework/',
        views.student_homework_view,
        name='student_homework'
    ),

    path(
        'student/grades/',
        views.student_grades,
        name='student_grades'
    ),

    path(
        'student/attendance/',
        views.student_attendance_view,
        name='student_attendance'
    ),

    path(
        'student/report-card/download/',
        views.generate_student_report_card,
        name='student_report_card'
    ),

    path(
        'finances/',
        views.student_finances_view,
        name='student_finances'
    ),

    # ============================================================
    # TEACHER PORTAL
    # ============================================================
    path(
        'teacher/assignment/<int:assignment_id>/homework/',
        views.teacher_homework_view,
        name='teacher_homework'
    ),

    path(
        'teacher/classes/',
        views.teacher_classes_view,
        name='teacher_classes'
    ),

    path(
        'teacher/schedule/',
        views.teacher_schedule_view,
        name='teacher_schedule'
    ),

    path(
        'teacher/notices/',
        views.teacher_notices_view,
        name='teacher_notices'
    ),

    path(
        'teacher/grades/',
        views.teacher_grades_list_view,
        name='teacher_grades_list'
    ),

    path(
        'teacher/homework/',
        views.teacher_homework_list_view,
        name='teacher_homework_list'
    ),

    path(
        'teacher/assignment/<int:assignment_id>/grades/input/',
        views.teacher_enter_grades_view,
        name='teacher_enter_grades'
    ),

    path(
        'teacher/assignment/<int:assignment_id>/homework/manage/',
        views.teacher_homework_manage_view,
        name='teacher_homework_manage'
    ),

    # ============================================================
    # ACCOUNTANT
    # ============================================================
    path(
        'accountant/record-payment/',
        views.record_payment,
        name='record_payment'
    ),

    path(
        'accountant/debtors/',
        views.debtors_list,
        name='debtors_list'
    ),

    path(
        'accountant/receipt/<int:payment_id>/',
        views.payment_receipt,
        name='payment_receipt'
    ),

    path(
        'accountant/collections/daily/',
        views.daily_collections,
        name='daily_collections'
    ),

    path(
        'accountant/payment/<int:payment_id>/void/',
        views.void_payment_view,
        name='void_payment'
    ),

    path(
        'accountant/student/<int:student_id>/statement/',
        views.student_financial_statement,
        name='student_financial_statement'
    ),

    path(
        'accountant/reports/daily/',
        views.daily_collection_report,
        name='daily_collection_report'
    ),

    path(
        'accountant/reports/class-collections/',
        views.class_collections_report,
        name='class_collections_report'
    ),

    path(
        'accountant/reports/class-collections/<int:class_id>/',
        views.class_collection_detail,
        name='class_collection_detail'
    ),

    path(
        'accountant/student/<int:student_id>/profile/',
        views.accountant_student_profile,
        name='accountant_student_profile'
    ),

    path(
        'accountant/student/<int:student_id>/financial/',
        views.student_financial_profile,
        name='student_financial_profile'
    ),

    # ============================================================
    # STUDENT SEARCH
    # ============================================================
    path(
        'students/search/',
        views.student_search,
        name='student_search'
    ),
]


# ================================================================
# MEDIA FILES
# ================================================================
# Serve uploaded media files during development
urlpatterns += [
    path(
        'media/<path:path>',
        serve,
        {'document_root': settings.MEDIA_ROOT}
    ),
]