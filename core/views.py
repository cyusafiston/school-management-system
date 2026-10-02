from decimal import Decimal, InvalidOperation
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
    """Only return an assignment belonging to the logged-in teacher."""
    if not is_teacher(request.user):
        return None

    return get_object_or_404(
        TeacherAssignment.objects.select_related(
            "current_class", "subject", "term", "teacher"
        ),
        id=assignment_id,
        teacher=request.user,
    )


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
            print("LOGIN FORM ERRORS:", form.errors)
    else:
        form = AuthenticationForm()

    return render(request, 'core/login.html', {'form': form})


def redirect_based_on_role(request):
    user = request.user

    if not user.is_authenticated:
        return redirect("login")

    role = get_user_role(user)

    if is_accountant(user):
        return redirect("accountant_dashboard")

    if role == ROLE_TEACHER:
        return redirect("teacher_dashboard")

    if role == ROLE_STUDENT:
        return redirect("student_dashboard")

    if is_admin(user):
        return redirect("admin:index")

    logout(request)
    messages.error(request, "Your account lacks a valid role configuration.")
    return redirect("login")


@login_required
def role_based_redirect_view(request):
    return redirect_based_on_role(request)


@login_required
def teacher_dashboard(request):
    if is_teacher(request.user):
        current_term = Term.objects.filter(is_current=True).first()

        assignments = TeacherAssignment.objects.filter(teacher=request.user)
        if current_term:
            term_assignments = assignments.filter(term=current_term)
        else:
            term_assignments = assignments

        context = {
            'assignments': term_assignments,
            'current_term': current_term,
        }
        return render(request, 'core/teacher_dashboard.html', context)
    else:
        messages.error(request, "Access denied. This page is for teachers only.")
        return redirect('/login/')


@login_required
def teacher_classes_view(request):
    if not is_teacher(request.user):
        messages.error(request, "Access denied. This page is for teachers only.")
        return redirect('/login/')

    current_term = Term.objects.filter(is_current=True).first()
    assignments = TeacherAssignment.objects.filter(teacher=request.user)
    if current_term:
        assignments = assignments.filter(term=current_term)

    context = {
        'assignments': assignments,
    }
    return render(request, 'core/teacher_classes.html', context)


@login_required
def input_grades_view(request, assignment_id):
    if not is_teacher(request.user):
        messages.error(request, "Access denied.")
        return redirect('/login/')

    assignment = teacher_assignment_for_user(request, assignment_id)
    if assignment is None:
        return deny_and_redirect(
            request,
            "Access denied. This assignment does not belong to you.",
        )

    class_stream = assignment.current_class
    subject = assignment.subject
    term = assignment.term

    students = StudentProfile.objects.filter(current_class=class_stream).order_by('id')

    if request.method == 'POST':
        for student in students:
            cat_key = f'cat_{student.id}'
            exam_key = f'exam_{student.id}'

            if cat_key in request.POST and exam_key in request.POST:
                try:
                    cat_val = Decimal(request.POST.get(cat_key) or '0.00')
                    exam_val = Decimal(request.POST.get(exam_key) or '0.00')

                    grade_obj, created = Grade.objects.get_or_create(
                        student=student,
                        subject=subject,
                        term=term,
                        defaults={'cat_marks': cat_val, 'exam_marks': exam_val}
                    )

                    if not created:
                        grade_obj.cat_marks = cat_val
                        grade_obj.exam_marks = exam_val
                    
                    grade_obj.save() # Triggers calculations & full_clean

                except (InvalidOperation, ValueError, TypeError):
                    messages.error(
                        request,
                        f"Invalid marks entered for student {student.id}.",
                    )
                    continue

        messages.success(request, f"Grades for {class_stream.name} - {subject.name} saved successfully!")
        return redirect('teacher_dashboard')

    # Attach the specific grade object directly to each student for clean template rendering
    grades_map = {g.student_id: g for g in Grade.objects.filter(subject=subject, term=term, student__in=students)}
    for student in students:
        student.grade = grades_map.get(student.id)

    context = {
        'assignment': assignment,
        'students': students,
    }
    return render(request, 'core/input_grades.html', context)


@login_required
def class_students_view(request, assignment_id):
    if not is_teacher(request.user):
        messages.error(request, "Access denied.")
        return redirect('/login/')

    assignment = teacher_assignment_for_user(request, assignment_id)
    if assignment is None:
        return deny_and_redirect(
            request,
            "Access denied. This assignment does not belong to you.",
        )
    class_stream = assignment.current_class
    subject = assignment.subject

    students = StudentProfile.objects.filter(current_class=class_stream).order_by('id')
    
    student_data = []
    for student in students:
        grade = Grade.objects.filter(
            student=student,
            subject=subject,
            term=assignment.term
        ).first()
        
        attendance_records = Attendance.objects.filter(student=student)
        present_count = attendance_records.filter(status='Present').count()
        absent_count = attendance_records.filter(status='Absent').count()
        late_count = attendance_records.filter(status='Late').count()
        
        student_data.append({
            'student': student,
            'grade': grade,
            'present': present_count,
            'absent': absent_count,
            'late': late_count,
        })

    context = {
        'assignment': assignment,
        'class_stream': class_stream,
        'subject': subject,
        'student_data': student_data,
    }
    return render(request, 'core/class_students.html', context)


