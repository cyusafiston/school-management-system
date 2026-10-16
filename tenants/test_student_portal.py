from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from core.models import (AcademicYear, Attendance, ClassStream, ClassSubject,
                         DailyClassAttendance, Grade, Homework, Notice,
                         StudentEnrollment, Subject, Term, UserProfile)
from core.views import student_report_context
from tenants.models import School, SchoolMembership
from tenants.teacher_test_fixtures import TeacherWorkflowFixture


class StudentPortalTests(TeacherWorkflowFixture, TestCase):
    def setUp(self):
        self.student = self.students[0][0]
        self.assignment = self.assignments[0]
        self.client.force_login(self.student.user)
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        settings = override_settings(MEDIA_ROOT=self.media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.pages = ['student_dashboard', 'student_subjects', 'student_grades',
                      'student_homework', 'student_attendance', 'student_notices',
                      'student_schedule', 'student_profile', 'change_password', 'student_report_card']

    def grade(self, student=None, *, cat='24', exam='56', finalized=True, subject=None, term=None):
        student = student or self.student
        assignment = self.assignments[0 if student.school_id == self.schools[0].pk else 1]
        grade = Grade.objects.create(school=student.school, student=student,
            subject=subject or assignment.subject, term=term or assignment.term,
            cat_marks=Decimal(cat), exam_marks=Decimal(exam))
        if finalized:
            grade.status = 'Finalized'
            grade.finalized_by = assignment.teacher
            grade.finalized_at = timezone.now()
            grade.save()
        return grade

    def report(self, **query):
        request = RequestFactory().get('/report/', query)
        request.user = self.student.user
        return student_report_context(request)

    def homework(self, index=0, **extra):
        return Homework.objects.create(school=self.schools[index], assignment=self.assignments[index],
            title=f'Homework {index}', description='Exercises', due_date=date(2026, 11, 1), **extra)

    def extra_subject(self, *, required=True):
        subject = Subject.objects.create(school=self.schools[0], name='ENGLISH', code='ENG-STUDENT',
                                         max_cat_marks=Decimal('30'), max_exam_marks=Decimal('70'))
        ClassSubject.objects.create(school=self.schools[0], academic_year=self.assignment.term.academic_year,
            class_stream=self.assignment.current_class, subject=subject, is_required=required)
        return subject

    def extra_term(self, name='Term 2', *, enrolled=True):
        term = Term.objects.create(school=self.schools[0], academic_year=self.assignment.term.academic_year, name=name)
        if enrolled:
            StudentEnrollment.objects.create(school=self.schools[0], student=self.student,
                academic_year=term.academic_year, term=term, class_stream=self.assignment.current_class,
                status='Completed')
        return term

    def test_all_student_pages_render_and_pdf_is_valid(self):
        for page in self.pages:
            with self.subTest(page=page):
                response = self.client.get(reverse(page))
                self.assertEqual(response.status_code, 200)
                if page == 'student_report_card':
                    self.assertTrue(response.content.startswith(b'%PDF'))
                    self.assertGreaterEqual(len(PdfReader(BytesIO(response.content)).pages), 1)

    def test_student_authentication_redirects_to_student_portal(self):
        user = self.student.user
        user.set_password('StudentTestPassword2026!')
        user.save()
        self.client.logout()
        response = self.client.post(reverse('login'), {'username': user.username, 'password': 'StudentTestPassword2026!'})
        self.assertRedirects(response, reverse('student_dashboard'))

    def test_wrong_password_cannot_authenticate(self):
        self.client.logout()
        response = self.client.post(reverse('login'), {'username': self.student.user.username, 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_membership_role_is_authoritative(self):
        UserProfile.objects.filter(user=self.student.user).update(role='Teacher')
        self.assertEqual(self.client.get(reverse('student_dashboard')).status_code, 200)

    def test_anonymous_users_cannot_access_any_student_page(self):
        self.client.logout()
        for page in self.pages:
            self.assertEqual(self.client.get(reverse(page)).status_code, 302)

    def test_inactive_membership_denies_every_page(self):
        SchoolMembership.objects.filter(user=self.student.user).update(is_active=False)
        for page in self.pages:
            self.assertEqual(self.client.get(reverse(page)).status_code, 403)

    def test_suspended_school_denies_every_page(self):
        School.objects.filter(pk=self.schools[0].pk).update(status='suspended')
        for page in self.pages:
            self.assertEqual(self.client.get(reverse(page)).status_code, 403)

    def test_inactive_user_cannot_access_portal(self):
        get_user_model().objects.filter(pk=self.student.user_id).update(is_active=False)
        self.assertEqual(self.client.get(reverse('student_dashboard')).status_code, 302)

    def test_teacher_cannot_access_student_pages(self):
        self.client.force_login(self.teachers[0])
        for page in self.pages:
            self.assertEqual(self.client.get(reverse(page)).status_code, 403)

    def test_profile_in_other_school_cannot_be_used(self):
        SchoolMembership.objects.filter(user=self.student.user).update(school=self.schools[1])
        self.assertEqual(self.client.get(reverse('student_dashboard')).status_code, 404)

    def test_ambiguous_memberships_fail_closed(self):
        SchoolMembership.objects.create(user=self.student.user, school=self.schools[1], role='student')
        self.assertEqual(self.client.get(reverse('student_dashboard')).status_code, 403)

    def test_current_active_enrollment_required_for_every_page(self):
        StudentEnrollment.objects.filter(student=self.student).update(status='Transferred')
        for page in self.pages:
            self.assertEqual(self.client.get(reverse(page)).status_code, 403)

    def test_no_current_term_denies_portal(self):
        Term.objects.filter(pk=self.assignment.term_id).update(is_current=False)
        self.assertEqual(self.client.get(reverse('student_dashboard')).status_code, 403)

    def test_profile_current_class_is_not_enrollment_context(self):
        StudentProfile = type(self.student)
        StudentProfile.objects.filter(pk=self.student.pk).update(current_class=None)
        response = self.client.get(reverse('student_dashboard'))
        self.assertEqual(response.context['class_stream'], self.assignment.current_class)
        self.assertEqual(response.context['current_term'], self.assignment.term)

    def test_cross_student_and_cross_school_query_overrides_rejected(self):
        for page in self.pages:
            for query in ({'student_id': self.students[0][1].pk}, {'student_id': self.students[1][0].pk}, {'school_id': self.schools[1].pk}):
                with self.subTest(page=page, query=query):
                    self.assertEqual(self.client.get(reverse(page), query).status_code, 404)

    def test_foreign_term_selection_rejected(self):
        for page in self.pages[:-1]:
            self.assertEqual(self.client.get(reverse(page), {'term_id': self.assignments[1].term_id}).status_code, 404)
            self.assertEqual(self.client.get(reverse(page), {'term_id': 'bad'}).status_code, 404)

    def test_enrolled_subjects_and_schedule_are_school_scoped(self):
        response = self.client.get(reverse('student_subjects'))
        self.assertEqual([s.subject_id for s in response.context['subjects']], [self.assignment.subject_id])
        response = self.client.get(reverse('student_schedule'))
        self.assertEqual(list(response.context['assignments']), [self.assignment])
        self.assertContains(response, 'Lesson days, times and rooms are not configured')

    def test_only_own_finalized_grades_are_visible(self):
        own = self.grade()
        self.grade(self.students[0][1])
        self.grade(self.students[1][0])
        for route in ('student_grades', 'student_dashboard'):
            response = self.client.get(reverse(route))
            self.assertEqual(list(response.context['grades_list']), [own])
        self.client.force_login(self.students[0][1].user)
        response = self.client.get(reverse('student_grades'))
        self.assertNotIn(own, response.context['grades_list'])

    def test_draft_grade_hidden_everywhere(self):
        self.grade(finalized=False)
        for route in ('student_grades', 'student_dashboard'):
            self.assertEqual(list(self.client.get(reverse(route)).context['grades_list']), [])
        report = self.report()
        self.assertEqual(report['grades'], [])
        self.assertFalse(report['report_complete'])
        self.assertIsNone(report['average_percentage'])

    def test_historical_grade_requires_enrollment(self):
        term = self.extra_term()
        grade = self.grade(term=term)
        response = self.client.get(reverse('student_grades'), {'term_id': term.pk})
        self.assertEqual(list(response.context['grades_list']), [grade])
        StudentEnrollment.objects.filter(student=self.student, term=term).delete()
        self.assertEqual(self.client.get(reverse('student_grades'), {'term_id': term.pk}).status_code, 404)

    def test_report_existing_cat_exam_and_letter_rules(self):
        self.grade(cat='25', exam='60')
        report = self.report()
        self.assertTrue(report['report_complete'])
        self.assertEqual(report['average_percentage'], Decimal('85.0'))
        self.assertEqual(report['avg_grade_letter'], 'A')
        self.assertEqual(report['table_rows'][0]['terms'][1]['marks_obtained'], Decimal('85'))

    def test_required_missing_result_blocks_overall_average(self):
        self.grade()
        self.extra_subject(required=True)
        report = self.report()
        self.assertFalse(report['report_complete'])
        self.assertIsNone(report['average_percentage'])
        self.assertIn('Incomplete required results', [row['remarks'] for row in report['table_rows']])

    def test_optional_unassessed_subject_does_not_block_average(self):
        self.grade()
        self.extra_subject(required=False)
        report = self.report()
        self.assertTrue(report['report_complete'])
        self.assertEqual(report['average_percentage'], Decimal('80.0'))
        self.assertIn('Optional - not assessed', [row['remarks'] for row in report['table_rows']])

    def test_multiple_subject_average(self):
        self.grade()
        subject = self.extra_subject()
        self.grade(subject=subject, cat='20', exam='40')
        self.assertEqual(self.report()['average_percentage'], Decimal('70.0'))

    def test_cumulative_and_annual_reports(self):
        self.grade()
        term2 = self.extra_term()
        self.grade(term=term2, cat='20', exam='40')
        self.assertEqual(self.report(term='2')['average_percentage'], Decimal('70.0'))
        term3 = self.extra_term('Term 3')
        self.grade(term=term3, cat='10', exam='30')
        report = self.report(term='3')
        self.assertEqual(report['average_percentage'], Decimal('60.0'))
        self.assertEqual(report['report_scope'], 'annual')

    def test_report_requires_every_reporting_enrollment(self):
        self.extra_term(enrolled=False)
        self.assertEqual(self.client.get(reverse('student_report_card'), {'term': '2'}).status_code, 404)

    def test_invalid_report_selection_rejected(self):
        for query in ({'term': '999'}, {'scope': 'bad'}, {'academic_year': self.assignments[1].term.academic_year_id}):
            self.assertEqual(self.client.get(reverse('student_report_card'), query).status_code, 404)

    def test_pdf_contains_only_own_identity_and_finalized_result(self):
        self.grade()
        self.grade(self.students[0][1], cat='20', exam='30')
        response = self.client.get(reverse('student_report_card'))
        text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
        self.assertIn(self.student.first_name, text)
        self.assertNotIn(self.students[0][1].first_name, text)
        self.assertIn('80.0', text)
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_personal_attendance_excludes_other_students(self):
        for student in self.students[0]:
            Attendance.objects.create(school=self.schools[0], student=student, assignment=self.assignment, date=timezone.localdate(), status='Present', recorded_by=self.teachers[0])
            DailyClassAttendance.objects.create(school=self.schools[0], student=student, current_class=self.assignment.current_class, status='Late', submitted_by=self.teachers[0])
        response = self.client.get(reverse('student_attendance'))
        self.assertEqual([r.student_id for r in response.context['subject_attendance']], [self.student.pk])
        self.assertEqual([r.student_id for r in response.context['daily_attendance']], [self.student.pk])
        report = self.report()
        self.assertEqual(report['total_records'], 1)
        self.assertEqual(report['attendance_percentage'], 100.0)

    def test_invalid_attendance_filters_return_404(self):
        for query in ({'month': '0'}, {'month': '13'}, {'year': '10000'}, {'year': 'bad'}):
            self.assertEqual(self.client.get(reverse('student_attendance'), query).status_code, 404)

    def test_homework_only_for_enrolled_curriculum_and_term(self):
        own = self.homework()
        self.homework(1)
        response = self.client.get(reverse('student_homework'))
        self.assertEqual(list(response.context['homework_list']), [own])
        ClassSubject.objects.filter(school=self.schools[0]).delete()
        self.assertEqual(list(self.client.get(reverse('student_homework')).context['homework_list']), [])

    def test_homework_download_and_cross_school_denial(self):
        own = self.homework(file=SimpleUploadedFile('exercise.pdf', b'%PDF-1.4 exercises'))
        foreign = self.homework(1, file=SimpleUploadedFile('foreign.pdf', b'%PDF-1.4 private'))
        response = self.client.get(reverse('student_homework_download', args=[own.pk]))
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 exercises')
        self.assertIn('attachment;', response['Content-Disposition'])
        response.close()
        self.assertEqual(self.client.get(reverse('student_homework_download', args=[foreign.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('student_homework')), own.file.url)

    def test_same_school_other_class_cannot_download_homework(self):
        own = self.homework(file=SimpleUploadedFile('exercise.pdf', b'%PDF-1.4'))
        other_class = ClassStream.objects.create(school=self.schools[0], name='PRIMARY 2', code='P2-STUDENT')
        StudentEnrollment.objects.filter(student=self.student).update(class_stream=other_class)
        self.assertEqual(self.client.get(reverse('student_homework_download', args=[own.pk])).status_code, 404)

    def test_revoked_membership_blocks_download(self):
        own = self.homework(file=SimpleUploadedFile('exercise.pdf', b'%PDF-1.4'))
        SchoolMembership.objects.filter(user=self.student.user).update(is_active=False)
        self.assertEqual(self.client.get(reverse('student_homework_download', args=[own.pk])).status_code, 403)

    def test_notices_school_class_and_expiry(self):
        today = timezone.localdate()
        general = Notice.objects.create(school=self.schools[0], title='General', content='For school')
        targeted = Notice.objects.create(school=self.schools[0], target_class=self.assignment.current_class, title='Class notice', content='For class', expires_at=today)
        Notice.objects.create(school=self.schools[0], title='Expired', content='Old', expires_at=today-timedelta(days=1))
        Notice.objects.create(school=self.schools[1], title='Foreign', content='Other school')
        other_class = ClassStream.objects.create(school=self.schools[0], name='PRIMARY 2', code='P2-NOTICE')
        Notice.objects.create(school=self.schools[0], target_class=other_class, title='Other class', content='Other class')
        response = self.client.get(reverse('student_notices'))
        self.assertEqual(set(response.context['notices']), {general, targeted})
        dashboard = self.client.get(reverse('student_dashboard'))
        self.assertEqual(set(dashboard.context['recent_notices']), {general, targeted})

    def test_teacher_to_student_publication_workflow(self):
        self.client.force_login(self.teachers[0])
        response = self.client.post(reverse('input_grades', args=[self.assignment.pk]), {f'cat_{self.student.pk}': '24', f'exam_{self.student.pk}': '56'})
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.student.user)
        self.assertEqual(list(self.client.get(reverse('student_grades')).context['grades_list']), [])
        grade = Grade.objects.get(student=self.student)
        self.client.force_login(self.teachers[0])
        self.assertEqual(self.client.post(reverse('finalize_grade', args=[self.assignment.pk, grade.pk]), {'confirm_finalize': 'yes'}).status_code, 302)
        self.client.post(reverse('take_attendance', args=[self.assignment.pk]), {f'status_{s.pk}': 'Present' for s in self.students[0]})
        self.assertEqual(self.client.post(reverse('teacher_homework', args=[self.assignment.pk]), {'title': 'Published lesson', 'description': 'Read chapter 1', 'due_date': '2026-11-01'}).status_code, 302)
        self.client.force_login(self.student.user)
        self.assertEqual(list(self.client.get(reverse('student_grades')).context['grades_list']), [grade])
        self.assertContains(self.client.get(reverse('student_homework')), 'Published lesson')
        self.assertEqual(self.client.get(reverse('student_attendance')).context['subject_attendance'].count(), 1)
        self.client.force_login(self.students[1][0].user)
        self.assertNotContains(self.client.get(reverse('student_homework')), 'Published lesson')

    def test_password_change_validates_old_password_and_preserves_session(self):
        user = self.student.user
        user.set_password('OldStudentPassword2026!')
        user.save()
        self.client.force_login(user)
        url = reverse('change_password')
        data = {'old_password': 'wrong', 'new_password1': 'NewStudentPassword2026!', 'new_password2': 'NewStudentPassword2026!'}
        self.assertEqual(self.client.post(url, data).status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password('OldStudentPassword2026!'))
        data['old_password'] = 'OldStudentPassword2026!'
        self.assertEqual(self.client.post(url, data).status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password('NewStudentPassword2026!'))
        self.assertEqual(self.client.get(reverse('student_dashboard')).status_code, 200)

    def test_password_change_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.student.user)
        self.assertEqual(client.post(reverse('change_password'), {}).status_code, 403)

    def test_readonly_academic_views_reject_posts(self):
        for page in self.pages:
            if page != 'change_password':
                self.assertEqual(self.client.post(reverse(page), {}).status_code, 405)
        self.assertFalse(Grade.objects.exists())
        self.assertFalse(Homework.objects.exists())

    def test_unconfigured_finalized_result_blocks_report(self):
        self.grade()
        subject = self.extra_subject()
        ClassSubject.objects.filter(subject=subject).delete()
        self.grade(subject=subject)
        report = self.report()
        self.assertFalse(report['report_complete'])
        self.assertIsNone(report['average_percentage'])
        self.assertIn('Subject not configured in curriculum', [row['remarks'] for row in report['table_rows']])

    def test_grade_letter_boundaries_follow_existing_scale(self):
        for marks, letter in [('80', 'A'), ('70', 'B'), ('60', 'C'), ('50', 'D'), ('49', 'F')]:
            with self.subTest(marks=marks):
                Grade.objects.all().delete()
                self.grade(cat='10', exam=str(Decimal(marks)-10))
                self.assertEqual(self.report()['avg_grade_letter'], letter)

    def test_report_refuses_foreign_term_id_override(self):
        self.assertEqual(self.client.get(reverse('student_report_card'), {'term_id': self.assignments[1].term_id}).status_code, 404)

    def test_malformed_cross_school_enrollment_fails_closed(self):
        StudentEnrollment.objects.filter(student=self.student).update(class_stream=self.assignments[1].current_class)
        self.assertEqual(self.client.get(reverse('student_dashboard')).status_code, 403)

    def test_malformed_attendance_assignment_is_hidden(self):
        Attendance.objects.bulk_create([Attendance(school=self.schools[0], student=self.student,
            assignment=self.assignments[1], date=timezone.localdate(), status='Absent', recorded_by=self.teachers[1])])
        response = self.client.get(reverse('student_attendance'))
        self.assertEqual(response.context['subject_attendance'].count(), 0)
        self.assertEqual(self.report()['total_records'], 0)

    def test_malformed_grade_tenant_is_hidden(self):
        grade = self.grade()
        Grade.objects.filter(pk=grade.pk).update(school=self.schools[1])
        self.assertEqual(self.client.get(reverse('student_grades')).context['grades_list'].count(), 0)
        self.assertEqual(self.report()['grades'], [])

    def test_current_context_pages_reject_historical_term_override(self):
        term = self.extra_term()
        for route in ('student_dashboard', 'student_notices', 'student_profile', 'change_password'):
            self.assertEqual(self.client.get(reverse(route), {'term_id': term.pk}).status_code, 404)

    def test_platform_superuser_denied_student_pages(self):
        user = get_user_model().objects.create_superuser(username='student_platform_test', email='platform@example.com', password='PlatformTestPassword2026!')
        self.client.force_login(user)
        for route in self.pages:
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)

    def test_missing_attachment_is_404(self):
        record = self.homework()
        self.assertEqual(self.client.get(reverse('student_homework_download', args=[record.pk])).status_code, 404)

    def test_report_uses_finalized_values_after_subject_maxima_change(self):
        self.grade()
        Subject.objects.filter(pk=self.assignment.subject_id).update(max_cat_marks=Decimal('60'), max_exam_marks=Decimal('100'))
        report = self.report()
        row = report['table_rows'][0]['terms'][1]
        self.assertEqual(row['max_marks'], Decimal('100'))
        self.assertEqual(row['percentage'], Decimal('80'))
        self.assertEqual(report['average_percentage'], Decimal('80.0'))
        response = self.client.get(reverse('student_report_card'))
        text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
        self.assertIn('80.0/100.0', text)
        self.assertNotIn('24.0/60.0', text)
        self.assertNotIn('56.0/100.0', text)
