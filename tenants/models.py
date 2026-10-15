
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.text import slugify

class School(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending Approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        SUSPENDED = "suspended", "Suspended"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)

    email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registered_schools",
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_schools",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class SchoolMembership(models.Model):
    class Role(models.TextChoices):
        ADMINISTRATOR = "administrator", "Administrator"
        TEACHER = "teacher", "Teacher"
        ACCOUNTANT = "accountant", "Accountant"
        STUDENT = "student", "Student"

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="memberships",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="school_memberships",
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
    )

    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["school", "user"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "user"],
                name="unique_school_user_membership",
            ),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.school.name} ({self.role})"


class StudentRegistrationCounter(models.Model):
    """
    Tracks student registration numbers separately
    for each school and registration year.
    """

    school = models.ForeignKey(
        "tenants.School",
        on_delete=models.PROTECT,
        related_name="student_registration_counters",
    )

    year = models.PositiveIntegerField()

    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "year"],
                name="unique_student_counter_per_school_year",
            ),
        ]
        ordering = ["school", "year"]

    def __str__(self):
        return (
            f"{self.school.name} - {self.year}: "
            f"{self.last_number}"
        )
