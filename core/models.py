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
        ('2024-2025', '2024-2025'),
        ('2025-2026', '2025-2026'),
        ('2026-2027', '2026-2027'),
        ('2027-2028', '2027-2028'),
        ('2028-2029', '2028-2029'),
        ('2029-2030', '2029-2030'),
    ]
    name = models.CharField(max_length=20, unique=True, choices=ACADEMIC_YEAR_CHOICES)
    is_current = models.BooleanField(default=False)
    
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
        ('Term 1', 'Term 1'),
        ('Term 2', 'Term 2'),
        ('Term 3', 'Term 3'),
    ]
    name = models.CharField(max_length=20, choices=TERM_CHOICES)
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE)
    is_current = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ('name', 'academic_year')
    
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
  code = models.CharField(max_length=20, unique=True, blank=True)

  class Meta:
    # This ensures they sort sequentially from oldest to newest
    ordering = ['id']

  def save(self, *args, **kwargs):
    if not self.code or not self.code.startswith('STR/'):
      count = ClassStream.objects.count() + 1
      self.code = f'STR/{count:02d}'

    super().save(*args, **kwargs)

  def __str__(self):
    return f'{self.name} ({self.code})'

class StudentProfile(models.Model):
  school = models.ForeignKey(
      "tenants.School",
      on_delete=models.PROTECT,
      null=True,
      blank=True,
      related_name="studentprofile_records",
  )
  user = models.OneToOneField(
      User, on_delete=models.CASCADE, null=True, blank=True
  )
  first_name = models.CharField(max_length=50)
  last_name = models.CharField(max_length=50)
  registration_number = models.CharField(
      max_length=30, unique=True, blank=True
  )
  date_of_birth = models.DateField()
  gender = models.CharField(
      max_length=10, choices=[('Male', 'Male'), ('Female', 'Female')]
  )
  current_class = models.ForeignKey(
      ClassStream, on_delete=models.SET_NULL, null=True
  )

  father_name = models.CharField(
      max_length=100, blank=True, null=True, default='None'
  )
  father_phone = models.CharField(
      max_length=20, blank=True, null=True, validators=[validate_rwandan_phone]
  )

  mother_name = models.CharField(
      max_length=100, blank=True, null=True, default='None'
  )
  mother_phone = models.CharField(
      max_length=20, blank=True, null=True, validators=[validate_rwandan_phone]
  )
  date_enrolled = models.DateField(auto_now_add=True)

  class Meta:
    ordering = ['id']

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

    if self.date_of_birth:
      if self.date_of_birth > date.today():
        raise ValidationError(
            {'date_of_birth': 'Date of birth cannot be in the future!'}
        )

      if self.age < 3 or self.age > 30:
        raise ValidationError({
            'date_of_birth': (
                'Please enter a valid school age (student must be between 3'
                ' and 30 years old).'
            )
        })

    if self.father_phone:
      validate_rwandan_phone(self.father_phone)
    if self.mother_phone:
      validate_rwandan_phone(self.mother_phone)

  def save(self, *args, **kwargs):
    if not self.registration_number:
      current_year = datetime.now().year
      prefix = f'STU/{current_year}/'

      last_student = (
          StudentProfile.objects.filter(registration_number__startswith=prefix)
          .order_by('-id')
          .first()
      )

      if last_student:
        try:
          last_seq = int(last_student.registration_number.split('/')[-1])
          new_seq = last_seq + 1
        except ValueError:
          new_seq = StudentProfile.objects.count() + 1
      else:
        new_seq = 1

      self.registration_number = f'{prefix}{new_seq:03d}'

    # Automatically create a Django User account using the exact registration number as the username
    if not self.user:
      username = self.registration_number  # Keeps format like "STU/2026/001"
      default_password = 'student123'

      user = User.objects.create_user(
          username=username,
          password=default_password,
          first_name=self.first_name,
          last_name=self.last_name,
      )
      self.user = user

    self.full_clean()
    super().save(*args, **kwargs)

    if self.current_class:
      current_term = Term.objects.filter(is_current=True).first()
      if current_term:
        StudentEnrollment.objects.get_or_create(
            student=self,
            academic_year=current_term.academic_year,
            term=current_term,
            defaults={'class_stream': self.current_class, 'status': 'Active'},
        )

  def __str__(self):
    return f'{self.first_name} {self.last_name} ({self.registration_number})'

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
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['student', 'subject', 'term'], name='unique_student_term_grade')
        ]

    def clean(self):
        super().clean()
        max_cat = getattr(self.subject, 'max_cat_marks', Decimal('50.00')) or Decimal('50.00')
        max_exam = getattr(self.subject, 'max_exam_marks', Decimal('50.00')) or Decimal('50.00')

        if self.cat_marks > max_cat:
            raise ValidationError({'cat_marks': f"CAT marks cannot exceed the maximum of {max_cat} for this subject."})
        if self.exam_marks > max_exam:
            raise ValidationError({'exam_marks': f"Exam marks cannot exceed the maximum of {max_exam} for this subject."})

    def save(self, *args, **kwargs):
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
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'profile__role': 'Teacher'})
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    current_class = models.ForeignKey(ClassStream, on_delete=models.CASCADE)
    term = models.ForeignKey(Term, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.teacher.username} teaches {self.subject.name} in {self.current_class.name}"

