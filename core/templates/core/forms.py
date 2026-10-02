from django import forms
from .models import DailyClassAttendance, Payment

class DailyAttendanceForm(forms.ModelForm):
    class Meta:
        model = DailyClassAttendance
        fields = ['status']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-control bg-dark text-light border-secondary'})
        }

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