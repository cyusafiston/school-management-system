from django.db import models
from datetime import datetime, date
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
import re

def validate_rwandan_phone(value):
    if not value:
        return

    cleaned_value = value.strip()
    pattern = r'^(07[2389]\d{7})$'

    if not re.match(pattern, cleaned_value):
        raise ValidationError(
            "Invalid Rwandan phone number. Must be exactly 10 digits and start with 078, 079, 072, or 073 (e.g., 0781234567)."
        )


class AcademicYear(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="academicyear_records",
    )

    ACADEMIC_YEAR_CHOICES = [
        ("2024-2025", "2024-2025"),
        ("2025-2026", "2025-2026"),
        ("2026-2027", "2026-2027"),
        ("2027-2028", "2027-2028"),
        ("2028-2029", "2028-2029"),
        ("2029-2030", "2029-2030"),
    ]

    name = models.CharField(
        max_length=20,
        choices=ACADEMIC_YEAR_CHOICES,
    )

    is_current = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="unique_academic_year_per_school",
            ),
        ]

    def clean(self):
        super().clean()

        if self.school_id is None:
            raise ValidationError({
                "school": "An academic year must belong to a school."
            })

    def __str__(self):
        return self.name




class Term(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="term_records",
    )

    TERM_CHOICES = [
        ("Term 1", "Term 1"),
        ("Term 2", "Term 2"),
        ("Term 3", "Term 3"),
    ]

    name = models.CharField(
        max_length=20,
        choices=TERM_CHOICES,
    )

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE,
    )

    is_current = models.BooleanField(default=False)

    class Meta:
        unique_together = ("name", "academic_year")
        constraints = [
            models.UniqueConstraint(
                fields=["school"],
                condition=models.Q(is_current=True),
                name="unique_current_term_per_school",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.school_id is None:
            errors["school"] = (
                "A term must belong to a school."
            )

        if self.academic_year_id:
            academic_year_school_id = (
                AcademicYear.objects.filter(
                    pk=self.academic_year_id
                )
                .values_list("school_id", flat=True)
                .first()
            )

            if (
                self.school_id is not None
                and academic_year_school_id is not None
                and self.school_id != academic_year_school_id
            ):
                errors["academic_year"] = (
                    "The academic year must belong to the same school "
                    "as the term."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.academic_year})"



from django.db import models
from django.utils.text import slugify



class ClassStream(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="classstream_records",
    )

    name = models.CharField(max_length=50)

    code = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
    )

    class Meta:
        ordering = ["id"]

    def clean(self):
        super().clean()

        if self.school_id is None:
            raise ValidationError({
                "school": "A class must belong to a school."
            })

    def save(self, *args, **kwargs):
        import uuid

        if not self.code:
            self.code = f"STR/{uuid.uuid4().hex[:12].upper()}"

        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"