@login_required
def take_attendance_view(request, assignment_id):
    if not is_teacher(request.user):
        messages.error(request, "Access denied.")
        return redirect('/login/')

    assignment = teacher_assignment_for_user(request, assignment_id)
    if assignment is None:
        return deny_and_redirect(
            request,
            "Access denied. This assignment does not belong to you.",
        )
    class_stream = assignment.current_class
    students = StudentProfile.objects.filter(current_class=class_stream).order_by('id')

    attendance_date = request.GET.get('date', str(date.today()))

    if request.method == 'POST':
        attendance_date = request.POST.get('attendance_date', date.today())
        for student in students:
            status_key = f'status_{student.id}'
            status_val = request.POST.get(status_key, 'Present')

            Attendance.objects.update_or_create(
                student=student,
                assignment=assignment,
                date=attendance_date,
                defaults={
                    'status': status_val,
                    'recorded_by': request.user
                }
            )
        messages.success(request, f"Attendance for {attendance_date} saved successfully!")
        return redirect('class_students', assignment_id=assignment.id)

    existing_attendance = {
        a.student_id: a.status 
        for a in Attendance.objects.filter(assignment=assignment, date=attendance_date)
    }

    student_data = []
    for student in students:
        student_data.append({
            'student': student,
            'status': existing_attendance.get(student.id, 'Present')
        })

    context = {
        'assignment': assignment,
        'student_data': student_data,
        'attendance_date': attendance_date,
    }
    return render(request, 'core/take_attendance.html', context)


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
    if not is_admin(request.user):
        messages.error(request, "Access denied. Admins only.")
        return redirect('/login/')

    selected_date_str = request.GET.get('date', str(date.today()))
    try:
        parsed_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except ValueError:
        parsed_date = date.today()
        selected_date_str = str(parsed_date)

    day = parsed_date.day
    suffix = 'th' if 11 <= day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    formatted_date_display = parsed_date.strftime(f'%B {day}{suffix}, %Y')

    class_id = request.GET.get('class_id', '')
    classes = ClassStream.objects.all()

    total_school_students = StudentProfile.objects.count()
    school_attendance_qs = DailyClassAttendance.objects.filter(date=parsed_date)
    total_records = school_attendance_qs.count()
    present_count = school_attendance_qs.filter(status='Present').count()
    late_count = school_attendance_qs.filter(status='Late').count()
    absent_count = school_attendance_qs.filter(status='Absent').count()

    class_summaries = []
    for class_obj in classes:
        total_class_students = StudentProfile.objects.filter(current_class=class_obj).count()
        
        class_records = school_attendance_qs.filter(current_class=class_obj)
        present = class_records.filter(status='Present').count()
        late = class_records.filter(status='Late').count()
        absent = class_records.filter(status='Absent').count()
        
        is_submitted = class_records.exists()
        first_record = class_records.first()
        submitted_by = first_record.submitted_by.username if is_submitted and first_record.submitted_by else None

        class_summaries.append({
            'class_obj': class_obj,
            'total_students': total_class_students,
            'present_count': present,
            'late_count': late,
            'absent_count': absent,
            'is_submitted': is_submitted,
            'submitted_by': submitted_by,
        })

    attendance_qs = school_attendance_qs.select_related('student', 'current_class', 'submitted_by')
    if class_id:
        attendance_qs = attendance_qs.filter(current_class_id=class_id)

    context = {
        'formatted_date_display': formatted_date_display,
        'class_summaries': class_summaries,
        'attendance_records': attendance_qs,
        'selected_date': selected_date_str,
        'selected_class_id': class_id,
        'classes': classes,
        'total_school_students': total_school_students,
        'total_records': total_records,
        'present_count': present_count,
        'late_count': late_count,
        'absent_count': absent_count,
    }
    return render(request, 'core/admin_attendance_report.html', context)


@login_required
def admin_subject_attendance_report_view(request):
    if not is_admin(request.user):
        messages.error(request, "Access denied. Admins only.")
        return redirect('/login/')

    selected_date = request.GET.get('date', str(date.today()))
    class_id = request.GET.get('class_id', '')

    attendance_qs = Attendance.objects.filter(date=selected_date).select_related('student', 'assignment__current_class', 'assignment__subject', 'recorded_by')

    if class_id:
        attendance_qs = attendance_qs.filter(assignment__current_class_id=class_id)

    context = {
        'attendance_records': attendance_qs,
        'selected_date': selected_date,
        'selected_class_id': class_id,
        'classes': ClassStream.objects.all(),
        'total_records': attendance_qs.count(),
        'present_count': attendance_qs.filter(status='Present').count(),
        'late_count': attendance_qs.filter(status='Late').count(),
        'absent_count': attendance_qs.filter(status='Absent').count(),
    }
    return render(request, 'core/admin_subject_attendance_report.html', context)


@login_required
def take_daily_attendance(request, class_id=None):
    user_profile = getattr(request.user, 'profile', None)
    if not user_profile or user_profile.role.lower() != 'teacher':
        messages.error(request, "Access denied. Only teachers can take and submit daily attendance.")
        return redirect('role_redirect')

    classes = ClassStream.objects.all()
    selected_class = None
    students = []
    already_submitted = False
    current_date = date.today()

    if class_id:
        selected_class = get_object_or_404(ClassStream, id=class_id)

        if not teacher_can_access_class(request.user, selected_class):
            return deny_and_redirect(
                request,
                "Access denied. You are not assigned to this class.",
            )

        students = StudentProfile.objects.filter(
            current_class=selected_class
        ).order_by("id")

        already_submitted = DailyClassAttendance.objects.filter(
            current_class=selected_class,
            date=current_date
        ).exists()

        if request.method == 'POST' and not already_submitted:
            valid_statuses = ['Present', 'Late', 'Absent']
            attendance_data_to_create = []
            has_error = False

            for student in students:
                status_val = request.POST.get(f'status_{student.id}')
                if status_val not in valid_statuses:
                    has_error = True
                    break
                attendance_data_to_create.append(
                    DailyClassAttendance(
                        student=student,
                        current_class=selected_class,
                        status=status_val,
                        submitted_by=request.user,
                        is_locked=True
                    )
                )

            if has_error or len(attendance_data_to_create) != students.count():
                messages.error(request, "Submission failed: Every student must have a valid attendance status assigned.")
            else:
                DailyClassAttendance.objects.bulk_create(attendance_data_to_create)
                messages.success(request, f"Attendance for {selected_class.name} submitted and locked successfully!")
                return redirect('take_daily_attendance_class', class_id=selected_class.id)

    context = {
        'classes': classes,
        'selected_class': selected_class,
        'students': students,
        'already_submitted': already_submitted,
        'today': current_date,
    }
    return render(request, 'core/take_daily_attendance.html', context)


@login_required
def teacher_homework_view(request, assignment_id):
    if not is_teacher(request.user):
        return deny_and_redirect(request, "Access denied. Teachers only.")

    assignment = teacher_assignment_for_user(request, assignment_id)
    if assignment is None:
        return deny_and_redirect(
            request,
            "Access denied. This assignment does not belong to you.",
        )
    homeworks = assignment.homeworks.all().order_by('-created_at')
    
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        due_date = request.POST.get('due_date')
        file = request.FILES.get('file')
        
        if title and description and due_date:
            Homework.objects.create(
                assignment=assignment,
                title=title,
                description=description,
                due_date=due_date,
                file=file
            )
            messages.success(request, "Homework posted successfully!")
            return redirect('teacher_homework', assignment_id=assignment.id)
            
    context = {
        'assignment': assignment,
        'homeworks': homeworks,
    }
    return render(request, 'core/teacher_homework.html', context)


