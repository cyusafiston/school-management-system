from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import TeacherAssignment
from tenants.models import SchoolMembership
from tenants.test_teacher_assignment_form import (
    TeacherAssignmentFormTests,
)


class TeacherAssignmentViewTests(TeacherAssignmentFormTests):
    """Reuse the existing isolated two-school fixture."""

    def setUp(self):
        super().setUp()

        User = get_user_model()

        self.admin_a = User.objects.create_user(
            username="assignment_admin_a",
            password="TestPassword123!",
        )

        self.admin_b = User.objects.create_user(
            username="assignment_admin_b",
            password="TestPassword123!",
        )

        SchoolMembership.objects.create(
            school=self.school_a,
            user=self.admin_a,
            role=SchoolMembership.Role.ADMINISTRATOR,
            is_active=True,
        )

        SchoolMembership.objects.create(
            school=self.school_b,
            user=self.admin_b,
            role=SchoolMembership.Role.ADMINISTRATOR,
            is_active=True,
        )

        self.url = reverse(
            "teacher_assignment_management"
        )

    def assignment_data(self):
        return {
            "teacher": self.teacher_a.pk,
            "current_class": self.class_a.pk,
            "subject": self.subject_a.pk,
            "term": self.term_a.pk,
        }

    def test_anonymous_user_cannot_access_page(self):
        response = self.client.get(self.url)
        self.assertNotEqual(response.status_code, 200)

    def test_school_admin_can_open_page(self):
        self.client.force_login(self.admin_a)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_teacher_cannot_open_admin_page(self):
        self.client.force_login(self.teacher_a)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_own_school_assignment(self):
        self.client.force_login(self.admin_a)

        response = self.client.post(
            self.url,
            self.assignment_data(),
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            TeacherAssignment.objects.filter(
                school=self.school_a,
                teacher=self.teacher_a,
            ).exists()
        )

    def test_foreign_school_teacher_is_rejected(self):
        self.client.force_login(self.admin_a)

        data = self.assignment_data()
        data["teacher"] = self.teacher_b.pk

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            TeacherAssignment.objects.count(),
            0,
        )

    def test_posted_school_id_cannot_change_tenant(self):
        self.client.force_login(self.admin_a)

        data = self.assignment_data()
        data["school"] = self.school_b.pk

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 302)

        assignment = TeacherAssignment.objects.get()
        self.assertEqual(
            assignment.school_id,
            self.school_a.pk,
        )

    def test_other_school_cannot_see_assignments(self):
        TeacherAssignment.objects.create(
            school=self.school_a,
            teacher=self.teacher_a,
            current_class=self.class_a,
            subject=self.subject_a,
            term=self.term_a,
        )

        self.client.force_login(self.admin_b)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["assignments"]),
            [],
        )

    def test_duplicate_assignment_is_rejected(self):
        TeacherAssignment.objects.create(
            school=self.school_a,
            teacher=self.teacher_a,
            current_class=self.class_a,
            subject=self.subject_a,
            term=self.term_a,
        )

        self.client.force_login(self.admin_a)

        response = self.client.post(
            self.url,
            self.assignment_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            TeacherAssignment.objects.count(),
            1,
        )
