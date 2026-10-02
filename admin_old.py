from django.contrib import admin
from django.shortcuts import redirect
from .models import (
    AcademicYear, 
    Term, 
    ClassStream, 
    StudentProfile, 
    Subject, 
    Grade,
    UserProfile,
    TeacherAssignment,
    StudentEnrollment,
    DailyClassAttendance,
    Attendance,
    Homework,
    Notice,
    FeeCategory,
    FeeStructure,
    StudentFee
)

@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_current')
    list_filter = ('is_current',)

@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ('name', 'academic_year', 'is_current')
    list_filter = ('academic_year', 'is_current')

@admin.register(ClassStream)
class ClassStreamAdmin(admin.ModelAdmin):
    list_display = ('name', 'code')  
    readonly_fields = ('code',)

class StudentEnrollmentInline(admin.TabularInline):
    model = StudentEnrollment
    extra = 1
    fields = ('academic_year', 'term', 'class_stream', 'status')

@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = (
        'registration_number',
        'first_name',
        'last_name',
        'age',
        'current_class',
        'gender',
        'date_enrolled',
    )

    list_per_page = 25

    list_filter = (
        'current_class',
        'gender',
        'date_enrolled',
        'academic_year__name',
    ) if 'academic_year' in [
        f.name for f in StudentProfile._meta.fields
    ] else ('current_class', 'gender', 'date_enrolled')

    search_fields = (
        'first_name',
        'last_name',
        'registration_number',
        'father_name',
        'father_phone',
        'mother_name',
        'mother_phone',
    )

    list_editable = ('current_class',)
    readonly_fields = ('registration_number', 'age')

    inlines = [StudentEnrollmentInline]

    fieldsets = (
        (
            'Personal Information',
            {
                'fields': (
                    'first_name',
                    'last_name',
                    'date_of_birth',
                    'age',
                    'gender',
                )
            },
        ),
        ('Academic Details', {'fields': ('registration_number', 'current_class')}),
        ('Father Details', {'fields': ('father_name', 'father_phone')}),
        ('Mother Details', {'fields': ('mother_name', 'mother_phone')}),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('current_class')

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'code')
    search_fields = ('name', 'code')
    readonly_fields = ('code',)

@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'term', 'cat_marks', 'exam_marks', 'marks_obtained', 'grade_letter', 'status')
    list_filter = ('term', 'subject', 'status', 'grade_letter')
    search_fields = ('student__first_name', 'student__last_name', 'student__registration_number', 'subject__name')
    list_editable = ('cat_marks', 'exam_marks', 'status')

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'phone_number')
    list_filter = ('role',)
    search_fields = ('user__username', 'phone_number')

@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'subject', 'current_class', 'term')
    list_filter = ('term', 'current_class', 'subject')
    search_fields = ('teacher__username', 'subject__name', 'current_class__name')

@admin.register(StudentEnrollment)
class StudentEnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'class_stream', 'academic_year', 'term', 'status', 'date_enrolled')
    list_filter = ('academic_year', 'term', 'class_stream', 'status')
    search_fields = ('student__first_name', 'student__last_name', 'student__registration_number')
    list_editable = ('status',)

@admin.register(DailyClassAttendance)
class DailyClassAttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'current_class', 'date', 'status', 'submitted_by', 'is_locked')
    list_filter = ('date', 'status', 'current_class', 'is_locked')
    search_fields = ('student__first_name', 'student__last_name', 'student__registration_number', 'submitted_by__username')
    list_editable = ('status', 'is_locked')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('student', 'current_class', 'submitted_by')

    def changelist_view(self, request, extra_context=None):
        return redirect('admin_attendance_report')

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'date', 'status', 'recorded_by')
    list_filter = ('date', 'status')
    search_fields = ('student__first_name', 'student__last_name', 'student__registration_number')
    list_editable = ('status',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('student', 'recorded_by')

@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = ('title', 'assignment', 'due_date', 'created_at')
    list_filter = ('due_date', 'created_at', 'assignment__subject')
    search_fields = ('title', 'description', 'assignment__subject__name')
    readonly_fields = ('created_at',)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('assignment', 'assignment__subject', 'assignment__current_class', 'assignment__teacher')

@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = ('title', 'target_class', 'created_at', 'expires_at')
    list_filter = ('target_class', 'created_at', 'expires_at')
    search_fields = ('title', 'content')

# --- FINANCIAL MODULE ADMIN CONFIGURATIONS ---

@admin.register(FeeCategory)
class FeeCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)

@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ('academic_year', 'term', 'class_stream', 'category', 'amount')
    list_filter = ('academic_year', 'term', 'class_stream', 'category')
    search_fields = ('class_stream__name', 'category__name')

@admin.register(StudentFee)
class StudentFeeAdmin(admin.ModelAdmin):
    list_display = ('student', 'academic_year', 'term', 'total_expected', 'created_at')
    list_filter = ('academic_year', 'term')
    search_fields = ('student__first_name', 'student__last_name', 'student__registration_number')
from .models import Payment

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('student', 'amount_paid', 'payment_method', 'academic_year', 'term', 'date_paid', 'received_by')
    list_filter = ('payment_method', 'academic_year', 'term', 'date_paid')
    search_for = ('student__student_id', 'student__user__first_name', 'student__user__last_name', 'reference_number')    