@login_required
def student_dashboard(request):
    student_profile = get_object_or_404(StudentProfile, user=request.user)
    
    class_stream = student_profile.current_class
    
    # --- Homework Logic ---
    homeworks = Homework.objects.all().order_by('-created_at')
    if class_stream:
        try:
            homeworks = Homework.objects.filter(assignment__class_stream=class_stream).order_by('-created_at')
        except Exception:
            try:
                homeworks = Homework.objects.filter(class_stream=class_stream).order_by('-created_at')
            except Exception:
                try:
                    homeworks = Homework.objects.filter(assignment__teacher_assignment__student_class=class_stream).order_by('-created_at')
                except Exception:
                    pass

    homework_count = homeworks.count()
    recent_homeworks = homeworks[:5]

    # --- Notices Logic ---
    today = timezone.now().date()
    if class_stream:
        notices = Notice.objects.filter(
            Q(expires_at__gte=today) | Q(expires_at__isnull=True)
        ).filter(
            Q(target_class__isnull=True) | Q(target_class=class_stream)
        )
    else:
        notices = Notice.objects.filter(
            Q(expires_at__gte=today) | Q(expires_at__isnull=True),
            target_class__isnull=True
        )
        
    notice_count = notices.count()
    recent_notices = notices.order_by('-created_at')[:3]

    # --- Attendance Logic ---
    attendance_records = Attendance.objects.filter(student=student_profile)
    total_classes = attendance_records.count()
    present_count = attendance_records.filter(status='Present').count()
    late_count = attendance_records.filter(status='Late').count()

    attendance_percentage = 0
    if total_classes > 0:
        attendance_percentage = round(((present_count + late_count) / total_classes) * 100, 1)

    if total_classes == 0:
        attendance_status = "No Records"
        status_color = "text-gray-600"
        bg_color = "bg-gray-50 text-gray-600"
        icon_class = "fa-info-circle"
    elif attendance_percentage >= 85:
        attendance_status = "Normal"
        status_color = "text-green-600"
        bg_color = "bg-green-50 text-green-600"
        icon_class = "fa-check-circle"
    elif attendance_percentage >= 70:
        attendance_status = "Warning"
        status_color = "text-yellow-600"
        bg_color = "bg-yellow-50 text-yellow-600"
        icon_class = "fa-exclamation-triangle"
    else:
        attendance_status = "Critical"
        status_color = "text-red-600"
        bg_color = "bg-red-50 text-red-600"
        icon_class = "fa-times-circle"

    # --- Academic Grades Logic (Added for Report Card Integration) ---
    term_param = request.GET.get('term', '1')
    grades_qs = Grade.objects.filter(student=student_profile)
    
    target_term_names = ['Term 1']
    if term_param == '2':
        target_term_names = ['Term 1', 'Term 2']
    elif term_param == '3':
        target_term_names = ['Term 1', 'Term 2', 'Term 3']
        
    filtered_grades = grades_qs.filter(term__name__in=target_term_names)

    subject_summary = {}
    for g in filtered_grades:
        subj_name = g.subject.name
        term_num = 1
        if g.term and 'Term 2' in str(g.term.name): term_num = 2
        elif g.term and 'Term 3' in str(g.term.name): term_num = 3

        max_cat = getattr(g.subject, 'max_cat_marks', Decimal('50.00')) or Decimal('50.00')
        max_exam = getattr(g.subject, 'max_exam_marks', Decimal('50.00')) or Decimal('50.00')
        max_total = max_cat + max_exam

        if subj_name not in subject_summary:
            subject_summary[subj_name] = {'subject': g.subject, 'terms': {}}
            
        subject_summary[subj_name]['terms'][term_num] = {
            'cat_marks': g.cat_marks,
            'max_cat': max_cat,
            'exam_marks': g.exam_marks,
            'max_exam': max_exam,
            'marks_obtained': g.marks_obtained,
            'max_marks': max_total,
            'percentage': g.percentage,
        }

    table_rows = []
    total_percentage_sum = Decimal('0.00')
    count_subjects = 0

    for subj_name, data in subject_summary.items():
        term_percentages = [t_data['percentage'] for t_data in data['terms'].values() if t_data['percentage'] is not None]
        final_pct = sum(term_percentages, Decimal('0.00')) / len(term_percentages) if term_percentages else Decimal('0.00')
        
        total_percentage_sum += final_pct
        count_subjects += 1
        
        grade_ltr = 'F'
        rem = 'Fail'
        if final_pct >= 80: grade_ltr, rem = 'A', 'Excellent'
        elif final_pct >= 70: grade_ltr, rem = 'B', 'Very Good'
        elif final_pct >= 60: grade_ltr, rem = 'C', 'Good'
        elif final_pct >= 50: grade_ltr, rem = 'D', 'Satisfactory'

        table_rows.append({
            'subject_name': subj_name,
            'terms': data['terms'],
            'final_percentage': round(final_pct, 1),
            'grade_letter': grade_ltr,
            'remarks': rem
        })

    average_percentage = round(total_percentage_sum / count_subjects if count_subjects > 0 else Decimal('0.00'), 1)

    context = {
        'student_profile': student_profile,
        'class_stream': class_stream,
        'homework_count': homework_count,
        'recent_homeworks': recent_homeworks,
        'notice_count': notice_count,
        'recent_notices': recent_notices,
        'attendance_status': attendance_status,
        'attendance_percentage': attendance_percentage,
        'status_color': status_color,
        'bg_color': bg_color,
        'icon_class': icon_class,
        'table_rows': table_rows,
        'average_percentage': average_percentage,
        'term_param': term_param,
    }
    return render(request, 'core/student_dashboard.html', context)


@login_required
def student_homework_view(request):
    if not is_student(request.user):
        messages.error(request, "Access denied. Student portal only.")
        return redirect('/login/')

    student_profile = get_object_or_404(StudentProfile, user=request.user)
    class_stream = student_profile.current_class
    
    homework_list = Homework.objects.filter(assignment__current_class=class_stream).order_by('-created_at')
    homework_count = homework_list.count()
    
    context = {
        'student_profile': student_profile,
        'homework_list': homework_list,
        'homework_count': homework_count,
    }
    return render(request, 'core/student_homework.html', context)


@login_required
def student_grades(request):
    if not is_student(request.user):
        messages.error(request, "Access denied. Student portal only.")
        return redirect('/login/')
        
    student_profile = get_object_or_404(StudentProfile, user=request.user)
    
    grades_list = Grade.objects.filter(student=student_profile, status='Finalized').select_related('subject', 'term')
    
    context = {
        'student_profile': student_profile,
        'grades_list': grades_list,
    }
    return render(request, 'core/student_grades.html', context)