class Homework(models.Model):
    assignment = models.ForeignKey(TeacherAssignment, on_delete=models.CASCADE, related_name='homeworks')
    title = models.CharField(max_length=255)
    description = models.TextField()
    due_date = models.DateField()
    file = models.FileField(upload_to='homework_files/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} - {self.assignment.subject.name}"

class Attendance(models.Model):
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

    def __str__(self):
        return f"{self.student} - {self.date} ({self.status})"

class StudentEnrollment(models.Model):
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

    def __str__(self):
        return f"{self.student} - {self.status} ({self.date})"

class Notice(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    target_class = models.ForeignKey(ClassStream, on_delete=models.CASCADE, null=True, blank=True, help_text="Leave blank for school-wide notices.")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateField(null=True, blank=True, help_text="Date when this notice stops showing up.")

    def __str__(self):
        return self.title
    from django.db import models

class FeeCategory(models.Model):
    """Categories like Tuition, Transport, Lunch, Examination, etc."""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __str__(self):
        return self.name

class FeeStructure(models.Model):
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

class StudentFee(models.Model):
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
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone

class Payment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('Cash', 'Cash'),
        ('Bank Deposit', 'Bank Deposit'),
        ('Mobile Money', 'Mobile Money'),
        ('Check', 'Check'),
    ]

    student = models.ForeignKey('StudentProfile', on_delete=models.CASCADE, related_name='payments')
    academic_year = models.ForeignKey('AcademicYear', on_delete=models.CASCADE)
    term = models.ForeignKey('Term', on_delete=models.CASCADE)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES, default='Cash')
    reference_number = models.CharField(max_length=100, blank=True, null=True, unique=True)
    receipt_number = models.CharField(max_length=50, unique=True, blank=True, null=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    date_paid = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    # New fields for tracking payment reversals/voids
    is_voided = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True, null=True)
    voided_at = models.DateTimeField(blank=True, null=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='voided_payments'
    )

    class Meta:
        permissions = [
            ("can_void_payment", "Can void payment"),
        ]

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            year = timezone.now().year
            unique_suffix = str(uuid.uuid4().int)[:5]
            self.receipt_number = f"REC-{year}-{unique_suffix}"
        super().save(*args, **kwargs)

    def __str__(self):
        receipt_str = self.receipt_number or "PENDING"
        status = " [VOIDED]" if self.is_voided else ""
        return f"{receipt_str} - {self.student} ({self.amount_paid} RWF){status}"