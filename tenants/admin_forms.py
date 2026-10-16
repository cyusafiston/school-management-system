from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import ValidationError
from core.models import AcademicYear, ClassStream, StudentProfile, Subject, Term
from tenants.models import SchoolMembership
from tenants.forms import ClassStreamForm, SubjectSetupForm


class UniqueEmailMixin:
    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise ValidationError('This email is unavailable for a new account.')
        return email


class StudentRegistrationForm(UniqueEmailMixin, forms.ModelForm):
    email = forms.EmailField(max_length=254, label='Recovery email (unique to this account)')
    class Meta:
        model = StudentProfile
        fields = ['first_name', 'last_name', 'date_of_birth', 'gender', 'current_class',
                  'registration_number', 'father_name', 'father_phone', 'mother_name', 'mother_phone']
        widgets = {'date_of_birth': forms.DateInput(attrs={'type': 'date'})}
    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.school = school
        self.fields['current_class'].queryset = ClassStream.objects.filter(school=school)
        self.fields['current_class'].required = True


class StaffInvitationForm(UniqueEmailMixin, forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    username = forms.CharField(max_length=150, validators=get_user_model()._meta.get_field('username').validators)
    email = forms.EmailField(max_length=254)
    role = forms.ChoiceField(choices=[('teacher', 'Teacher'), ('accountant', 'Accountant')])
    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise ValidationError('This username is unavailable.')
        return username


class EnrollmentForm(forms.Form):
    term = forms.ModelChoiceField(queryset=Term.objects.none())
    class_stream = forms.ModelChoiceField(queryset=ClassStream.objects.none())
    action = forms.ChoiceField(choices=[('enroll', 'Enroll / change stream'), ('complete', 'Complete term'), ('transfer', 'Transfer out'), ('withdraw', 'Withdraw')])
    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['term'].queryset = Term.objects.filter(school=school, academic_year__school=school).select_related('academic_year')
        self.fields['class_stream'].queryset = ClassStream.objects.filter(school=school)


class StaffMembershipForm(forms.Form):
    role = forms.ChoiceField(choices=[('teacher', 'Teacher'), ('accountant', 'Accountant')])
    is_active = forms.BooleanField(required=False)


class YearForm(forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ['name']
    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.school = school


class TermForm(forms.ModelForm):
    class Meta:
        model = Term
        fields = ['academic_year', 'name']
    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.school = school
        self.fields['academic_year'].queryset = AcademicYear.objects.filter(school=school)


class SchoolPasswordResetForm(PasswordResetForm):
    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):
        from django.template.loader import render_to_string
        from tenants.admin_services import deliver_account_mail
        subject = ''.join(render_to_string(subject_template_name, context).splitlines())
        body = render_to_string(email_template_name, context)
        html = render_to_string(html_email_template_name, context) if html_email_template_name else None
        deliver_account_mail(subject, body, to_email, from_email, html)

    def get_users(self, email):
        # Support unusable-password invitations, but fail closed for ambiguous email.
        from django.core.validators import validate_email
        try:
            validate_email(email)
        except ValidationError:
            return []
        matches = list(get_user_model().objects.filter(email__iexact=email, is_active=True, is_staff=False, is_superuser=False)[:2])
        if len(matches) != 1:
            return []
        user = matches[0]
        memberships = list(SchoolMembership.objects.filter(user=user).select_related('school')[:2])
        if len(memberships) != 1 or not memberships[0].is_active or memberships[0].school.status != 'approved':
            return []
        return [user]


class RolloverForm(forms.Form):
    source = forms.ModelChoiceField(queryset=Term.objects.none())
    target = forms.ModelChoiceField(queryset=Term.objects.none())
    target_class = forms.ModelChoiceField(queryset=ClassStream.objects.none(), required=False,
        help_text='Leave blank to preserve each student\'s class.')
    confirm = forms.BooleanField(label='Create new enrollments and mark source enrollments completed')
    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        periods = Term.objects.filter(school=school, academic_year__school=school).select_related('academic_year')
        self.fields['source'].queryset = periods
        self.fields['target'].queryset = periods
        self.fields['target_class'].queryset = ClassStream.objects.filter(school=school)
    def clean(self):
        data = super().clean()
        source, target = data.get('source'), data.get('target')
        if source and target and (target.academic_year.name, target.name) <= (source.academic_year.name, source.name):
            raise ValidationError('The target term must follow the source term.')
        return data


class TeacherReassignmentForm(forms.Form):
    teacher = forms.ModelChoiceField(queryset=get_user_model().objects.none())
    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['teacher'].queryset = get_user_model().objects.filter(
            is_active=True, is_staff=False, is_superuser=False,
            school_memberships__school=school, school_memberships__role='teacher',
            school_memberships__is_active=True)


class NoticeForm(forms.ModelForm):
    class Meta:
        model = __import__('core.models', fromlist=['Notice']).Notice
        fields = ['title', 'content', 'target_class', 'expires_at']
        widgets = {'expires_at': forms.DateInput(attrs={'type': 'date'})}
    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.school = school
        self.fields['target_class'].queryset = ClassStream.objects.filter(school=school)