class StudentProfile(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="studentprofile_records",
    )

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )


    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)

    registration_number = models.CharField(
        max_length=30,
        blank=True,
    )

    date_of_birth = models.DateField()


    date_of_birth = models.DateField()

    gender = models.CharField(
        max_length=10,
        choices=[
            ("Male", "Male"),
            ("Female", "Female"),
        ],
    )


    current_class = models.ForeignKey(
        ClassStream,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )


    father_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        default="None",
    )

    father_phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[validate_rwandan_phone],
    )

    mother_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        default="None",
    )

    mother_phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[validate_rwandan_phone],
    )

    date_enrolled = models.DateField(auto_now_add=True)


    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "registration_number"],
                name="unique_student_registration_per_school",
            ),
        ]

    @property
    def age(self):
        if not self.date_of_birth:
            return None

        today = date.today()

        return (
            today.year
            - self.date_of_birth.year
            - (
                (today.month, today.day)
                < (self.date_of_birth.month, self.date_of_birth.day)
            )
        )



    def clean(self):
        super().clean()

        from tenants.models import SchoolMembership

        errors = {}

        # 1. Every student must belong to a school.
        if self.school_id is None:
            errors["school"] = [
                "A student must belong to a school."
            ]

        # 2. Validate student age.
        if self.date_of_birth:
            if self.date_of_birth > date.today():
                errors["date_of_birth"] = [
                    "Date of birth cannot be in the future."
                ]
            elif self.age < 3 or self.age > 30:
                errors["date_of_birth"] = [
                    "Student age must be between 3 and 30 years."
                ]

        # 3. Ensure the selected class belongs to
        # the student's school.
        if self.current_class_id and self.school_id:
            valid_class = ClassStream.objects.filter(
                pk=self.current_class_id,
                school_id=self.school_id,
            ).exists()

            if not valid_class:
                errors["current_class"] = [
                    "The selected class must belong to "
                    "the student's school."
                ]

        # 4. Prevent changing the school or linked account
        # of an existing student.
        if self.pk:
            original = (
                type(self).objects
                .filter(pk=self.pk)
                .values("school_id", "user_id")
                .first()
            )

            if original:
                if original["school_id"] != self.school_id:
                    errors.setdefault("school", []).append(
                        "An existing student cannot be transferred "
                        "to another school by changing their school."
                    )

                if original["user_id"] != self.user_id:
                    errors.setdefault("user", []).append(
                        "An existing student's linked account "
                        "cannot be changed directly."
                    )

        # 5. Prevent linking an account that already
        # belongs to another student.
        if self.user_id:
            account_in_use = (
                type(self).objects
                .filter(user_id=self.user_id)
                .exclude(pk=self.pk)
                .exists()
            )

            if account_in_use:
                errors.setdefault("user", []).append(
                    "This user account is already linked "
                    "to another student."
                )

            # 6. Prevent cross-school account assignments.
            if self.school_id:
                other_school_membership = (
                    SchoolMembership.objects.filter(
                        user_id=self.user_id,
                        is_active=True,
                    )
                    .exclude(school_id=self.school_id)
                    .exists()
                )

                if other_school_membership:
                    errors.setdefault("user", []).append(
                        "This account has an active membership "
                        "at another school and cannot be linked "
                        "to this student."
                    )

        # 7. Return all validation errors together.
        if errors:
            raise ValidationError(errors)




    def save(self, *args, **kwargs):
        import uuid

        from django.core.exceptions import ValidationError
        from django.db import transaction
        from django.utils import timezone

        from tenants.models import (
    School,
    SchoolMembership,
    StudentRegistrationCounter,
)

        is_new = self._state.adding

        with transaction.atomic():
            if self.school_id is None:
                raise ValidationError({
                    "school": "A student must belong to a school."
                })

            if is_new:
                # Lock this school's row to serialize registrations
                # for the same school, including the first of a year.
                School.objects.select_for_update().get(
                    pk=self.school_id
                )

                if not self.registration_number:
                    current_year = timezone.localdate().year

                    counter, _ = (
                        StudentRegistrationCounter.objects.get_or_create(
                            school_id=self.school_id,
                            year=current_year,
                            defaults={"last_number": 0},
                        )
                    )

                    counter = (
                        StudentRegistrationCounter.objects
                        .select_for_update()
                        .get(pk=counter.pk)
                    )

                    counter.last_number += 1
                    counter.save(update_fields=["last_number"])

                    self.registration_number = (
                        f"STU/{current_year}/"
                        f"{counter.last_number:03d}"
                    )

            # Validate before creating a Django user account.
            self.full_clean()

            if not self.user_id:
                # This username is internal and globally unique.
                # It is intentionally different from the
                # school-specific registration number.
                internal_username = (
                    f"student_{uuid.uuid4().hex}"
                )

                user = User.objects.create_user(
                    username=internal_username,
                    password=None,
                    first_name=self.first_name,
                    last_name=self.last_name,
                )

                self.user = user

                # The existing signal initially assigns Teacher
                # to non-STU usernames. Correct that explicitly.
                UserProfile.objects.update_or_create(
                    user=user,
                    defaults={"role": "Student"},
                )

            super().save(*args, **kwargs)

            # Ensure this student belongs to the correct school.
            # Never silently change an existing membership's role.
            membership, created = SchoolMembership.objects.get_or_create(
                school_id=self.school_id,
                user_id=self.user_id,
                defaults={
                    "role": SchoolMembership.Role.STUDENT,
                    "is_active": True,
                },
            )

            if membership.role != SchoolMembership.Role.STUDENT:
                raise ValidationError({
                    "user": (
                        "This account already has a different role "
                        "at the selected school."
                    )
                })

            if not membership.is_active:
                raise ValidationError({
                    "user": (
                        "This student's school membership is inactive. "
                        "An administrator must review it."
                    )
                })


            # Preserve automatic enrollment in this school's
            # current academic term only.
            if is_new and self.current_class_id:
                current_term = (
                    Term.objects.filter(
                        school_id=self.school_id,
                        is_current=True,
                        academic_year__school_id=self.school_id,
                    )
                    .select_related("academic_year")
                    .first()
                )

                if current_term:
                    StudentEnrollment.objects.get_or_create(
                        school_id=self.school_id,
                        student=self,
                        academic_year=current_term.academic_year,
                        term=current_term,
                        defaults={
                            "class_stream": self.current_class,
                            "status": "Active",
                        },
                    )


    def __str__(self):
        return (
            f"{self.first_name} {self.last_name} "
            f"({self.registration_number})"
        )


