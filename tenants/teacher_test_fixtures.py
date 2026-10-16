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


class TeacherWorkflowFixture:
    @classmethod
    def setUpTestData(cls):
        cls.schools = []
        cls.teachers = []
        cls.assignments = []
        cls.students = []
        for suffix in ('a', 'b'):
            school = School.objects.create(name=f'School {suffix}', status='approved')
            teacher = get_user_model().objects.create_user(username=f'teacher_{suffix}')
            SchoolMembership.objects.create(school=school, user=teacher, role='teacher')
            year = AcademicYear.objects.create(school=school, name='2026-2027')
            term = Term.objects.create(school=school, academic_year=year, name='Term 1', is_current=True)
            stream = ClassStream.objects.create(school=school, name='PRIMARY 1', code=f'P1-{suffix}')
            subject = Subject.objects.create(school=school, name='MATHEMATICS', code=f'MATH-{suffix}', max_cat_marks=Decimal('30'), max_exam_marks=Decimal('70'))
            ClassSubject.objects.create(school=school, academic_year=year, class_stream=stream, subject=subject)
            assignment = TeacherAssignment.objects.create(school=school, teacher=teacher, current_class=stream, subject=subject, term=term)
            students = []
            for number in (1, 2):
                student = StudentProfile.objects.create(school=school, first_name=f'Child{number}', last_name=suffix, date_of_birth=date(2016, 1, 1), gender='Male', current_class=stream)
                # StudentProfile.save automatically enrolls in the current term.
                StudentEnrollment.objects.get(school=school, student=student, academic_year=year, term=term, class_stream=stream)
                students.append(student)
            cls.schools.append(school)
            cls.teachers.append(teacher)
            cls.assignments.append(assignment)
            cls.students.append(students)
