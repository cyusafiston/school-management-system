from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import School


class SchoolRegistrationForm(UserCreationForm):
    school_name = forms.CharField(max_length=200)
    school_email = forms.EmailField(required=False)
    school_phone = forms.CharField(max_length=30, required=False)
    school_address = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "email", "first_name", "last_name")

    def clean_school_name(self):
        name = self.cleaned_data["school_name"].strip()
        if not name:
            raise forms.ValidationError("School name is required.")
        return name

from core.models import ClassSubject


class ClassSubjectForm(forms.ModelForm):
    """Tenant-scoped curriculum assignment form."""

    class Meta:
        model = ClassSubject
        fields = [
            "academic_year",
            "class_stream",
            "subject",
            "is_required",
        ]
        labels = {
            "academic_year": "Academic Year",
            "class_stream": "Class",
            "subject": "Subject",
            "is_required": "Required Subject",
        }

    def __init__(self, *args, school, **kwargs):
        from core.models import AcademicYear, ClassStream, Subject

        if school is None or school.pk is None:
            raise ValueError("A saved school is required.")

        self.school = school
        super().__init__(*args, **kwargs)

        # Set the trusted school before ModelForm validation.
        # Never accept the school ID from submitted form data.
        self.instance.school = school

        self.fields["academic_year"].queryset = (
            AcademicYear.objects.filter(school=school)
        )
        self.fields["class_stream"].queryset = (
            ClassStream.objects.filter(school=school)
        )
        self.fields["subject"].queryset = (
            Subject.objects.filter(school=school)
        )

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.school = self.school

        if commit:
            instance.save()

        return instance


class ClassSubjectRequirementForm(forms.ModelForm):
    """Edit only the required/optional status of a curriculum subject."""

    class Meta:
        model = ClassSubject
        fields = ["is_required"]
        labels = {
            "is_required": "Required Subject",
        }

    def __init__(self, *args, school, **kwargs):
        if school is None or school.pk is None:
            raise ValueError("A saved school is required.")

        instance = kwargs.get("instance")

        if instance is None or instance.pk is None:
            raise ValueError("An existing curriculum assignment is required.")

        if instance.school_id != school.pk:
            raise ValueError("Assignment does not belong to this school.")

        self.school = school
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)

        if instance.school_id != self.school.pk:
            raise ValueError("School mismatch.")

        if commit:
            instance.save(update_fields=["is_required"])

        return instance


# ============================================================
# SCHOOL ACADEMIC SETUP
# ============================================================

class ClassStreamForm(forms.ModelForm):
    """Create classes only within the authenticated school."""

    class Meta:
        model = __import__(
            "core.models", fromlist=["ClassStream"]
        ).ClassStream
        fields = ["name"]
        labels = {"name": "Class Name"}

    def __init__(self, *args, school, **kwargs):
        if school is None or school.pk is None:
            raise ValueError("A saved school is required.")

        self.school = school
        super().__init__(*args, **kwargs)
        self.instance.school = school

    def clean_name(self):
        from core.models import ClassStream

        name = self.cleaned_data["name"].strip()

        if not name:
            raise forms.ValidationError("Enter a class name.")

        if ClassStream.objects.filter(
            school=self.school,
            name__iexact=name,
        ).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(
                "This class already exists in your school."
            )

        return name

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.school = self.school

        if commit:
            instance.save()

        return instance


class SubjectSetupForm(forms.ModelForm):
    """Create subjects only within the authenticated school."""

    class Meta:
        model = __import__(
            "core.models", fromlist=["Subject"]
        ).Subject
        fields = [
            "name",
            "description",
            "max_cat_marks",
            "max_exam_marks",
        ]
        labels = {
            "name": "Subject Name",
            "description": "Description",
            "max_cat_marks": "Maximum CAT Marks",
            "max_exam_marks": "Maximum Exam Marks",
        }

    def __init__(self, *args, school, **kwargs):
        if school is None or school.pk is None:
            raise ValueError("A saved school is required.")

        self.school = school
        super().__init__(*args, **kwargs)
        self.instance.school = school

    def clean_name(self):
        from core.models import Subject

        name = self.cleaned_data["name"].strip()

        if not name:
            raise forms.ValidationError("Enter a subject name.")

        if Subject.objects.filter(
            school=self.school,
            name__iexact=name,
        ).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(
                "This subject already exists in your school."
            )

        return name

    def clean_max_cat_marks(self):
        value = self.cleaned_data["max_cat_marks"]

        if value <= 0:
            raise forms.ValidationError(
                "CAT maximum marks must be greater than zero."
            )

        return value

    def clean_max_exam_marks(self):
        value = self.cleaned_data["max_exam_marks"]

        if value <= 0:
            raise forms.ValidationError(
                "Exam maximum marks must be greater than zero."
            )

        return value

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.school = self.school

        if commit:
            instance.save()

        return instance


# STEP 881 - TENANT-SAFE TEACHER REGISTRATION

from django import forms as teacher_forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction


