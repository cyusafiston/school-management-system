from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import ClassStream, Subject
from tenants.models import School, SchoolMembership


class AcademicSetupTests(TestCase):
    """Verify academic setup permissions and tenant isolation."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.school_a = School.objects.create(
            name="Academic Test School A",
            slug="academic-test-school-a",
            status=School.Status.APPROVED,
        )
        cls.school_b = School.objects.create(
            name="Academic Test School B",
            slug="academic-test-school-b",
            status=School.Status.APPROVED,
        )

        cls.admin_a = User.objects.create_user(
            username="academic_admin_a",
            password="TestPassword123!",
        )
        cls.admin_b = User.objects.create_user(
            username="academic_admin_b",
            password="TestPassword123!",
        )
        cls.teacher_a = User.objects.create_user(
            username="academic_teacher_a",
            password="TestPassword123!",
        )

        for user, school, role in [
            (cls.admin_a, cls.school_a, "administrator"),
            (cls.admin_b, cls.school_b, "administrator"),
            (cls.teacher_a, cls.school_a, "teacher"),
        ]:
            SchoolMembership.objects.create(
                user=user,
                school=school,
                role=role,
                is_active=True,
            )

        cls.url = reverse("academic_setup")

    def test_administrator_can_create_class(self):
        self.client.force_login(self.admin_a)

        response = self.client.post(
            self.url,
            {
                "action": "create_class",
                "name": "Primary One",
                "school": self.school_b.pk,
            },
        )

        self.assertRedirects(response, self.url)

        created = ClassStream.objects.get(name="Primary One")
        self.assertEqual(created.school_id, self.school_a.pk)
        self.assertTrue(created.code.startswith("STR/"))

    def test_administrator_can_create_subject(self):
        self.client.force_login(self.admin_a)

        response = self.client.post(
            self.url,
            {
                "action": "create_subject",
                "name": "Mathematics",
                "description": "Basic Mathematics",
                "max_cat_marks": "30",
                "max_exam_marks": "70",
                "school": self.school_b.pk,
            },
        )

        self.assertRedirects(response, self.url)

        created = Subject.objects.get(name="Mathematics")
        self.assertEqual(created.school_id, self.school_a.pk)
        self.assertTrue(created.code.startswith("SUB/"))

    def test_teacher_cannot_create_class(self):
        self.client.force_login(self.teacher_a)

        response = self.client.post(
            self.url,
            {"action": "create_class", "name": "Forbidden Class"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            ClassStream.objects.filter(name="Forbidden Class").exists()
        )

    def test_duplicate_class_name_is_rejected(self):
        ClassStream.objects.create(
            school=self.school_a,
            name="Primary One",
        )
        self.client.force_login(self.admin_a)

        response = self.client.post(
            self.url,
            {"action": "create_class", "name": "primary one"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ClassStream.objects.filter(school=self.school_a).count(),
            1,
        )

    def test_duplicate_subject_name_is_rejected(self):
        Subject.objects.create(
            school=self.school_a,
            name="Mathematics",
        )
        self.client.force_login(self.admin_a)

        response = self.client.post(
            self.url,
            {
                "action": "create_subject",
                "name": "mathematics",
                "max_cat_marks": "30",
                "max_exam_marks": "70",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Subject.objects.filter(school=self.school_a).count(),
            1,
        )

    def test_two_schools_can_have_same_class_and_subject_names(self):
        for school in [self.school_a, self.school_b]:
            ClassStream.objects.create(
                school=school,
                name="Primary One",
            )
            Subject.objects.create(
                school=school,
                name="Mathematics",
            )

        self.assertEqual(
            ClassStream.objects.filter(name="Primary One").count(),
            2,
        )
        self.assertEqual(
            Subject.objects.filter(name="Mathematics").count(),
            2,
        )

    def test_administrator_sees_only_own_school_records(self):
        ClassStream.objects.create(
            school=self.school_a,
            name="Class A",
        )
        ClassStream.objects.create(
            school=self.school_b,
            name="Class B",
        )
        Subject.objects.create(
            school=self.school_a,
            name="Subject A",
        )
        Subject.objects.create(
            school=self.school_b,
            name="Subject B",
        )

        self.client.force_login(self.admin_a)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Class A")
        self.assertContains(response, "Subject A")
        self.assertNotContains(response, "Class B")
        self.assertNotContains(response, "Subject B")
