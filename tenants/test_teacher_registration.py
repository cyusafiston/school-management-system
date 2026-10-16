
from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import UserProfile
from tenants.forms import TeacherRegistrationForm
from tenants.models import School, SchoolMembership


class TeacherRegistrationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.school_a = School.objects.create(
            name="Teacher Test School A",
            slug="teacher-test-school-a",
            status=School.Status.APPROVED,
        )
        cls.school_b = School.objects.create(
            name="Teacher Test School B",
            slug="teacher-test-school-b",
            status=School.Status.APPROVED,
        )

    def valid_data(self, **overrides):
        data = {
            "first_name": "Test",
            "last_name": "Teacher",
            "username": "teacher_step882",
            "email": "teacher882@example.com",
            "password1": "StrongTeacherPassword882!",
            "password2": "StrongTeacherPassword882!",
        }
        data.update(overrides)
        return data

    def test_teacher_creation(self):
        form = TeacherRegistrationForm(
            self.valid_data(),
            school=self.school_a,
        )

        self.assertTrue(form.is_valid(), form.errors)

        user = form.save()

        self.assertTrue(
            user.check_password("StrongTeacherPassword882!")
        )
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

        self.assertEqual(
            UserProfile.objects.get(user=user).role,
            "Teacher",
        )

        membership = SchoolMembership.objects.get(user=user)

        self.assertEqual(membership.school, self.school_a)
        self.assertEqual(
            membership.role,
            SchoolMembership.Role.TEACHER,
        )
        self.assertTrue(membership.is_active)

        self.assertFalse(
            SchoolMembership.objects.filter(
                user=user,
                school=self.school_b,
            ).exists()
        )

    def test_duplicate_username_rejected(self):
        get_user_model().objects.create_user(
            username="teacher_step882",
            password="ExistingPassword882!",
        )

        form = TeacherRegistrationForm(
            self.valid_data(),
            school=self.school_a,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_case_insensitive_duplicate_rejected(self):
        get_user_model().objects.create_user(
            username="TEACHER_STEP882",
            password="ExistingPassword882!",
        )

        form = TeacherRegistrationForm(
            self.valid_data(),
            school=self.school_a,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_password_mismatch_rejected(self):
        form = TeacherRegistrationForm(
            self.valid_data(
                password2="DifferentPassword882!"
            ),
            school=self.school_a,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_weak_password_rejected(self):
        form = TeacherRegistrationForm(
            self.valid_data(
                password1="123",
                password2="123",
            ),
            school=self.school_a,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("password1", form.errors)

    def test_school_is_required(self):
        with self.assertRaises(ValueError):
            TeacherRegistrationForm(
                self.valid_data(),
                school=None,
            )
