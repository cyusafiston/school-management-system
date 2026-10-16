from datetime import date
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Attendance, DailyClassAttendance, Homework, StudentEnrollment
from tenants.models import SchoolMembership
from tenants.teacher_test_fixtures import TeacherWorkflowFixture


class TeacherAttendanceHomeworkTests(TeacherWorkflowFixture, TestCase):
    def setUp(self):
        self.client.force_login(self.teachers[0])
        self.assignment = self.assignments[0]
        self.subject_url = reverse('take_attendance', args=[self.assignment.pk])
        self.daily_url = reverse('take_daily_attendance_class', args=[self.assignment.current_class_id])
        self.homework_url = reverse('teacher_homework', args=[self.assignment.pk])
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)

    def attendance_data(self, **extra):
        return {**{f'status_{s.pk}': 'Present' for s in self.students[0]}, **extra}

    def homework_data(self, **extra):
        return {'title': 'Fractions', 'description': 'Complete exercises 1–4.', 'due_date': '2026-11-01', **extra}

    def homework(self, index=0, **extra):
        return Homework.objects.create(school=self.schools[index], assignment=self.assignments[index], title='Fractions', description='Practice', due_date=date(2026, 11, 1), **extra)

    def test_subject_attendance_create_and_update(self):
        self.assertEqual(self.client.post(self.subject_url, self.attendance_data(attendance_date='2026-10-15')).status_code, 302)
        self.assertEqual(Attendance.objects.count(), 2)
        self.client.post(self.subject_url, self.attendance_data(attendance_date='2026-10-15', **{f'status_{self.students[0][0].pk}': 'Late'}))
        self.assertEqual(Attendance.objects.count(), 2)
        record = Attendance.objects.get(student=self.students[0][0])
        self.assertEqual(record.status, 'Late')
        self.assertEqual(record.recorded_by, self.teachers[0])
        response = self.client.get(self.subject_url, {'date': '2026-10-15'})
        self.assertContains(response, 'value="2026-10-15"')
        self.assertEqual(response.context['student_data'][0]['status'], 'Late')

    def test_subject_invalid_status_is_atomic(self):
        self.client.post(self.subject_url, self.attendance_data(**{f'status_{self.students[0][1].pk}': 'invalid'}))
        self.assertFalse(Attendance.objects.exists())

    def test_subject_invalid_date(self):
        self.assertEqual(self.client.get(self.subject_url, {'date': 'bad'}).status_code, 404)
        self.client.post(self.subject_url, self.attendance_data(attendance_date='bad'))
        self.assertFalse(Attendance.objects.exists())

    def test_subject_uses_enrollment_not_profile_class(self):
        student = self.students[0][0]
        type(student).objects.filter(pk=student.pk).update(current_class=None)
        StudentEnrollment.objects.filter(student=self.students[0][1]).update(status='Transferred')
        response = self.client.get(self.subject_url)
        self.assertEqual([row['student'].pk for row in response.context['student_data']], [student.pk])
        self.client.post(self.subject_url, {f'status_{student.pk}': 'Absent', f'status_{self.students[1][0].pk}': 'Present'})
        self.assertEqual(list(Attendance.objects.values_list('student_id', flat=True)), [student.pk])

    def test_daily_create_lock_and_repeat_preserves_records(self):
        self.assertEqual(self.client.post(self.daily_url, self.attendance_data()).status_code, 302)
        self.assertEqual(DailyClassAttendance.objects.count(), 2)
        self.assertFalse(DailyClassAttendance.objects.filter(is_locked=False).exists())
        self.client.post(self.daily_url, {f'status_{s.pk}': 'Absent' for s in self.students[0]})
        self.assertEqual(DailyClassAttendance.objects.filter(status='Present').count(), 2)

    def test_daily_invalid_status_is_atomic(self):
        self.client.post(self.daily_url, self.attendance_data(**{f'status_{self.students[0][1].pk}': 'invalid'}))
        self.assertFalse(DailyClassAttendance.objects.exists())

    def test_daily_only_active_current_term_enrollments(self):
        StudentEnrollment.objects.filter(student=self.students[0][1]).update(status='Transferred')
        self.client.post(self.daily_url, self.attendance_data())
        self.assertEqual(list(DailyClassAttendance.objects.values_list('student_id', flat=True)), [self.students[0][0].pk])
        type(self.assignment.term).objects.filter(pk=self.assignment.term_id).update(is_current=False)
        self.assertEqual(self.client.get(self.daily_url).status_code, 404)

    def test_daily_without_class_rejects_post(self):
        self.assertEqual(self.client.post(reverse('take_daily_attendance'), {}).status_code, 400)

    def test_foreign_assignment_and_class_rejected(self):
        for name, pk in [('take_attendance', self.assignments[1].pk), ('teacher_homework', self.assignments[1].pk), ('take_daily_attendance_class', self.assignments[1].current_class_id)]:
            url = reverse(name, args=[pk])
            with self.subTest(name=name):
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(self.client.post(url, self.attendance_data()).status_code, 404)
        self.assertFalse(Attendance.objects.exists())
        self.assertFalse(DailyClassAttendance.objects.exists())
        self.assertFalse(Homework.objects.exists())

    def test_inactive_membership_denies_all_workflows(self):
        SchoolMembership.objects.filter(user=self.teachers[0]).update(is_active=False)
        for url in (self.subject_url, self.daily_url, self.homework_url):
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_wrong_role_denies_all_workflows(self):
        SchoolMembership.objects.filter(user=self.teachers[0]).update(role='accountant')
        for url in (self.subject_url, self.daily_url, self.homework_url):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_anonymous_redirects_and_csrf_rejects_posts(self):
        self.client.logout()
        for url in (self.subject_url, self.daily_url, self.homework_url):
            self.assertEqual(self.client.get(url).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.teachers[0])
        for url in (self.subject_url, self.daily_url, self.homework_url):
            self.assertEqual(client.post(url, {}).status_code, 403)

    def test_homework_create_ignores_posted_school_and_assignment(self):
        self.assertEqual(self.client.post(self.homework_url, self.homework_data(school=self.schools[1].pk, assignment=self.assignments[1].pk)).status_code, 302)
        homework = Homework.objects.get()
        self.assertEqual(homework.school, self.schools[0])
        self.assertEqual(homework.assignment, self.assignment)

    def test_homework_validation_retains_input(self):
        for data in ({}, self.homework_data(due_date='bad'), self.homework_data(title=' '), self.homework_data(title='X'*256)):
            with self.subTest(data=data):
                response = self.client.post(self.homework_url, data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
                self.assertFalse(Homework.objects.exists())

    def test_homework_edit_and_list_isolation(self):
        own = self.homework()
        other = self.homework(1)
        response = self.client.post(reverse('teacher_homework_edit', args=[self.assignment.pk, own.pk]), self.homework_data(title='Updated'))
        self.assertEqual(response.status_code, 302)
        own.refresh_from_db()
        self.assertEqual(own.title, 'Updated')
        response = self.client.get(self.homework_url)
        self.assertEqual(list(response.context['homeworks']), [own])
        for route in ('teacher_homework_edit', 'teacher_homework_delete', 'teacher_homework_download'):
            url = reverse(route, args=[self.assignment.pk, other.pk])
            self.assertEqual(self.client.post(url, self.homework_data()).status_code, 404)
        other.refresh_from_db()
        self.assertEqual(other.title, 'Fractions')

    def test_homework_delete_requires_post(self):
        own = self.homework()
        url = reverse('teacher_homework_delete', args=[self.assignment.pk, own.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(Homework.objects.filter(pk=own.pk).exists())
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(Homework.objects.exists())

    def test_homework_attachment_download_authorized(self):
        attachment = SimpleUploadedFile('practice.pdf', b'%PDF-1.4 test', content_type='application/pdf')
        self.client.post(self.homework_url, self.homework_data(file=attachment))
        own = Homework.objects.get()
        url = reverse('teacher_homework_download', args=[self.assignment.pk, own.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 test')
        response.close()
        self.client.force_login(self.teachers[1])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_edit_form_does_not_expose_storage_url(self):
        own = self.homework(file=SimpleUploadedFile('practice.pdf', b'%PDF-1.4 test'))
        response = self.client.get(reverse('teacher_homework_edit', args=[self.assignment.pk, own.pk]))
        self.assertNotContains(response, own.file.url)

    def test_disallowed_and_oversize_uploads_rejected(self):
        for attachment in (SimpleUploadedFile('bad.html', b'<script>'), SimpleUploadedFile('large.pdf', b'x'*(10*1024*1024+1))):
            response = self.client.post(self.homework_url, self.homework_data(file=attachment))
            self.assertEqual(response.status_code, 200)
            self.assertIn('file', response.context['form'].errors)
        self.assertFalse(Homework.objects.exists())

    def test_homework_model_rejects_foreign_assignment(self):
        with self.assertRaises(ValidationError):
            Homework.objects.create(school=self.schools[0], assignment=self.assignments[1], title='Bad', description='Bad', due_date=date(2026, 11, 1))

    def test_dashboard_restores_attendance_homework_links(self):
        response = self.client.get(reverse('teacher_dashboard'))
        for url in (self.subject_url, self.homework_url, reverse('take_daily_attendance')):
            self.assertContains(response, url)

    def test_other_teacher_in_school_cannot_manage_homework(self):
        own = self.homework()
        user = get_user_model().objects.create_user(username='unassigned_teacher')
        SchoolMembership.objects.create(school=self.schools[0], user=user, role='teacher')
        self.client.force_login(user)
        for route in ('teacher_homework_edit', 'teacher_homework_delete', 'teacher_homework_download'):
            self.assertEqual(self.client.post(reverse(route, args=[self.assignment.pk, own.pk]), self.homework_data()).status_code, 404)
        self.assertEqual(self.client.get(self.subject_url).status_code, 404)
        self.assertEqual(self.client.get(self.daily_url).status_code, 404)

    def test_inactive_membership_cannot_edit_delete_or_download(self):
        own = self.homework()
        SchoolMembership.objects.filter(user=self.teachers[0]).update(is_active=False)
        for route in ('teacher_homework_edit', 'teacher_homework_delete', 'teacher_homework_download'):
            self.assertEqual(self.client.post(reverse(route, args=[self.assignment.pk, own.pk]), self.homework_data()).status_code, 403)
        self.assertTrue(Homework.objects.filter(pk=own.pk).exists())

    def test_empty_attendance_roster_does_not_create_records(self):
        StudentEnrollment.objects.filter(school=self.schools[0]).update(status='Transferred')
        for url in (self.subject_url, self.daily_url):
            response = self.client.post(url, self.attendance_data())
            self.assertIn(response.status_code, (200, 302))
        self.assertFalse(Attendance.objects.exists())
        self.assertFalse(DailyClassAttendance.objects.exists())

    def test_attachment_survives_edit_without_reupload(self):
        own = self.homework(file=SimpleUploadedFile('practice.pdf', b'%PDF-1.4 test'))
        filename = own.file.name
        self.client.post(reverse('teacher_homework_edit', args=[self.assignment.pk, own.pk]), self.homework_data(title='Revised'))
        own.refresh_from_db()
        self.assertEqual(own.file.name, filename)
        self.assertEqual(own.title, 'Revised')

    def test_classes_show_one_enabled_attendance_and_homework_link(self):
        response = self.client.get(reverse('teacher_classes'))
        self.assertContains(response, f'href="{self.subject_url}"', count=1)
        self.assertContains(response, f'href="{self.homework_url}"', count=1)
        self.assertNotContains(response, 'Attendance (Coming soon)')
        self.assertNotContains(response, 'Homework (Coming soon)')
