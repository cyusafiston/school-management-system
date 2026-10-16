"""Regression coverage rebuilt from GitHub; not a copy of the local checkpoint."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import (AcademicYear, ClassStream, ClassSubject, Grade,
                         StudentEnrollment, StudentProfile, Subject,
                         TeacherAssignment, Term)
from tenants.models import School, SchoolMembership


from tenants.teacher_test_fixtures import TeacherWorkflowFixture


class TeacherGradingWorkflowTests(TeacherWorkflowFixture, TestCase):
    def setUp(self):
        self.client.force_login(self.teachers[0])
        self.assignment = self.assignments[0]
        self.url = reverse('input_grades', args=[self.assignment.pk])

    def marks(self, student=None, cat='24', exam='56'):
        student = student or self.students[0][0]
        return {f'cat_{student.pk}': cat, f'exam_{student.pk}': exam}

    def grade(self, index=0):
        assignment = self.assignments[index]
        return Grade.objects.create(school=self.schools[index], student=self.students[index][0], subject=assignment.subject, term=assignment.term, cat_marks=Decimal('24'), exam_marks=Decimal('56'))

    def finalize(self, grade, data=None):
        return self.client.post(reverse('finalize_grade', args=[self.assignment.pk, grade.pk]), {'confirm_finalize': 'yes'} if data is None else data)

    def test_saves_and_calculates_grade(self):
        self.assertEqual(self.client.post(self.url, self.marks()).status_code, 302)
        grade = Grade.objects.get()
        self.assertEqual(grade.status, "Draft")
        self.assertEqual((grade.cat_marks, grade.exam_marks), (Decimal("24"), Decimal("56")))
        self.assertEqual((grade.marks_obtained, grade.percentage, grade.grade_letter), (Decimal('80'), Decimal('80'), 'A'))
        self.assertEqual(grade.school, self.schools[0])

    def test_finalization_records_actor_and_time(self):
        grade = self.grade()
        self.assertEqual(self.finalize(grade).status_code, 302)
        grade.refresh_from_db()
        self.assertEqual(grade.status, 'Finalized')
        self.assertEqual(grade.finalized_by, self.teachers[0])
        self.assertIsNotNone(grade.finalized_at)

    def test_finalization_requires_confirmation(self):
        grade = self.grade()
        self.assertEqual(self.finalize(grade, {}).status_code, 400)
        grade.refresh_from_db()
        self.assertEqual(grade.status, 'Draft')

    def test_repeated_finalization_preserves_audit(self):
        grade = self.grade()
        self.finalize(grade)
        grade.refresh_from_db()
        timestamp = grade.finalized_at
        self.assertEqual(self.finalize(grade).status_code, 400)
        grade.refresh_from_db()
        self.assertEqual(grade.finalized_at, timestamp)

    def test_foreign_grade_cannot_be_finalized(self):
        grade = self.grade(1)
        self.assertEqual(self.finalize(grade).status_code, 404)
        grade.refresh_from_db()
        self.assertEqual(grade.status, 'Draft')

    def test_finalization_requires_post(self):
        grade = self.grade()
        self.assertEqual(self.client.get(reverse('finalize_grade', args=[self.assignment.pk, grade.pk])).status_code, 405)

    def test_locked_row_does_not_block_other_draft(self):
        grade = self.grade()
        self.finalize(grade)
        data = self.marks()
        data.update(self.marks(self.students[0][1], cat='20', exam='50'))
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertEqual(Grade.objects.count(), 2)
        grade.refresh_from_db()
        self.assertEqual(grade.status, 'Finalized')

    def test_tampered_finalized_marks_reject_entire_batch(self):
        grade = self.grade()
        self.finalize(grade)
        data = self.marks(cat='25')
        data.update(self.marks(self.students[0][1]))
        self.assertEqual(self.client.post(self.url, data).status_code, 200)
        self.assertEqual(Grade.objects.count(), 1)
        grade.refresh_from_db()
        self.assertEqual(grade.cat_marks, Decimal('24'))

    def test_invalid_numeric_values_leave_no_records(self):
        for value in ('NaN', 'Infinity', '-1', '31', 'abc', '1.234'):
            with self.subTest(value=value):
                self.assertEqual(self.client.post(self.url, self.marks(cat=value)).status_code, 200)
                self.assertFalse(Grade.objects.exists())

    def test_invalid_row_rolls_back_batch(self):
        data = self.marks()
        data.update(self.marks(self.students[0][1], exam='71'))
        self.client.post(self.url, data)
        self.assertFalse(Grade.objects.exists())

    def test_cross_school_assignment_rejected_for_get_and_post(self):
        url = reverse('input_grades', args=[self.assignments[1].pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, self.marks(self.students[1][0])).status_code, 404)
        self.assertFalse(Grade.objects.exists())

    def test_foreign_student_fields_cannot_create_foreign_grade(self):
        self.client.post(self.url, self.marks(self.students[1][0]))
        self.assertFalse(Grade.objects.exists())

    def test_inactive_membership_blocks_grades_and_finalization(self):
        grade = self.grade()
        SchoolMembership.objects.filter(user=self.teachers[0]).update(is_active=False)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.finalize(grade).status_code, 403)

    def test_student_role_cannot_enter_grades(self):
        self.client.force_login(self.students[0][0].user)
        self.assertEqual(self.client.post(self.url, self.marks()).status_code, 403)

    def test_suspended_school_blocks_teacher(self):
        School.objects.filter(pk=self.schools[0].pk).update(status='suspended')
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_missing_curriculum_blocks_grading(self):
        ClassSubject.objects.filter(school=self.schools[0]).delete()
        self.assertEqual(self.client.post(self.url, self.marks()).status_code, 403)

    def test_inactive_enrollment_cannot_be_graded_or_finalized(self):
        grade = self.grade()
        StudentEnrollment.objects.filter(student=grade.student).update(status='Transferred')
        self.client.post(self.url, self.marks(cat='25'))
        self.assertEqual(self.finalize(grade).status_code, 404)
        grade.refresh_from_db()
        self.assertEqual(grade.cat_marks, Decimal('24'))

    def test_roster_excludes_foreign_and_inactive_students(self):
        StudentEnrollment.objects.filter(student=self.students[0][1]).update(status='Transferred')
        response = self.client.get(reverse('class_students', args=[self.assignment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['student'].pk for row in response.context['student_data']], [self.students[0][0].pk])

    def test_dashboard_links_to_secured_workflows(self):
        response = self.client.get(reverse('teacher_dashboard'))
        self.assertContains(response, self.url)
        self.assertContains(response, reverse('class_students', args=[self.assignment.pk]))

    def test_other_teacher_in_same_school_cannot_use_assignment(self):
        user = get_user_model().objects.create_user(username='other_teacher')
        SchoolMembership.objects.create(school=self.schools[0], user=user, role='teacher')
        self.client.force_login(user)
        grade = self.grade()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.finalize(grade).status_code, 404)

    def test_platform_superuser_cannot_use_teacher_workflow(self):
        user = get_user_model().objects.create_superuser(username='platform', password='test', email='platform@example.com')
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_ambiguous_school_membership_fails_closed(self):
        SchoolMembership.objects.create(school=self.schools[1], user=self.teachers[0], role='teacher')
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_finalization_requires_csrf_token(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.teachers[0])
        grade = self.grade()
        response = client.post(reverse('finalize_grade', args=[self.assignment.pk, grade.pk]), {'confirm_finalize': 'yes'})
        self.assertEqual(response.status_code, 403)
        grade.refresh_from_db()
        self.assertEqual(grade.status, 'Draft')

    def test_roster_shows_only_assignment_grade_and_attendance(self):
        from core.models import Attendance
        own = self.grade()
        self.grade(1)
        Attendance.objects.create(school=self.schools[0], student=own.student, assignment=self.assignment, date=date(2026, 10, 15), status='Present', recorded_by=self.teachers[0])
        Attendance.objects.create(school=self.schools[1], student=self.students[1][0], assignment=self.assignments[1], date=date(2026, 10, 15), status='Absent', recorded_by=self.teachers[1])
        response = self.client.get(reverse('class_students', args=[self.assignment.pk]))
        rows = response.context['student_data']
        self.assertEqual(rows[0]['grade'], own)
        self.assertEqual((rows[0]['present'], rows[0]['absent'], rows[0]['late']), (1, 0, 0))
        self.assertIsNone(rows[1]['grade'])
        self.assertContains(response, '80.00')

    def test_teacher_can_open_own_grade_page(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_anonymous_user_cannot_open_grade_page(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
