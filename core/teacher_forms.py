"""Forms for the school-scoped teacher workflows."""
from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError

from core.models import Homework


class HomeworkForm(forms.ModelForm):
    class Meta:
        model = Homework
        fields = ('title', 'description', 'due_date', 'file')
        widgets = {'due_date': forms.DateInput(attrs={'type': 'date'}), 'file': forms.FileInput()}

    def clean_file(self):
        attachment = self.cleaned_data.get('file')
        if attachment and hasattr(attachment, 'size'):
            if attachment.size > 10 * 1024 * 1024:
                raise ValidationError('Attachments must be 10 MB or smaller.')
            if Path(attachment.name).suffix.lower() not in {'.pdf', '.doc', '.docx', '.png', '.jpg', '.jpeg'}:
                raise ValidationError('Use a PDF, Word document, PNG, or JPEG attachment.')
        return attachment