from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError

class Subject(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subject_records",
    )
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)

    max_cat_marks = models.DecimalField(max_digits=5, decimal_places=2, default=50.00, help_text="Maximum possible marks for CAT")
    max_exam_marks = models.DecimalField(max_digits=5, decimal_places=2, default=50.00, help_text="Maximum possible marks for Exam")

    class Meta:
        ordering = ['id']

    def save(self, *args, **kwargs):
        if not self.code or not self.code.startswith("SUB/"):
            count = Subject.objects.count() + 1
            self.code = f"SUB/{count:02d}"

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"

from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError

class Grade(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="grade_records",
    )

    student = models.ForeignKey('StudentProfile', on_delete=models.CASCADE, related_name='grades')
    subject = models.ForeignKey('Subject', on_delete=models.CASCADE, related_name='grades')
    term = models.ForeignKey('Term', on_delete=models.CASCADE)

    cat_marks = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, help_text="Total CAT marks obtained")
    exam_marks = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, help_text="Exam marks obtained")

    marks_obtained = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, help_text="Total (CAT + Exam)")
    max_marks = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, help_text="Total Possible Max Marks")
    percentage = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)

    grade_letter = models.CharField(max_length=2, blank=True, null=True)
    remarks = models.CharField(max_length=50, blank=True, null=True)

    status = models.CharField(
        max_length=10,
        choices=[('Draft', 'Draft'), ('Finalized', 'Finalized')],
        default='Draft'
    )
    finalized_by = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finalized_grades",
    )
    finalized_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['student', 'subject', 'term'], name='unique_student_term_grade')
        ]

    def clean(self):
        super().clean()

        errors = {}
        for field_name in ("cat_marks", "exam_marks"):
            value = getattr(self, field_name, None)

            if value is not None:
                try:
                    finite = value.is_finite()
                except (AttributeError, TypeError):
                    finite = False

                if not finite:
                    errors[field_name] = (
                        "Marks must be a finite numeric value."
                    )

        if not self.school_id:
            errors["school"] = "Every grade must belong to a school."

        if self.student_id and self.school_id:
            if self.student.school_id != self.school_id:
                errors["student"] = "Student belongs to another school."

        if self.subject_id and self.school_id:
            if self.subject.school_id != self.school_id:
                errors["subject"] = "Subject belongs to another school."

        if self.term_id and self.school_id:
            if self.term.school_id != self.school_id:
                errors["term"] = "Term belongs to another school."
            elif self.term.academic_year.school_id != self.school_id:
                errors["term"] = "Academic year belongs to another school."

        if self.subject_id:
            max_cat = self.subject.max_cat_marks
            max_exam = self.subject.max_exam_marks

            if (
                self.cat_marks is not None
                and "cat_marks" not in errors
            ):
                if self.cat_marks < 0:
                    errors["cat_marks"] = "CAT marks cannot be negative."
                elif self.cat_marks > max_cat:
                    errors["cat_marks"] = (
                        f"CAT marks cannot exceed {max_cat}."
                    )

            if (
                self.exam_marks is not None
                and "exam_marks" not in errors
            ):
                if self.exam_marks < 0:
                    errors["exam_marks"] = "Exam marks cannot be negative."
                elif self.exam_marks > max_exam:
                    errors["exam_marks"] = (
                        f"Exam marks cannot exceed {max_exam}."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        if self.pk is not None:
            original = type(self).objects.filter(pk=self.pk).first()

            if original is not None and original.status == "Finalized":
                raise ValidationError(
                    "This grade is finalized and cannot be modified."
                )

        max_cat = getattr(self.subject, 'max_cat_marks', Decimal('50.00')) or Decimal('50.00')
        max_exam = getattr(self.subject, 'max_exam_marks', Decimal('50.00')) or Decimal('50.00')

        self.max_marks = (max_cat + max_exam).quantize(Decimal('0.01'))
        self.marks_obtained = ((self.cat_marks or Decimal('0.00')) + (self.exam_marks or Decimal('0.00'))).quantize(Decimal('0.01'))

        if self.max_marks and self.max_marks > 0:
            raw_percentage = (self.marks_obtained / self.max_marks) * Decimal('100.00')
            self.percentage = raw_percentage.quantize(Decimal('0.01'))
        else:
            self.percentage = Decimal('0.00')

        if self.percentage >= Decimal('80.00'):
            self.grade_letter = 'A'
            self.remarks = 'Excellent'
        elif self.percentage >= Decimal('70.00'):
            self.grade_letter = 'B'
            self.remarks = 'Very Good'
        elif self.percentage >= Decimal('60.00'):
            self.grade_letter = 'C'
            self.remarks = 'Good'
        elif self.percentage >= Decimal('50.00'):
            self.grade_letter = 'D'
            self.remarks = 'Satisfactory'
        else:
            self.grade_letter = 'F'
            self.remarks = 'Fail'

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} - {self.subject.name}: {self.marks_obtained}/{self.max_marks} ({self.grade_letter})"