@login_required
def student_attendance_view(request):
    student_profile = get_object_or_404(StudentProfile, user=request.user)
    
    try:
        year = int(request.GET.get('year', datetime.now().year))
        month = int(request.GET.get('month', datetime.now().month))
    except ValueError:
        year = datetime.now().year
        month = datetime.now().month

    subject_attendance = Attendance.objects.filter(student=student_profile).order_by('-date')
    sub_total = subject_attendance.count()
    sub_present = subject_attendance.filter(status='Present').count()
    sub_late = subject_attendance.filter(status='Late').count()
    sub_absent = subject_attendance.filter(status='Absent').count()
    sub_percentage = round(((sub_present + sub_late) / sub_total) * 100, 1) if sub_total > 0 else 0

    daily_attendance = DailyClassAttendance.objects.filter(student=student_profile).order_by('-date')
    daily_total = daily_attendance.count()
    daily_present = daily_attendance.filter(status='Present').count()
    daily_late = daily_attendance.filter(status='Late').count()
    daily_absent = daily_attendance.filter(status='Absent').count()
    daily_percentage = round(((daily_present + daily_late) / daily_total) * 100, 1) if daily_total > 0 else 0

    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdayscalendar(year, month)
    
    monthly_daily_records = daily_attendance.filter(date__year=year, date__month=month)
    attendance_map = {record.date.day: record.status for record in monthly_daily_records}

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    month_name = calendar.month_name[month]

    context = {
        'student_profile': student_profile,
        'subject_attendance': subject_attendance,
        'sub_total': sub_total, 'sub_present': sub_present, 'sub_late': sub_late, 'sub_absent': sub_absent, 'sub_percentage': sub_percentage,
        'daily_attendance': daily_attendance,
        'daily_total': daily_total, 'daily_present': daily_present, 'daily_late': daily_late, 'daily_absent': daily_absent, 'daily_percentage': daily_percentage,
        'month_days': month_days,
        'attendance_map': attendance_map,
        'current_year': year,
        'current_month': month,
        'month_name': month_name,
        'prev_month': prev_month, 'prev_year': prev_year,
        'next_month': next_month, 'next_year': next_year,
    }
    return render(request, 'core/student_attendance.html', context)


from django.template.loader import get_template
from xhtml2pdf import pisa

