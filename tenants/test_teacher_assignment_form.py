from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import (
    AcademicYear,
    ClassStream,
    ClassSubject,
    Subject,
    Term,
    TeacherAssignment,
)
from tenants.forms import TeacherAssignmentForm
from tenants.models import School, SchoolMembership


class TeacherAssignmentFormTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.school_a = School.objects.create(
            name="Assignment School A",
            slug="assignment-school-a",
            status="approved",
        )
        cls.school_b = School.objects.create(
            name="Assignment School B",
            slug="assignment-school-b",
            status="approved",
        )

        cls.teacher_a = User.objects.create_user(
            username="assignment_teacher_a",
            password="SecureTestPass2026!",
        )
        cls.teacher_b = User.objects.create_user(
            username="assignment_teacher_b",
            password="SecureTestPass2026!",
        )

        for school, teacher in [
            (cls.school_a, cls.teacher_a),
            (cls.school_b, cls.teacher_b),
        ]:
            SchoolMembership.objects.create(
                school=school,
                user=teacher,
                role="teacher",
                is_active=True,
            )

        cls.year_a = AcademicYear.objects.create(
            school=cls.school_a,
            name="2026-2027",
        )
        cls.year_b = AcademicYear.objects.create(
            school=cls.school_b,
            name="2026-2027",
        )

        cls.term_a = Term.objects.create(
            school=cls.school_a,
            academic_year=cls.year_a,
            name="Term 1",
        )
        cls.term_b = Term.objects.create(
            school=cls.school_b,
            academic_year=cls.year_b,
            name="Term 1",
        )

        cls.class_a = ClassStream.objects.create(
            school=cls.school_a,
            name="PRIMARY 1",
            code="P1-A",
        )
        cls.class_b = ClassStream.objects.create(
            school=cls.school_b,
            name="PRIMARY 1",
            code="P1-B",
        )

        cls.subject_a = Subject.objects.create(
            school=cls.school_a,
            name="MATHEMATICS",
            code="MATH-A",
            max_cat_marks=30,
            max_exam_marks=70,
        )
        cls.subject_b = Subject.objects.create(
            school=cls.school_b,
            name="MATHEMATICS",
            code="MATH-B",
            max_cat_marks=30,
            max_exam_marks=70,
        )

        ClassSubject.objects.create(
            school=cls.school_a,
            academic_year=cls.year_a,
            class_stream=cls.class_a,
            subject=cls.subject_a,
        )

    def payload(self, **overrides):
        data = {
            "teacher": self.teacher_a.pk,
            "current_class": self.class_a.pk,
            "subject": self.subject_a.pk,
            "term": self.term_a.pk,
        }
        data.update(overrides)
        return data

    def test_valid_assignment(self):
        form = TeacherAssignmentForm(
            self.payload(),
            school=self.school_a,
        )
        self.assertTrue(form.is_valid(), form.errors)

        assignment = form.save()
        self.assertEqual(assignment.school, self.school_a)

    def test_foreign_teacher_rejected(self):
        form = TeacherAssignmentForm(
            self.payload(teacher=self.teacher_b.pk),
            school=self.school_a,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("teacher", form.errors)

    def test_foreign_class_rejected(self):
        form = TeacherAssignmentForm(
            self.payload(current_class=self.class_b.pk),
            school=self.school_a,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("current_class", form.errors)

    def test_foreign_subject_rejected(self):
        form = TeacherAssignmentForm(
            self.payload(subject=self.subject_b.pk),
            school=self.school_a,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("subject", form.errors)

    def test_foreign_term_rejected(self):
        form = TeacherAssignmentForm(
            self.payload(term=self.term_b.pk),
            school=self.school_a,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("term", form.errors)

    def test_subject_must_be_in_curriculum(self):
        ClassSubject.objects.filter(
            school=self.school_a,
        ).delete()

        form = TeacherAssignmentForm(
            self.payload(),
            school=self.school_a,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("subject", form.errors)

    def test_duplicate_assignment_rejected(self):
        TeacherAssignment.objects.create(
            school=self.school_a,
            teacher=self.teacher_a,
            current_class=self.class_a,
            subject=self.subject_a,
            term=self.term_a,
        )

        form = TeacherAssignmentForm(
            self.payload(),
            school=self.school_a,
        )

        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

    def test_inactive_teacher_rejected(self):
        SchoolMembership.objects.filter(
            school=self.school_a,
            user=self.teacher_a,
        ).update(is_active=False)

        form = TeacherAssignmentForm(
            self.payload(),
            school=self.school_a,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("teacher", form.errors)

    def test_school_cannot_be_overridden_by_post(self):
        data = self.payload()
        data["school"] = self.school_b.pk

        form = TeacherAssignmentForm(
            data,
            school=self.school_a,
        )

        self.assertTrue(form.is_valid(), form.errors)

        assignment = form.save()
        self.assertEqual(assignment.school, self.school_a)