class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('Administrator', 'Administrator'),
        ('Teacher', 'Teacher'),
        ('Accountant', 'Accountant'),
        ('Student', 'Student'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='Teacher')
    phone_number = models.CharField(max_length=15, blank=True, null=True, validators=[validate_rwandan_phone])

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.user.username} - {self.role}"

# Automatic profile creation signal
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        if instance.username.lower().startswith('stu/'):
            assigned_role = 'Student'
        elif instance.is_superuser or instance.is_staff:
            assigned_role = 'Administrator'
        else:
            assigned_role = 'Teacher'
        UserProfile.objects.get_or_create(user=instance, defaults={'role': assigned_role})

class TeacherAssignment(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="teacherassignment_records",
    )

    teacher = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'profile__role': 'Teacher'})
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    current_class = models.ForeignKey(ClassStream, on_delete=models.CASCADE)
    term = models.ForeignKey(Term, on_delete=models.CASCADE)


    def clean(self):
        from django.core.exceptions import ValidationError
        from tenants.models import SchoolMembership

        super().clean()

        errors = {}

        if not self.school_id:
            errors["school"] = "A school is required."
            raise ValidationError(errors)

        related_fields = {
            "subject": self.subject_id,
            "current_class": self.current_class_id,
            "term": self.term_id,
        }

        for field_name, related_id in related_fields.items():
            if related_id is None:
                continue

            related_model = self._meta.get_field(
                field_name
            ).remote_field.model

            valid = related_model.objects.filter(
                pk=related_id,
                school_id=self.school_id,
            ).exists()

            if not valid:
                errors[field_name] = (
                    "This record must belong to the "
                    "assignment's school."
                )

        if self.term_id:
            from core.models import Term

            valid_term_year = Term.objects.filter(
                pk=self.term_id,
                school_id=self.school_id,
                academic_year__school_id=self.school_id,
            ).exists()

            if not valid_term_year:
                errors["term"] = (
                    "The term and academic year must "
                    "belong to the assignment's school."
                )

        if self.teacher_id:
            valid_teacher = SchoolMembership.objects.filter(
                school_id=self.school_id,
                user_id=self.teacher_id,
                role="teacher",
                is_active=True,
            ).exists()

            if not valid_teacher:
                errors["teacher"] = (
                    "The teacher must have an active "
                    "teacher membership in this school."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.teacher.username} teaches {self.subject.name} in {self.current_class.name}"