@login_required
def generate_student_report_card(request):
    if not is_student(request.user):
        return deny_and_redirect(request, "Access denied. Student portal only.")

    student = get_object_or_404(StudentProfile, user=request.user)
    
    term_param = request.GET.get('term', '1')
    scope = request.GET.get('scope', 'term')
    
    grades_qs = Grade.objects.filter(student=student)
    attendance_records = Attendance.objects.filter(student=student)
    
    if scope == 'annual' or term_param == '3':
        target_term_names = ['Term 1', 'Term 2', 'Term 3']
        report_title = "Annual Academic & Attendance Report"
        current_term_label = "Term 1, 2 & 3 (Annual)"
    elif term_param == '2':
        target_term_names = ['Term 1', 'Term 2']
        report_title = "Cumulative Term 2 Report"
        current_term_label = "Term 1 & 2 (Cumulative)"
    else:
        target_term_names = ['Term 1']
        report_title = "Term 1 Academic & Attendance Report"
        current_term_label = "Term 1"
        
    filtered_grades = grades_qs.filter(term__name__in=target_term_names)

    subject_summary = {}
    for g in filtered_grades:
        subj_name = g.subject.name
        term_num = 1
        if g.term and 'Term 2' in str(g.term.name): term_num = 2
        elif g.term and 'Term 3' in str(g.term.name): term_num = 3

        subject_max_cat = getattr(g.subject, 'max_cat_marks', Decimal('50.00')) or Decimal('50.00')
        subject_max_exam = getattr(g.subject, 'max_exam_marks', Decimal('50.00')) or Decimal('50.00')
        
        max_cat = subject_max_cat
        max_exam = subject_max_exam
        max_total = max_cat + max_exam

        if subj_name not in subject_summary:
            subject_summary[subj_name] = {
                'subject': g.subject,
                'terms': {},
            }
            
        subject_summary[subj_name]['terms'][term_num] = {
            'grade_obj': g,
            'cat_marks': g.cat_marks,
            'max_cat': max_cat,
            'exam_marks': g.exam_marks,
            'max_exam': max_exam,
            'marks_obtained': g.marks_obtained,
            'max_marks': max_total,
            'percentage': g.percentage,
        }

    table_rows = []
    total_percentage_sum = Decimal('0.00')
    count_subjects = 0

    for subj_name, data in subject_summary.items():
        term_percentages = [t_data['percentage'] for t_data in data['terms'].values() if t_data['percentage'] is not None]
        final_pct = sum(term_percentages, Decimal('0.00')) / len(term_percentages) if term_percentages else Decimal('0.00')
        
        total_percentage_sum += final_pct
        count_subjects += 1
        
        grade_ltr = 'F'
        rem = 'Fail'
        if final_pct >= 80: grade_ltr, rem = 'A', 'Excellent'
        elif final_pct >= 70: grade_ltr, rem = 'B', 'Very Good'
        elif final_pct >= 60: grade_ltr, rem = 'C', 'Good'
        elif final_pct >= 50: grade_ltr, rem = 'D', 'Satisfactory'

        table_rows.append({
            'subject_name': subj_name,
            'terms': data['terms'],
            'final_percentage': round(final_pct, 1),
            'grade_letter': grade_ltr,
            'remarks': rem
        })

    average_percentage = round(total_percentage_sum / count_subjects if count_subjects > 0 else Decimal('0.00'), 1)
    
    avg_grade_letter = 'F'
    if average_percentage >= 80: avg_grade_letter = 'A'
    elif average_percentage >= 70: avg_grade_letter = 'B'
    elif average_percentage >= 60: avg_grade_letter = 'C'
    elif average_percentage >= 50: avg_grade_letter = 'D'

    total_records = attendance_records.count()
    present_count = attendance_records.filter(status='Present').count()
    late_count = attendance_records.filter(status='Late').count()
    absent_count = attendance_records.filter(status='Absent').count()
    
    attendance_percentage = round((present_count / total_records * 100) if total_records > 0 else 0, 1)

    context = {
        'student_profile': student,
        'attendance_records': attendance_records,
        'grades': filtered_grades,
        'table_rows': table_rows,
        'average_percentage': average_percentage,
        'avg_grade_letter': avg_grade_letter,
        'attendance_percentage': attendance_percentage,
        'present_count': present_count,
        'late_count': late_count,
        'absent_count': absent_count,
        'total_records': total_records,
        'current_term': current_term_label,
        'report_title': report_title,
        'report_scope': scope,
        'term_param': term_param,
        'date_range': "August 2026 – December 2026",
        'issue_date': date.today().strftime("%B %d, %Y"),
    }

    template = get_template('core/report_card_pdf.html')
    html = template.render(context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Report_Card_{student.registration_number}_Term{term_param}.pdf"'
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Error generating PDF report', status=400)
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
    if not is_teacher(request.user):
        messages.error(request, "Access denied.")
        return redirect('/login/')

    assignment = teacher_assignment_for_user(request, assignment_id)
    if assignment is None:
        return deny_and_redirect(
            request,
            "Access denied. This assignment does not belong to you.",
        )

    class_stream = assignment.current_class
    subject = assignment.subject
    term = assignment.term

    students = StudentProfile.objects.filter(current_class=class_stream).order_by('id')

    if request.method == 'POST':
        for student in students:
            cat_key = f'cat_{student.id}'
            exam_key = f'exam_{student.id}'

            if cat_key in request.POST and exam_key in request.POST:
                try:
                    cat_val = Decimal(request.POST.get(cat_key) or '0.00')
                    exam_val = Decimal(request.POST.get(exam_key) or '0.00')

                    grade_obj, created = Grade.objects.get_or_create(
                        student=student,
                        subject=subject,
                        term=term,
                        defaults={'cat_marks': cat_val, 'exam_marks': exam_val}
                    )

                    if not created:
                        grade_obj.cat_marks = cat_val
                        grade_obj.exam_marks = exam_val
                    
                    grade_obj.save()

                except (InvalidOperation, ValueError, TypeError):
                    messages.error(
                        request,
                        f"Invalid marks entered for student {student.id}.",
                    )
                    continue

        messages.success(request, f"Grades for {class_stream.name} - {subject.name} saved successfully!")
        return redirect('teacher_dashboard')

    # Map grades directly to students so the template can use student.grade cleanly
    grades_map = {g.student_id: g for g in Grade.objects.filter(subject=subject, term=term, student__in=students)}
    for student in students:
        student.grade = grades_map.get(student.id)

    context = {
        'assignment': assignment,
        'students': students,
    }
    return render(request, 'core/teacher_enter_grades.html', context)


@login_required
def teacher_homework_manage_view(request, assignment_id):
    if not is_teacher(request.user):
        messages.error(request, "Access denied.")
        return redirect('/login/')

    assignment = teacher_assignment_for_user(request, assignment_id)
    if assignment is None:
        return deny_and_redirect(
            request,
            "Access denied. This assignment does not belong to you.",
        )
    homeworks = Homework.objects.filter(assignment=assignment)

    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        due_date = request.POST.get('due_date')
        file = request.FILES.get('file') # Capture uploaded file
        
        Homework.objects.create(
            assignment=assignment,
            title=title,
            description=description,
            due_date=due_date,
            file=file # Save file to model
        )
        messages.success(request, "Homework assigned successfully with attachment.")
        return redirect('teacher_homework_manage', assignment_id=assignment.id)

    context = {
        'assignment': assignment,
        'homeworks': homeworks,
    }
    return render(request, 'core/teacher_homework_manage.html', context)


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
@user_passes_test(
    is_accountant_or_admin,
    login_url="login",
)
def accountant_dashboard(request):
    total_students = StudentProfile.objects.count()

    current_term = (
        Term.objects
        .filter(is_current=True)
        .first()
    )

    # ---------------------------------------------------------
    # TOTAL EXPECTED FEES (Calculated dynamically per student class stream)
    # ---------------------------------------------------------
    total_expected_sum = None

    if current_term:
        total_expected_sum = (
            StudentFee.objects
            .filter(term=current_term)
            .aggregate(total=Sum("total_expected"))
            .get("total")
        )
    else:
        total_expected_sum = (
            StudentFee.objects
            .aggregate(total=Sum("total_expected"))
            .get("total")
        )

    # If no individual StudentFee records exist yet, compute dynamically by looping through students
    if total_expected_sum is None or total_expected_sum == Decimal("0.00"):
        computed_sum = Decimal("0.00")
        for student in StudentProfile.objects.all():
            if student.current_class:
                class_fees = (
                    FeeStructure.objects
                    .filter(term=current_term, class_stream=student.current_class)
                    if current_term else
                    FeeStructure.objects.filter(class_stream=student.current_class)
                ).aggregate(total=Sum("amount")).get("total") or Decimal("0.00")
                
                computed_sum += class_fees
        
        total_expected_sum = computed_sum

    # Fallback to general fee structures sum if still zero/none
    if total_expected_sum is None or total_expected_sum == Decimal("0.00"):
        if current_term:
            total_expected_sum = (
                FeeStructure.objects
                .filter(term=current_term)
                .aggregate(total=Sum("amount"))
                .get("total")
            )
        else:
            total_expected_sum = (
                FeeStructure.objects
                .aggregate(total=Sum("amount"))
                .get("total")
            )

    if total_expected_sum is None:
        total_expected_sum = Decimal("0.00")

    total_expected = Decimal(str(total_expected_sum))

    # ---------------------------------------------------------
    # TOTAL COLLECTED (Excluding voided payments)
    # ---------------------------------------------------------
    total_collected_sum = (
        Payment.objects
        .filter(is_voided=False)
        .aggregate(total=Sum("amount_paid"))
        .get("total")
    )

    if total_collected_sum is None:
        total_collected = Decimal("0.00")
    else:
        total_collected = Decimal(str(total_collected_sum))

    # ---------------------------------------------------------
    # TODAY'S COLLECTIONS & TRANSACTIONS (Excluding voided payments)
    # ---------------------------------------------------------
    today = timezone.now().date()
    today_payments = Payment.objects.filter(date_paid__date=today, is_voided=False)
    
    today_collections_sum = today_payments.aggregate(total=Sum("amount_paid")).get("total")
    today_collections = Decimal(str(today_collections_sum)) if today_collections_sum else Decimal("0.00")
    today_transactions = today_payments.count()

    # ---------------------------------------------------------
    # OUTSTANDING BALANCE
    # ---------------------------------------------------------
    outstanding_balance = total_expected - total_collected
    if outstanding_balance < Decimal("0.00"):
        outstanding_balance = Decimal("0.00")

    # ---------------------------------------------------------
    # TOTAL OVERPAID / ADVANCE BALANCE (Sum of excess student payments)
    # ---------------------------------------------------------
    total_overpaid = Decimal("0.00")
    for student in StudentProfile.objects.all():
        s_expected = Decimal("0.00")
        if current_term:
            s_fee_obj = StudentFee.objects.filter(student=student, term=current_term).first()
            if s_fee_obj:
                s_expected = s_fee_obj.total_expected
            elif student.current_class:
                s_expected = FeeStructure.objects.filter(term=current_term, class_stream=student.current_class).aggregate(total=Sum("amount")).get("total") or Decimal("0.00")
        else:
            s_fee_sum = StudentFee.objects.filter(student=student).aggregate(total=Sum("total_expected")).get("total")
            s_expected = s_fee_sum if s_fee_sum else Decimal("0.00")

        s_paid = Payment.objects.filter(student=student, is_voided=False).aggregate(total=Sum("amount_paid")).get("total") or Decimal("0.00")

        if s_paid > s_expected:
            total_overpaid += (s_paid - s_expected)

    # ---------------------------------------------------------
    # RECENT TRANSACTIONS FEED
    # ---------------------------------------------------------
    recent_payments = (
        Payment.objects
        .filter(is_voided=False)
        .select_related('student', 'received_by')
        .order_by('-date_paid', '-id')[:5]
    )

    # ---------------------------------------------------------
    # DASHBOARD CONTEXT
    # ---------------------------------------------------------
    context = {
        "total_expected": total_expected,
        "total_collected": total_collected,
        "outstanding_balance": outstanding_balance,
        "total_overpaid": total_overpaid,
        "today_collections": today_collections,
        "today_transactions": today_transactions,
        "total_students": total_students,
        "current_term": current_term,
        "recent_payments": recent_payments,
        "finance_ready": True,
        "finance_message": "Payment engine and fee structures are fully active.",
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
            'student',
            'academic_year',
            'term',
            'amount_paid',
            'payment_method',
            'reference_number',
            'notes',
        ]
        widgets = {
            'student': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500'}),
            'academic_year': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500'}),
            'term': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500'}),
            'amount_paid': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500', 'placeholder': 'Enter amount in RWF'}),
            'payment_method': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500'}),
            'reference_number': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500', 'placeholder': 'Optional (e.g., Bank Slip, MoMo code)'}),
            'notes': forms.Textarea(attrs={'class': 'w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500', 'rows': 3, 'placeholder': 'Optional remarks...'}),
        }

from django.db import transaction

@login_required
@user_passes_test(is_accountant_or_admin, login_url="login")
def record_payment(request):
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    payment = form.save(commit=False)
                    payment.received_by = request.user
                    payment.save()
                
                messages.success(request, f"Successfully recorded payment of {payment.amount_paid} RWF for {payment.student}.")
                return redirect('payment_receipt', payment_id=payment.id)
            except Exception as e:
                messages.error(request, f"An error occurred while saving the payment: {e}")
        else:
            # ---> ADD THIS LINE TO DEBUG <---
            print("FORM ERRORS:", form.errors)
    else:
        form = PaymentForm()

    context = {'form': form}
    return render(request, 'core/record_payment.html', context)
from decimal import Decimal
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum
from django.shortcuts import render
from .models import StudentEnrollment, Payment, StudentFee, FeeStructure, Term

@login_required
@user_passes_test(is_accountant_or_admin, login_url="login")
def debtors_list(request):
    """
    Displays a list of students with outstanding financial balances for the current term.
    """
    current_term = Term.objects.filter(is_current=True).first()
    
    enrollments = StudentEnrollment.objects.select_related('student', 'class_stream', 'academic_year', 'term')
    if current_term:
        enrollments = enrollments.filter(term=current_term)

    debtors_data = []
    for enrollment in enrollments:
        student = enrollment.student
        
        # Calculate expected fees for this student/term
        expected_sum = StudentFee.objects.filter(student=student, term=enrollment.term).aggregate(total=Sum('total_expected'))['total']
        if expected_sum is None:
            expected_sum = FeeStructure.objects.filter(class_stream=enrollment.class_stream, term=enrollment.term).aggregate(total=Sum('amount'))['total'] or Decimal("0.00")
        expected = Decimal(str(expected_sum))

        # Calculate total paid by this student for this term (excluding voided payments)
        paid_sum = Payment.objects.filter(student=student, term=enrollment.term, is_voided=False).aggregate(total=Sum('amount_paid'))['total']
        paid = Decimal(str(paid_sum)) if paid_sum is not None else Decimal("0.00")

        balance = expected - paid

        # Only include if they have an active outstanding balance
        if balance > 0:
            debtors_data.append({
                'student': student,
                'class': enrollment.class_stream,
                'expected': expected,
                'paid': paid,
                'balance': balance,
            })

    context = {
        'debtors': debtors_data,
        'current_term': current_term,
    }
    return render(request, 'core/debtors_list.html', context)
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test, permission_required
from django.contrib import messages
from django.utils import timezone
from .models import Payment, StudentEnrollment

@login_required
@user_passes_test(lambda u: u.is_authenticated, login_url="login") # Keep your custom accountant/admin check here
def payment_receipt(request, payment_id):
    """
    Displays a printable official payment receipt.
    """
    payment = get_object_or_404(Payment.objects.select_related('student', 'academic_year', 'term', 'received_by'), id=payment_id)
    
    # Get student's class stream for the term via enrollment
    enrollment = StudentEnrollment.objects.filter(student=payment.student, term=payment.term).select_related('class_stream').first()
    class_name = enrollment.class_stream.name if enrollment and enrollment.class_stream else "N/A"

    context = {
        'payment': payment,
        'class_name': class_name,
    }
    return render(request, 'core/payment_receipt.html', context)


@login_required
@permission_required('core.can_void_payment', raise_exception=True)
def void_payment_view(request, payment_id):
    """
    Handles the secure voiding/reversing of a payment with a mandatory audit trail.
    """
    payment = get_object_or_404(Payment, id=payment_id)
    
    if payment.is_voided:
        messages.error(request, "This payment has already been voided.")
        return redirect('accountant_dashboard')
        
    if request.method == 'POST':
        reason = request.POST.get('void_reason')
        if not reason:
            messages.error(request, "A reason is mandatory for voiding a payment.")
            return redirect('void_payment', payment_id=payment.id)
            
        # Mark as voided and record audit metadata
        payment.is_voided = True
        payment.void_reason = reason
        payment.voided_at = timezone.now()
        payment.voided_by = request.user
        payment.save()
        
        messages.success(request, f"Payment {payment.receipt_number} has been successfully voided.")
        return redirect('accountant_dashboard')
        
    return render(request, 'core/void_payment_confirm.html', {'payment': payment})
from decimal import Decimal
from django.db.models import Sum
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import StudentProfile, StudentEnrollment, StudentFee, FeeStructure, Payment, Term

@login_required
@user_passes_test(is_accountant_or_admin, login_url="login")
def student_financial_profile(request, student_id):
    """
    Displays the complete financial profile, fee summary, and transaction ledger for a specific student.
    """
    student = get_object_or_404(StudentProfile, id=student_id)
    current_term = Term.objects.filter(is_current=True).first()
    
    # Get latest enrollment to determine current class stream
    enrollment = StudentEnrollment.objects.filter(student=student).select_related('class_stream', 'academic_year', 'term').last()
    term_to_use = enrollment.term if enrollment else current_term
    
    # Calculate expected fees for the term
    expected_sum = None
    if term_to_use:
        expected_sum = StudentFee.objects.filter(student=student, term=term_to_use).aggregate(total=Sum('total_expected'))['total']
        if expected_sum is None and enrollment and enrollment.class_stream:
            expected_sum = FeeStructure.objects.filter(class_stream=enrollment.class_stream, term=term_to_use).aggregate(total=Sum('amount'))['total'] or Decimal("0.00")
    expected = Decimal(str(expected_sum or "0.00"))

    # Fetch all payment transactions for this student (includes voided ones for the audit ledger display)
    payments = Payment.objects.filter(student=student).select_related('academic_year', 'term', 'received_by', 'voided_by').order_by('-date_paid')
    
    # Calculate total paid EXCLUDING voided payments for the active term (or overall if no term)
    valid_payments = payments.filter(is_voided=False)
    paid_sum = valid_payments.filter(term=term_to_use).aggregate(total=Sum('amount_paid'))['total'] if term_to_use else valid_payments.aggregate(total=Sum('amount_paid'))['total']
    paid = Decimal(str(paid_sum)) if paid_sum is not None else Decimal("0.00")

    balance = expected - paid

    context = {
        'student': student,
        'enrollment': enrollment,
        'term': term_to_use,
        'expected': expected,
        'paid': paid,
        'balance': balance,
        'payments': payments,
    }
    return render(request, 'core/student_financial_profile.html', context)
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

def generate_student_fees_for_term(term=None):
    """
    Automatically calculates and creates StudentFee records for all 
    enrolled students for a given term based on their current_class's FeeStructure.
    """
    if not term:
        term = Term.objects.filter(is_current=True).first()
    
    if not term:
        return 0

    count = 0
    for student in StudentProfile.objects.all():
        # Use student.current_class as defined in your StudentProfile model
        class_stream = student.current_class
        
        if class_stream:
            # Sum up all fee categories configured for this class stream and term
            total_fee_sum = FeeStructure.objects.filter(
                term=term, 
                class_stream=class_stream
            ).aggregate(total=Sum('amount')).get('total') or Decimal('0.00')

            # Create or update the StudentFee record for this student
            StudentFee.objects.update_or_create(
                student=student,
                term=term,
                defaults={'total_expected': total_fee_sum}
            )
            count += 1

    return count
# views.py (Finance)
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.utils import timezone
from django.contrib import messages
from .models import Payment

@login_required
@permission_required('core.can_void_payment', raise_exception=True)
def void_payment_view(request, payment_id):
    """
    Handles the secure voiding/reversing of a payment with a mandatory audit trail.
    """
    payment = get_object_or_404(Payment, id=payment_id)
    
    if payment.is_voided:
        messages.error(request, "This payment has already been voided.")
        return redirect('accountant_dashboard')
        
    if request.method == 'POST':
        reason = request.POST.get('void_reason')
        if not reason:
            messages.error(request, "A reason is mandatory for voiding a payment.")
            return redirect('void_payment', payment_id=payment.id)
            
        # Mark as voided and record audit metadata
        payment.is_voided = True
        payment.void_reason = reason
        payment.voided_at = timezone.now()
        payment.voided_by = request.user
        payment.save()
        
        messages.success(request, f"Payment {payment.receipt_number} has been successfully voided.")
        return redirect('accountant_dashboard')
        
    return render(request, 'core/void_payment_confirm.html', {'payment': payment})
from decimal import Decimal
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import get_object_or_404, render
from .models import StudentProfile, StudentEnrollment, Payment, StudentFee, FeeStructure, Term


@login_required
def student_financial_statement(request, student_id):
    """
    Generates a complete, printable financial statement and ledger history for a single student.
    Accessible by accountants/admins for any student, and by a student for their own record only.
    """
    student = get_object_or_404(StudentProfile, id=student_id)

    is_owner = student.user_id == request.user.id
    if not (is_accountant_or_admin(request.user) or is_owner):
        raise PermissionDenied("You do not have permission to view this statement.")

    # Fetch all enrollments for this student
    enrollments = StudentEnrollment.objects.filter(student=student).select_related('class_stream', 'term', 'academic_year')

    # Fetch all payments (including voided ones, so the history is fully accountable)
    payments = Payment.objects.filter(student=student).order_by('-date_paid')

    # Calculate overall financial totals
    total_expected = Decimal("0.00")
    for enrollment in enrollments:
        expected_sum = StudentFee.objects.filter(student=student, term=enrollment.term).aggregate(total=Sum('total_expected'))['total']
        if expected_sum is None:
            expected_sum = FeeStructure.objects.filter(class_stream=enrollment.class_stream, term=enrollment.term).aggregate(total=Sum('amount'))['total'] or Decimal("0.00")
        total_expected += Decimal(str(expected_sum))

    # Only sum non-voided payments for the paid total
    valid_payments = payments.filter(is_voided=False)
    total_paid_sum = valid_payments.aggregate(total=Sum('amount_paid'))['total']
    total_paid = Decimal(str(total_paid_sum)) if total_paid_sum is not None else Decimal("0.00")

    outstanding_balance = total_expected - total_paid
    if outstanding_balance < Decimal("0.00"):
        outstanding_balance = Decimal("0.00")

    context = {
        'student': student,
        'enrollments': enrollments,
        'payments': payments,
        'total_expected': total_expected,
        'total_paid': total_paid,
        'outstanding_balance': outstanding_balance,
    }

    return render(request, 'core/student_statement.html', context)
from decimal import Decimal
from django.utils import timezone
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum
from django.shortcuts import render
from .models import Payment

@login_required
@user_passes_test(is_accountant_or_admin, login_url="login")
def daily_collection_report(request):
    """
    Generates a daily collection summary report broken down by payment methods.
    """
    # Allow picking a date via GET parameters, default to today
    date_str = request.GET.get('date')
    if date_str:
        try:
            report_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            report_date = timezone.now().date()
    else:
        report_date = timezone.now().date()

    # Fetch active (non-voided) payments for this specific date
    payments = Payment.objects.filter(date_paid__date=report_date, is_voided=False).select_related('student', 'term')

    # Aggregate by payment method
    method_summaries = payments.values('payment_method').annotate(total=Sum('amount_paid'))
    
    # Calculate overall daily total and transaction count
    total_collection_sum = payments.aggregate(total=Sum('amount_paid'))['total']
    total_collection = Decimal(str(total_collection_sum)) if total_collection_sum is not None else Decimal("0.00")
    total_transactions = payments.count()

    context = {
        'report_date': report_date,
        'payments': payments,
        'method_summaries': method_summaries,
        'total_collection': total_collection,
        'total_transactions': total_transactions,
    }
    
    return render(request, 'core/daily_collection_report.html', context)
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Q
# Make sure to import your Student model (adjust app name as needed)
from .models import StudentProfile as Student

@login_required
def student_search(request):
    query = request.GET.get('q', '').strip()
    students = []
    
    if query:
        # Search by name, registration number, or parent/guardian contact info
        students = Student.objects.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(registration_number__icontains=query)
        ).distinct()[:50]  # Limit results for performance
        
    context = {
        'query': query,
        'students': students,
    }
    return render(request, 'accountant/student_search.html', context)
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from .models import Payment, ClassStream, StudentFee, FeeStructure, Term

