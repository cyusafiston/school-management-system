"""One real HTTP workflow through all completed milestones using synthetic data."""
from decimal import Decimal
from tempfile import TemporaryDirectory
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.contrib.admin.models import LogEntry

from core.models import (AcademicYear, Term, ClassStream, Subject, ClassSubject, TeacherAssignment,
                         StudentProfile, Attendance, Homework, Grade, FeeCategory, StudentFee, Payment)
from tenants.models import School, SchoolMembership


class PilotEndToEndTests(TestCase):
    def test_application_through_report_card_and_payment_with_negative_boundaries(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media,
                STORAGES={'default': {'BACKEND': 'core.private_storage.PrivateDocumentStorage'},
                          'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}},
                MIDDLEWARE=[*settings.MIDDLEWARE, 'tenants.audit.AuditMiddleware',
                            'tenants.pilot_middleware.TenantWriteGuardMiddleware'],
                ACCOUNT_PUBLIC_ORIGIN='https://portal.example.com'):
            self.assertEqual(self.client.post(reverse('register_school'), {
                'school_name': 'Complete Pilot School', 'username': 'pilot-owner',
                'email': 'pilot-owner@example.com', 'password1': 'PilotInitialPassword2026!',
                'password2': 'PilotInitialPassword2026!'}).status_code, 302)
            school = School.objects.get(name='Complete Pilot School')
            owner = school.created_by
            self.client.force_login(owner)
            self.assertEqual(self.client.get(reverse('school_home')).status_code, 403)
            operator = get_user_model().objects.create_superuser(username='pilot-operator')
            self.client.force_login(operator)
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.client.post(reverse('platform_schools'), {'school_id': school.pk,
                    'action': 'approve', 'confirm': 'yes'}).status_code, 302)
            self.assertIn('https://portal.example.com/reset/', mail.outbox[-1].body)
            # Exercise the actual single-use administrator setup link.
            uid = urlsafe_base64_encode(force_bytes(owner.pk))
            token = default_token_generator.make_token(owner)
            self.client.logout()
            response = self.client.get(reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token}))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.client.post(response.url, {'new_password1': 'PilotNewAdminPassword2026!',
                'new_password2': 'PilotNewAdminPassword2026!'}).status_code, 302)
            self.assertTrue(self.client.login(username='pilot-owner', password='PilotNewAdminPassword2026!'))
            owner.refresh_from_db()  # force_login later must use the new session auth hash.
            self.assertEqual(self.client.get(reverse('school_setup_checklist')).status_code, 200)
            self.assertEqual(self.client.post(reverse('admin_periods'), {'action': 'create_year', 'name': '2026-2027'}).status_code, 302)
            year = AcademicYear.objects.get(school=school)
            self.assertEqual(self.client.post(reverse('admin_periods'), {'action': 'create_term',
                'academic_year': year.pk, 'name': 'Term 1'}).status_code, 302)
            term = Term.objects.get(school=school)
            self.assertEqual(self.client.post(reverse('admin_activate_term', args=[term.pk]), {'confirm': 'yes'}).status_code, 302)
            self.assertEqual(self.client.post(reverse('academic_setup'), {'action': 'create_class', 'name': 'PRIMARY 1'}).status_code, 302)
            stream = ClassStream.objects.get(school=school)
            self.assertEqual(self.client.post(reverse('academic_setup'), {'action': 'create_subject',
                'name': 'MATHEMATICS', 'max_cat_marks': '30', 'max_exam_marks': '70'}).status_code, 302)
            subject = Subject.objects.get(school=school)
            self.assertEqual(self.client.post(reverse('curriculum_management'), {'academic_year': year.pk,
                'class_stream': stream.pk, 'subject': subject.pk, 'is_required': 'on'}).status_code, 302)
            for role in ('teacher', 'accountant'):
                with self.captureOnCommitCallbacks(execute=True):
                    self.assertEqual(self.client.post(reverse('admin_staff'), {'username': f'pilot-{role}',
                        'email': f'{role}@example.com', 'first_name': 'Pilot', 'last_name': role, 'role': role}).status_code, 302)
            teacher = get_user_model().objects.get(username='pilot-teacher')
            accountant = get_user_model().objects.get(username='pilot-accountant')
            self.assertFalse(teacher.has_usable_password())
            self.assertEqual(self.client.post(reverse('teacher_assignment_management'), {'teacher': teacher.pk,
                'current_class': stream.pk, 'subject': subject.pk, 'term': term.pk}).status_code, 302)
            assignment = TeacherAssignment.objects.get(school=school)
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.client.post(reverse('admin_students'), {'first_name': 'Pilot',
                    'last_name': 'Child', 'date_of_birth': '2016-01-01', 'gender': 'Female',
                    'current_class': stream.pk, 'email': 'child@example.com'}).status_code, 302)
            student = StudentProfile.objects.get(school=school)
            self.assertTrue(self.client.get(reverse('school_setup_checklist')).context['complete'])
            # Configuration cannot assign foreign-school objects.
            foreign = School.objects.create(name='Other Pilot', status='approved')
            foreign_class = ClassStream.objects.create(school=foreign, name='PRIMARY 1', code='FP1')
            response = self.client.post(reverse('admin_students'), {'first_name': 'Foreign',
                'last_name': 'Attempt', 'date_of_birth': '2016-01-01', 'gender': 'Male',
                'current_class': foreign_class.pk, 'email': 'foreign@example.com'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(StudentProfile.objects.filter(school=school).count(), 1)
            self.client.force_login(teacher)
            self.assertEqual(self.client.post(reverse('take_attendance', args=[assignment.pk]), {
                'attendance_date': timezone.localdate().isoformat(), f'status_{student.pk}': 'Present'}).status_code, 302)
            self.assertEqual(Attendance.objects.get().student, student)
            self.assertEqual(self.client.post(reverse('teacher_homework', args=[assignment.pk]), {
                'title': 'Fractions', 'description': 'Practice fractions', 'due_date': '2026-11-01',
                'file': SimpleUploadedFile('fractions.pdf', b'%PDF-1.4\nprivate homework', content_type='application/pdf')}).status_code, 302)
            homework = Homework.objects.get(school=school)
            self.assertIn(f'schools/{school.pk}/homework/', homework.file.name)
            with self.assertRaises(ValueError):
                _ = homework.file.url
            self.assertEqual(self.client.post(reverse('input_grades', args=[assignment.pk]), {
                f'cat_{student.pk}': '24', f'exam_{student.pk}': '56'}).status_code, 302)
            grade = Grade.objects.get(student=student)
            self.assertEqual(grade.status, 'Draft')
            self.client.force_login(student.user)
            self.assertNotContains(self.client.get(reverse('student_grades')), '80.00')
            self.client.force_login(teacher)
            self.assertEqual(self.client.post(reverse('finalize_grade', args=[assignment.pk, grade.pk]), {'confirm_finalize': 'yes'}).status_code, 302)
            self.client.force_login(student.user)
            self.assertContains(self.client.get(reverse('student_grades')), 'MATHEMATICS')
            response = self.client.get(reverse('student_report_card'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'application/pdf')
            response = self.client.get(reverse('student_homework_download', args=[homework.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4\nprivate homework')
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            self.assertEqual(self.client.post(reverse('record_payment'), {}).status_code, 403)
            self.client.force_login(owner)
            self.assertEqual(self.client.post(reverse('fee_configuration'), {'action': 'create_category', 'name': 'Tuition'}).url, reverse('fee_configuration'))
            category = FeeCategory.objects.get(school=school)
            self.assertEqual(self.client.post(reverse('fee_configuration'), {'action': 'create_structure',
                'academic_year': year.pk, 'term': term.pk, 'class_stream': stream.pk,
                'category': category.pk, 'amount': '100.30'}).status_code, 302)
            self.assertEqual(self.client.post(reverse('fee_configuration'), {'action': 'generate_fees', 'term': term.pk}).status_code, 302)
            self.assertEqual(StudentFee.objects.get(student=student).total_expected, Decimal('100.30'))
            self.client.force_login(accountant)
            token = self.client.get(reverse('record_payment')).context['form'].initial['submission_token']
            data = {'student': student.pk, 'academic_year': year.pk, 'term': term.pk,
                'amount_paid': '100.30', 'payment_method': 'Bank Deposit', 'reference_number': 'PILOT-RECEIPT-1',
                'submission_token': token}
            receipt = self.client.post(reverse('record_payment'), data)
            self.assertEqual(receipt.status_code, 302)
            self.assertContains(self.client.get(receipt.url), '100.30 RWF')
            self.assertEqual(self.client.post(reverse('record_payment'), data).url, receipt.url)
            self.assertEqual(Payment.objects.count(), 1)
            self.client.force_login(student.user)
            self.assertEqual(self.client.get(reverse('student_finances')).context['balance'], Decimal('0'))
            self.client.force_login(operator)
            self.client.post(reverse('platform_schools'), {'school_id': school.pk, 'action': 'suspend', 'confirm': 'yes'})
            for user, route in ((student.user, 'student_dashboard'), (teacher, 'teacher_dashboard'),
                                (accountant, 'accountant_dashboard'), (owner, 'school_home')):
                self.client.force_login(user)
                self.assertEqual(self.client.get(reverse(route)).status_code, 403)
            self.client.force_login(teacher)
            self.assertEqual(self.client.get(reverse('teacher_homework_download', args=[assignment.pk, homework.pk])).status_code, 403)
            self.client.force_login(operator)
            self.client.post(reverse('platform_schools'), {'school_id': school.pk, 'action': 'reactivate', 'confirm': 'yes'})
            self.client.force_login(student.user)
            self.assertEqual(self.client.get(reverse('student_dashboard')).status_code, 200)
            self.assertEqual(Payment.objects.count(), 1)
            self.assertEqual(Grade.objects.get().status, 'Finalized')
            for model in ('Payment', 'Grade', 'SchoolMembership'):
                self.assertTrue(LogEntry.objects.filter(change_message__contains=f'"model": "{model}"').exists())
            self.assertFalse(LogEntry.objects.filter(change_message__contains='PilotNewAdminPassword').exists())