class Homework(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="homework_records",
    )

    assignment = models.ForeignKey(TeacherAssignment, on_delete=models.CASCADE, related_name='homeworks')
    title = models.CharField(max_length=255)
    description = models.TextField()
    due_date = models.DateField()
    file = models.FileField(upload_to='homework_files/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} - {self.assignment.subject.name}"

class Attendance(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attendance_records",
    )

    STATUS_CHOICES = [
        ('Present', 'Present'),
        ('Absent', 'Absent'),
        ('Late', 'Late'),
    ]

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='attendances')
    assignment = models.ForeignKey(TeacherAssignment, on_delete=models.CASCADE, related_name='attendances')
    date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Present')
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'assignment', 'date')


    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        errors = {}

        if not self.school_id:
            errors["school"] = "A school is required."
            raise ValidationError(errors)

        if self.student_id:
            valid_student = StudentProfile.objects.filter(
                pk=self.student_id,
                school_id=self.school_id,
            ).exists()

            if not valid_student:
                errors["student"] = (
                    "The student must belong to "
                    "the attendance record's school."
                )

        if self.assignment_id:
            valid_assignment = TeacherAssignment.objects.filter(
                pk=self.assignment_id,
                school_id=self.school_id,
                subject__school_id=self.school_id,
                current_class__school_id=self.school_id,
                term__school_id=self.school_id,
                term__academic_year__school_id=self.school_id,
            ).exists()

            if not valid_assignment:
                errors["assignment"] = (
                    "The teacher assignment and its related "
                    "academic records must belong to "
                    "the attendance record's school."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} - {self.date} ({self.status})"

class StudentEnrollment(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="studentenrollment_records",
    )

    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Completed', 'Completed'),
        ('Transferred', 'Transferred'),
        ('Dropped', 'Dropped'),
    ]

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='enrollments')
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE)
    term = models.ForeignKey(Term, on_delete=models.CASCADE)
    class_stream = models.ForeignKey(ClassStream, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    date_enrolled = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'academic_year', 'term')

    def __str__(self):
        return f"{self.student} - {self.class_stream} ({self.academic_year}, {self.term})"