class TeacherRegistrationForm(teacher_forms.Form):
    first_name = teacher_forms.CharField(max_length=150)
    last_name = teacher_forms.CharField(max_length=150)
    username = teacher_forms.CharField(max_length=150)
    email = teacher_forms.EmailField()
    password1 = teacher_forms.CharField(
        widget=teacher_forms.PasswordInput,
        label="Password",
    )
    password2 = teacher_forms.CharField(
        widget=teacher_forms.PasswordInput,
        label="Confirm password",
    )

    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)

        if school is None or school.pk is None:
            raise ValueError("A saved school is required.")

        self.school = school

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        User = get_user_model()

        if User.objects.filter(
            username__iexact=username
        ).exists():
            raise ValidationError(
                "This username is already taken."
            )

        return username

    def clean(self):
        cleaned_data = super().clean()

        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2:
            if password1 != password2:
                self.add_error(
                    "password2",
                    "Passwords do not match.",
                )
            else:
                User = get_user_model()
                candidate = User(
                    username=cleaned_data.get("username", ""),
                    first_name=cleaned_data.get("first_name", ""),
                    last_name=cleaned_data.get("last_name", ""),
                    email=cleaned_data.get("email", ""),
                )

                try:
                    validate_password(password1, user=candidate)
                except ValidationError as error:
                    self.add_error("password1", error)

        return cleaned_data

    def save(self):
        if not self.is_valid():
            raise ValueError(
                "Cannot save an invalid teacher registration."
            )

        from core.models import UserProfile
        from tenants.models import SchoolMembership

        User = get_user_model()

        with transaction.atomic():
            user = User.objects.create_user(
                username=self.cleaned_data["username"],
                email=self.cleaned_data["email"],
                password=self.cleaned_data["password1"],
                first_name=self.cleaned_data["first_name"],
                last_name=self.cleaned_data["last_name"],
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )

            UserProfile.objects.update_or_create(
                user=user,
                defaults={"role": "Teacher"},
            )

            SchoolMembership.objects.create(
                school=self.school,
                user=user,
                role=SchoolMembership.Role.TEACHER,
                is_active=True,
            )

        return user


# STEP 904 - TENANT-SAFE TEACHER ASSIGNMENT
from django import forms as assignment_forms


class TeacherAssignmentForm(assignment_forms.ModelForm):
    """Create teacher assignments within one approved school."""

    class Meta:
        model = __import__(
            "core.models",
            fromlist=["TeacherAssignment"],
        ).TeacherAssignment

        fields = [
            "teacher",
            "current_class",
            "subject",
            "term",
        ]

        labels = {
            "teacher": "Teacher",
            "current_class": "Class",
            "subject": "Subject",
            "term": "Academic Term",
        }

    def __init__(self, *args, school, **kwargs):
        from django.contrib.auth import get_user_model
        from core.models import ClassStream, Subject, Term
        from tenants.models import SchoolMembership

        if school is None or school.pk is None:
            raise ValueError("A saved school is required.")

        self.school = school
        super().__init__(*args, **kwargs)

        # School comes from authenticated context, never POST data.
        self.instance.school = school

        User = get_user_model()

        teacher_ids = SchoolMembership.objects.filter(
            school=school,
            role=SchoolMembership.Role.TEACHER,
            is_active=True,
            user__is_active=True,
        ).values_list("user_id", flat=True)

        self.fields["teacher"].queryset = (
            User.objects.filter(pk__in=teacher_ids)
            .order_by("first_name", "last_name", "username")
        )

        self.fields["current_class"].queryset = (
            ClassStream.objects.filter(school=school)
            .order_by("name")
        )

        self.fields["subject"].queryset = (
            Subject.objects.filter(school=school)
            .order_by("name")
        )

        self.fields["term"].queryset = (
            Term.objects.filter(
                school=school,
                academic_year__school=school,
            )
            .order_by("-academic_year_id", "name")
        )

    def clean(self):
        from core.models import ClassSubject, TeacherAssignment

        cleaned_data = super().clean()

        teacher = cleaned_data.get("teacher")
        current_class = cleaned_data.get("current_class")
        subject = cleaned_data.get("subject")
        term = cleaned_data.get("term")

        if not all([teacher, current_class, subject, term]):
            return cleaned_data

        curriculum_exists = ClassSubject.objects.filter(
            school=self.school,
            academic_year=term.academic_year,
            class_stream=current_class,
            subject=subject,
        ).exists()

        if not curriculum_exists:
            self.add_error(
                "subject",
                "This subject is not included in the selected "
                "class's curriculum for the term's academic year.",
            )

        duplicate_exists = TeacherAssignment.objects.filter(
            school=self.school,
            teacher=teacher,
            current_class=current_class,
            subject=subject,
            term=term,
        ).exclude(pk=self.instance.pk).exists()

        if duplicate_exists:
            self.add_error(
                None,
                "This teacher already has the same assignment "
                "for this class, subject, and term.",
            )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.school = self.school

        if commit:
            instance.save()

        return instance
