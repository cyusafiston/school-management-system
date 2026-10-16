from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import TeacherAssignment
from tenants import test_teacher_assignment_form as assignment_fixtures

User = get_user_model()


class TeacherStudentAccessTests(TestCase):
    """Verify teacher class access across independent schools."""

    @classmethod
    def setUpTestData(cls):
        assignment_fixtures.TeacherAssignmentFormTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.assignment_a = TeacherAssignment.objects.create(
            school=self.school_a,
            teacher=self.teacher_a,
            current_class=self.class_a,
            subject=self.subject_a,
            term=self.term_a,
        )

        self.assignment_b = TeacherAssignment.objects.create(
            school=self.school_b,
            teacher=self.teacher_b,
            current_class=self.class_b,
            subject=self.subject_b,
            term=self.term_b,
        )

    def student_url(self, assignment):
        return reverse(
            "class_students",
            kwargs={"assignment_id": assignment.pk},
        )

    def test_teacher_can_access_own_assignment(self):
        self.client.force_login(self.teacher_a)

        response = self.client.get(
            self.student_url(self.assignment_a)
        )

        self.assertEqual(response.status_code, 200)

    def test_teacher_cannot_access_other_school_assignment(self):
        self.client.force_login(self.teacher_a)

        response = self.client.get(
            self.student_url(self.assignment_b)
        )

        self.assertIn(response.status_code, [403, 404])

    def test_anonymous_user_cannot_access_students(self):
        response = self.client.get(
            self.student_url(self.assignment_a)
        )

        self.assertEqual(response.status_code, 302)

    def test_administrator_cannot_access_teacher_students(self):
        admin = User.objects.create_user(
            username="teacher_students_admin",
            password="TestPassword123!",
        )

        from tenants.models import SchoolMembership
        SchoolMembership.objects.create(school=self.school_a, user=admin, role="administrator")
        self.client.force_login(admin)

        response = self.client.get(
            self.student_url(self.assignment_a)
        )

        self.assertIn(response.status_code, [403, 404])


    def test_inactive_membership_cannot_access_students(self):
        from tenants.models import SchoolMembership

        SchoolMembership.objects.filter(
            school=self.school_a,
            user=self.teacher_a,
        ).update(is_active=False)

        self.client.force_login(self.teacher_a)

        response = self.client.get(
            self.student_url(self.assignment_a)
        )

        self.assertIn(response.status_code, [403, 404])

    def test_other_school_student_not_shown(self):
        from datetime import date
        from core.models import StudentProfile, StudentEnrollment

        own_student = StudentProfile.objects.create(
            school=self.school_a,
            first_name="Allowed",
            last_name="Student",
            date_of_birth=date(2015, 1, 1),
            gender="Male",
            current_class=self.class_a,
        )

        StudentEnrollment.objects.create(
            school=self.school_a,
            student=own_student,
            academic_year=self.year_a,
            term=self.term_a,
            class_stream=self.class_a,
            status="Active",
        )

        foreign_student = StudentProfile.objects.create(
            school=self.school_b,
            first_name="Foreign",
            last_name="Student",
            date_of_birth=date(2015, 1, 1),
            gender="Male",
            current_class=self.class_b,
        )

        StudentEnrollment.objects.create(
            school=self.school_b,
            student=foreign_student,
            academic_year=self.year_b,
            term=self.term_b,
            class_stream=self.class_b,
            status="Active",
        )

        self.client.force_login(self.teacher_a)

        response = self.client.get(
            self.student_url(self.assignment_a)
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Allowed Student")
        self.assertNotContains(response, "Foreign Student")