class DailyClassAttendance(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="dailyclassattendance_records",
    )

    STATUS_INFO_CHOICES = [
        ('Present', 'Present'),
        ('Late', 'Late'),
        ('Absent', 'Absent'),
    ]

    student = models.ForeignKey('StudentProfile', on_delete=models.CASCADE)
    current_class = models.ForeignKey('ClassStream', on_delete=models.CASCADE)
    date = models.DateField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_INFO_CHOICES, default='Present')
    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        unique_together = ('student', 'date', 'current_class')


    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        errors = {}

        if not self.school_id:
            errors["school"] = "A school is required."
            raise ValidationError(errors)

        if self.student_id:
            valid_student = StudentProfile.objects.filter(
                pk=self.student_id,
                school_id=self.school_id,
            ).exists()

            if not valid_student:
                errors["student"] = (
                    "The student must belong to "
                    "the attendance record's school."
                )

        if self.current_class_id:
            valid_class = ClassStream.objects.filter(
                pk=self.current_class_id,
                school_id=self.school_id,
            ).exists()

            if not valid_class:
                errors["current_class"] = (
                    "The class must belong to "
                    "the attendance record's school."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} - {self.status} ({self.date})"

class Notice(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="notice_records",
    )

    title = models.CharField(max_length=200)
    content = models.TextField()
    target_class = models.ForeignKey(ClassStream, on_delete=models.CASCADE, null=True, blank=True, help_text="Leave blank for school-wide notices.")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateField(null=True, blank=True, help_text="Date when this notice stops showing up.")

    def __str__(self):
        return self.title
    from django.db import models