@login_required
def class_collections_report(request):
    classes = ClassStream.objects.all()
    class_data = []
    
    current_term = Term.objects.filter(is_current=True).first()
    
    for c in classes:
        students = c.studentprofile_set.all()
        student_count = students.count()
        
        total_expected = StudentFee.objects.filter(student__current_class=c).aggregate(
            sum_expected=Sum('total_expected')
        )['sum_expected'] or 0
        
        if total_expected == 0 and current_term:
            class_fee_total = FeeStructure.objects.filter(
                class_stream=c, 
                term=current_term, 
                academic_year=current_term.academic_year
            ).aggregate(sum_amount=Sum('amount'))['sum_amount'] or 0
            
            total_expected = class_fee_total * student_count

        payments = Payment.objects.filter(student__current_class=c)
        total_collected = sum(p.amount_paid for p in payments)
        
        balance = total_expected - total_collected
        
        # Calculate collection rate percentage safely
        if total_expected > 0:
            collection_rate = (total_collected / total_expected) * 100
        else:
            collection_rate = 0.0

        class_data.append({
            'class_name': c.name,
            'total_students': student_count,
            'total_expected': total_expected,
            'total_collected': total_collected,
            'balance': balance,
            'collection_rate': round(collection_rate, 1),
            'transaction_count': payments.count()
        })

    context = {
        'class_data': class_data,
    }
    return render(request, 'accountant/class_collections_report.html', context)
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from .models import Payment, ClassStream, StudentFee, FeeStructure, Term

