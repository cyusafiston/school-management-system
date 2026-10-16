from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from tenants.models import School, SchoolMembership


class TeacherManagementSecurityTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.school_a = School.objects.create(
            name="Security Test School A",
            status="approved",
        )
        cls.school_b = School.objects.create(
            name="Security Test School B",
            status="approved",
        )

        cls.admin_a = User.objects.create_user(
            username="security_admin_a",
            password="StrongTestPass123!",
        )
        cls.admin_b = User.objects.create_user(
            username="security_admin_b",
            password="StrongTestPass123!",
        )
        cls.teacher_a = User.objects.create_user(
            username="security_teacher_a",
            password="StrongTestPass123!",
        )
        cls.accountant_a = User.objects.create_user(
            username="security_accountant_a",
            password="StrongTestPass123!",
        )

        for school, user, role in [
            (cls.school_a, cls.admin_a, "administrator"),
            (cls.school_b, cls.admin_b, "administrator"),
            (cls.school_a, cls.teacher_a, "teacher"),
            (cls.school_a, cls.accountant_a, "accountant"),
        ]:
            SchoolMembership.objects.create(
                school=school,
                user=user,
                role=role,
                is_active=True,
            )

    def setUp(self):
        self.url = reverse("teacher_management")

    def test_anonymous_user_redirected(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_school_admin_can_access(self):
        self.client.force_login(self.admin_a)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_teacher_cannot_access(self):
        self.client.force_login(self.teacher_a)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_accountant_cannot_access(self):
        self.client.force_login(self.accountant_a)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_admin_sees_only_own_school_teachers(self):
        User = get_user_model()

        other_teacher = User.objects.create_user(
            username="security_teacher_b",
            password="StrongTestPass123!",
        )

        SchoolMembership.objects.create(
            school=self.school_b,
            user=other_teacher,
            role="teacher",
            is_active=True,
        )

        self.client.force_login(self.admin_a)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "security_teacher_a")
        self.assertNotContains(response, "security_teacher_b")

    def test_new_teacher_assigned_to_correct_school(self):
        User = get_user_model()

        self.client.force_login(self.admin_a)

        response = self.client.post(
            self.url,
            {
                "first_name": "Security",
                "last_name": "Teacher",
                "username": "new_security_teacher",
                "email": "teacher-security@example.com",
                "password1": "SecureTeacherPass2026!",
                "password2": "SecureTeacherPass2026!",
            },
        )

        self.assertEqual(response.status_code, 302)

        teacher = User.objects.get(
            username="new_security_teacher"
        )

        self.assertTrue(
            SchoolMembership.objects.filter(
                school=self.school_a,
                user=teacher,
                role="teacher",
                is_active=True,
            ).exists()
        )

        self.assertFalse(
            SchoolMembership.objects.filter(
                school=self.school_b,
                user=teacher,
            ).exists()
        )


    def test_inactive_admin_cannot_access(self):
        SchoolMembership.objects.filter(
            school=self.school_a,
            user=self.admin_a,
        ).update(is_active=False)

        self.client.force_login(self.admin_a)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_suspended_school_admin_cannot_access(self):
        self.school_a.status = "suspended"
        self.school_a.save(update_fields=["status"])

        self.client.force_login(self.admin_a)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_teacher_cannot_register_another_teacher(self):
        User = get_user_model()
        self.client.force_login(self.teacher_a)

        response = self.client.post(
            self.url,
            self.teacher_payload("blocked_by_teacher"),
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            User.objects.filter(
                username="blocked_by_teacher"
            ).exists()
        )

    def test_accountant_cannot_register_teacher(self):
        User = get_user_model()
        self.client.force_login(self.accountant_a)

        response = self.client.post(
            self.url,
            self.teacher_payload("blocked_by_accountant"),
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            User.objects.filter(
                username="blocked_by_accountant"
            ).exists()
        )

    def test_posted_school_id_cannot_override_admin_school(self):
        User = get_user_model()
        self.client.force_login(self.admin_a)

        payload = self.teacher_payload(
            "school_override_attempt"
        )
        payload["school"] = str(self.school_b.pk)
        payload["school_id"] = str(self.school_b.pk)

        response = self.client.post(self.url, payload)

        self.assertEqual(response.status_code, 302)

        teacher = User.objects.get(
            username="school_override_attempt"
        )

        self.assertTrue(
            SchoolMembership.objects.filter(
                school=self.school_a,
                user=teacher,
                role="teacher",
            ).exists()
        )

        self.assertFalse(
            SchoolMembership.objects.filter(
                school=self.school_b,
                user=teacher,
            ).exists()
        )

    @staticmethod
    def teacher_payload(username):
        return {
            "first_name": "Security",
            "last_name": "Test",
            "username": username,
            "email": f"{username}@example.com",
            "password1": "SecureTeacherPass2026!",
            "password2": "SecureTeacherPass2026!",
        }