class FeeCategory(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="feecategory_records",
    )

    """Categories like Tuition, Transport, Lunch, Examination, etc."""
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)


    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="unique_fee_category_per_school",
            ),
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError

        if not self.school_id:
            raise ValidationError({
                "school": "A fee category must belong to a school."
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class FeeStructure(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="feestructure_records",
    )

    """Defines how much a class pays for a specific category, term, and academic year."""
    academic_year = models.ForeignKey('AcademicYear', on_delete=models.CASCADE)
    term = models.ForeignKey('Term', on_delete=models.CASCADE)
    class_stream = models.ForeignKey('ClassStream', on_delete=models.CASCADE)
    category = models.ForeignKey(FeeCategory, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        unique_together = ('academic_year', 'term', 'class_stream', 'category')

    def __str__(self):
        return f"{self.class_stream} - {self.category.name} ({self.academic_year} {self.term}): {self.amount} RWF"

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError

        errors = {}

        if not self.school_id:
            errors["school"] = "A fee structure must belong to a school."
        else:
            for field in (
                "academic_year", "term", "class_stream", "category"
            ):
                if getattr(self, f"{field}_id") is None:
                    continue

                related = getattr(self, field)

                if related.school_id != self.school_id:
                    errors[field] = "Must belong to the same school."

        if (
            self.term_id
            and self.academic_year_id
            and self.term.academic_year_id != self.academic_year_id
        ):
            errors["term"] = (
                "Term must belong to the selected academic year."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class StudentFee(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="studentfee_records",
    )

    """Tracks the total expected fee assigned to an individual student for a term."""
    student = models.ForeignKey('StudentProfile', on_delete=models.PROTECT, related_name='assigned_fees')
    academic_year = models.ForeignKey('AcademicYear', on_delete=models.PROTECT)
    term = models.ForeignKey('Term', on_delete=models.PROTECT)
    total_expected = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'academic_year', 'term'],
                name='unique_student_fee_period'
            )
        ]

    def __str__(self):
        return f"{self.student} - {self.academic_year} {self.term} Total: {self.total_expected} RWF"

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError

        errors = {}

        if not self.school_id:
            errors["school"] = "A student fee must belong to a school."
        else:
            for field in ("student", "academic_year", "term"):
                if getattr(self, f"{field}_id") is None:
                    continue

                related = getattr(self, field)

                if related.school_id != self.school_id:
                    errors[field] = "Must belong to the same school."

        if (
            self.term_id
            and self.academic_year_id
            and self.term.academic_year_id != self.academic_year_id
        ):
            errors["term"] = (
                "Term must belong to the selected academic year."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class Payment(models.Model):
    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payment_records",
    )

    PAYMENT_METHOD_CHOICES = [
        ("Cash", "Cash"),
        ("Bank Deposit", "Bank Deposit"),
        ("Mobile Money", "Mobile Money"),
        ("Check", "Check"),
    ]

    student = models.ForeignKey(
        "StudentProfile",
        on_delete=models.CASCADE,
        related_name="payments",
    )
    academic_year = models.ForeignKey(
        "AcademicYear",
        on_delete=models.CASCADE,
    )
    term = models.ForeignKey(
        "Term",
        on_delete=models.CASCADE,
    )

    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    payment_method = models.CharField(
        max_length=50,
        choices=PAYMENT_METHOD_CHOICES,
        default="Cash",
    )

    reference_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
    )

    receipt_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
    )

    received_by = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
)

    date_paid = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    is_voided = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True, null=True)
    voided_at = models.DateTimeField(blank=True, null=True)

    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="voided_payments",
    )

    class Meta:
        permissions = [
            ("can_void_payment", "Can void payment"),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()

        errors = {}

        if not self.school_id:
            errors["school"] = "A payment must belong to a school."
            raise ValidationError(errors)

        related_objects = {
            "student": self.student_id,
            "academic_year": self.academic_year_id,
            "term": self.term_id,
        }

        for field_name, related_id in related_objects.items():
            if related_id is None:
                continue

            related_object = getattr(self, field_name)

            if related_object.school_id != self.school_id:
                errors[field_name] = (
                    "This record must belong to the same school "
                    "as the payment."
                )

        if (
            self.term_id
            and self.academic_year_id
            and self.term.academic_year_id != self.academic_year_id
        ):
            errors["term"] = (
                "The selected term does not belong to "
                "the selected academic year."
            )

        if self.amount_paid is not None and self.amount_paid <= 0:
            errors["amount_paid"] = (
                "Payment amount must be greater than zero."
            )

        if self.is_voided:
            if not self.void_reason or not self.void_reason.strip():
                errors["void_reason"] = (
                    "A reason is required when voiding a payment."
                )

            if not self.voided_at:
                errors["voided_at"] = (
                    "A voided payment must have a void date."
                )

            if not self.voided_by_id:
                errors["voided_by"] = (
                    "A voided payment must identify who voided it."
                )
        elif self.void_reason or self.voided_at or self.voided_by_id:
            errors["is_voided"] = (
                "Void details require the payment to be marked voided."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        import uuid
        from django.utils import timezone

        if not self.receipt_number:
            year = timezone.now().year
            self.receipt_number = (
                f"REC-{year}-{uuid.uuid4().hex.upper()}"
            )

        self.full_clean()

        super().save(*args, **kwargs)

    def __str__(self):
        receipt_str = self.receipt_number or "PENDING"
        status = " [VOIDED]" if self.is_voided else ""

        return (
            f"{receipt_str} - {self.student} "
            f"({self.amount_paid} RWF){status}"
        )


class ClassSubject(models.Model):
    """School-specific curriculum for a class and academic year."""

    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        related_name="class_subjects",
    )

    academic_year = models.ForeignKey(
        "AcademicYear",
        on_delete=models.PROTECT,
        related_name="class_subjects",
    )

    class_stream = models.ForeignKey(
        "ClassStream",
        on_delete=models.PROTECT,
        related_name="class_subjects",
    )

    subject = models.ForeignKey(
        "Subject",
        on_delete=models.PROTECT,
        related_name="class_subjects",
    )

    is_required = models.BooleanField(default=True)

    class Meta:
        ordering = ["class_stream__name", "subject__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "academic_year", "class_stream", "subject"],
                name="unique_class_subject_per_year",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if not self.school_id:
            errors["school"] = "School is required."
        else:
            for field in ("academic_year", "class_stream", "subject"):
                related_id = getattr(self, f"{field}_id")

                if related_id is None:
                    continue

                related = getattr(self, field)

                if related.school_id != self.school_id:
                    errors[field] = "Must belong to the same school."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.class_stream.name} - {self.subject.name} "
            f"({self.academic_year.name})"
        )