@login_required
def class_collections_report(request):
    classes = ClassStream.objects.all()
    class_data = []
    
    current_term = Term.objects.filter(is_current=True).first()
    
    for c in classes:
        students = c.studentprofile_set.all()
        student_count = students.count()
        
        # Try fetching from StudentFee model first
        total_expected = StudentFee.objects.filter(student__current_class=c).aggregate(
            sum_expected=Sum('total_expected')
        )['sum_expected'] or 0
        
        # Fallback to FeeStructure if no individual student fee records exist
        if total_expected == 0 and current_term:
            class_fee_total = FeeStructure.objects.filter(
                class_stream=c, 
                term=current_term, 
                academic_year=current_term.academic_year
            ).aggregate(sum_amount=Sum('amount'))['sum_amount'] or 0
            
            total_expected = class_fee_total * student_count

        # Sum collected payments for students in this class
        payments = Payment.objects.filter(student__current_class=c)
        total_collected = sum(p.amount_paid for p in payments)
        
        balance = total_expected - total_collected
        
        # Calculate collection rate percentage safely
        if total_expected > 0:
            collection_rate = (total_collected / total_expected) * 100
        else:
            collection_rate = 0.0

        class_data.append({
            'class_id': c.id,  # Essential for the detail page link
            'class_name': c.name,
            'total_students': student_count,
            'total_expected': total_expected,
            'total_collected': total_collected,
            'balance': balance,
            'collection_rate': round(collection_rate, 1),
            'transaction_count': payments.count()
        })

    context = {
        'class_data': class_data,
    }
    return render(request, 'accountant/class_collections_report.html', context)
