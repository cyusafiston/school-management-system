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