@login_required
def class_collection_detail(request, class_id):
    class_stream = get_object_or_404(ClassStream, id=class_id)
    students = class_stream.studentprofile_set.all()
    current_term = Term.objects.filter(is_current=True).first()
    
    student_details = []
    class_total_expected = 0
    class_total_collected = 0
    
    for student in students:
        student_expected = StudentFee.objects.filter(student=student).aggregate(
            sum_expected=Sum('total_expected')
        )['sum_expected'] or 0
        
        if student_expected == 0 and current_term:
            student_expected = FeeStructure.objects.filter(
                class_stream=class_stream,
                term=current_term,
                academic_year=current_term.academic_year
            ).aggregate(sum_amount=Sum('amount'))['sum_amount'] or 0
            
        # FIX: Exclude voided payments from calculations and counts
        student_payments = Payment.objects.filter(student=student, is_voided=False)
        student_collected = sum(p.amount_paid for p in student_payments)
        student_balance = student_expected - student_collected
        
        class_total_expected += student_expected
        class_total_collected += student_collected
        
        student_details.append({
            'student': student,
            'expected': student_expected,
            'collected': student_collected,
            'balance': student_balance,
            'payments_count': student_payments.count()
        })
        
    class_balance = class_total_expected - class_total_collected
    
    context = {
        'class_stream': class_stream,
        'student_details': student_details,
        'class_total_expected': class_total_expected,
        'class_total_collected': class_total_collected,
        'class_balance': class_balance,
    }
    return render(request, 'accountant/class_collection_detail.html', context)
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from .models import StudentProfile

@login_required
def accountant_student_profile(request, student_id):
    student = get_object_or_404(StudentProfile, id=student_id)
    context = {
        'student': student,
    }
    return render(request, 'accountant/student_profile.html', context)
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