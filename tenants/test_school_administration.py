from datetime import date
from decimal import Decimal
import re

from django.core import mail
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from core.models import (AcademicYear, Attendance, ClassStream, ClassSubject, Grade,
                         StudentEnrollment, StudentProfile, Subject, Term, UserProfile)
from tenants.models import School, SchoolMembership
from tenants.teacher_test_fixtures import TeacherWorkflowFixture


class SchoolAdministrationTests(TeacherWorkflowFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admins = []
        for index in (0, 1):
            user = get_user_model().objects.create_user(username=f'school_admin_{index}', password='AdminTestPassword2026!')
            SchoolMembership.objects.create(school=cls.schools[index], user=user, role='administrator')
            cls.admins.append(user)

    def setUp(self):
        self.client.force_login(self.admins[0])
        self.school = self.schools[0]
        self.student = self.students[0][0]
        self.assignment = self.assignments[0]
        self.pages = ['admin_students', 'admin_staff', 'admin_periods', 'admin_rollover', 'admin_notices']

    def registration(self, **extra):
        return {'first_name': 'New', 'last_name': 'Student', 'date_of_birth': '2015-01-01',
                'gender': 'Female', 'current_class': self.assignment.current_class_id,
                'email': 'new-student@example.com', **extra}

    def staff_data(self, **extra):
        return {'first_name': 'New', 'last_name': 'Staff', 'username': 'new-staff',
                'email': 'new-staff@example.com', 'role': 'accountant', **extra}

    def enrollment(self, **extra):
        return {'term': self.assignment.term_id, 'class_stream': self.assignment.current_class_id, 'action': 'enroll', **extra}

    def detail(self, student=None):
        return reverse('admin_student_detail', args=[(student or self.student).pk])

    def term2(self, year=None):
        return Term.objects.create(school=self.school, academic_year=year or self.assignment.term.academic_year, name='Term 2')

    def grade(self):
        return Grade.objects.create(school=self.school, student=self.student, subject=self.assignment.subject,
            term=self.assignment.term, cat_marks=Decimal('20'), exam_marks=Decimal('50'))

    def membership(self, user=None):
        return SchoolMembership.objects.get(school=self.school, user=user or self.teachers[0])

    def test_admin_pages_and_dashboard_navigation(self):
        for route in self.pages:
            self.assertEqual(self.client.get(reverse(route)).status_code, 200)
        self.assertEqual(self.client.get(self.detail()).status_code, 200)
        response = self.client.get(reverse('school_home'))
        for route in self.pages:
            self.assertContains(response, reverse(route))

    def test_student_provisioned_with_unusable_password_and_setup_email(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('admin_students'), self.registration(school=self.schools[1].pk, user=self.teachers[1].pk))
        self.assertEqual(response.status_code, 302)
        student = StudentProfile.objects.get(first_name='New')
        self.assertEqual(student.school, self.school)
        self.assertFalse(student.user.has_usable_password())
        self.assertEqual(student.user.email, 'new-student@example.com')
        self.assertFalse(student.user.is_staff)
        self.assertFalse(student.user.is_superuser)
        self.assertTrue(StudentEnrollment.objects.filter(student=student, school=self.school, term=self.assignment.term).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/reset/', mail.outbox[0].body)
        page = self.client.get(response.url)
        self.assertNotContains(page, default_token_generator.make_token(student.user))

    def test_registration_foreign_class_and_duplicate_number_rejected(self):
        for data in (self.registration(current_class=self.assignments[1].current_class_id), self.registration(registration_number=self.student.registration_number)):
            response = self.client.post(reverse('admin_students'), data)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertFalse(StudentProfile.objects.filter(first_name='New').exists())

    def test_registration_requires_current_term(self):
        Term.objects.filter(school=self.school).update(is_current=False)
        before = get_user_model().objects.count()
        self.assertEqual(self.client.post(reverse('admin_students'), self.registration()).status_code, 200)
        self.assertEqual(get_user_model().objects.count(), before)

    def test_duplicate_recovery_email_rejected(self):
        get_user_model().objects.filter(pk=self.student.user_id).update(email='new-student@example.com')
        response = self.client.post(reverse('admin_students'), self.registration())
        self.assertIn('email', response.context['form'].errors)

    def test_accountant_invitation_cannot_escalate_privileges(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('admin_staff'), self.staff_data(is_staff='on', is_superuser='on', school=self.schools[1].pk))
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username='new-staff')
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertEqual(self.membership(user).role, 'accountant')
        self.assertEqual(mail.outbox[0].to, ['new-staff@example.com'])

    def test_staff_duplicate_username_or_admin_role_rejected(self):
        for data in (self.staff_data(username=self.teachers[0].username.upper()), self.staff_data(role='administrator')):
            response = self.client.post(reverse('admin_staff'), data)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertFalse(get_user_model().objects.filter(username='new-staff').exists())

    def test_staff_membership_activation_and_role_assignment(self):
        membership = self.membership()
        # Without current teaching assignments a teacher can become an accountant.
        self.assignment.delete()
        response = self.client.post(reverse('admin_staff_edit', args=[membership.pk]), {'role': 'accountant'})
        self.assertEqual(response.status_code, 302)
        membership.refresh_from_db()
        self.assertEqual(membership.role, 'accountant')
        self.assertFalse(membership.is_active)
        self.client.post(reverse('admin_staff_edit', args=[membership.pk]), {'role': 'accountant', 'is_active': 'on'})
        membership.refresh_from_db()
        self.assertTrue(membership.is_active)
        self.teachers[0].refresh_from_db()
        self.assertFalse(self.teachers[0].is_staff or self.teachers[0].is_superuser)

    def test_current_teacher_assignments_prevent_role_change(self):
        membership = self.membership()
        response = self.client.post(reverse('admin_staff_edit', args=[membership.pk]), {'role': 'accountant', 'is_active': 'on'})
        self.assertTrue(response.context['form'].errors)
        membership.refresh_from_db()
        self.assertEqual(membership.role, 'teacher')

    def test_cannot_modify_administrator_or_foreign_memberships(self):
        for membership in (self.membership(self.admins[0]), SchoolMembership.objects.get(user=self.teachers[1])):
            self.assertEqual(self.client.post(reverse('admin_staff_edit', args=[membership.pk]), {'role': 'teacher'}).status_code, 404)

    def test_shared_or_platform_staff_account_cannot_be_managed(self):
        membership = self.membership()
        SchoolMembership.objects.create(school=self.schools[1], user=self.teachers[0], role='teacher')
        self.assertEqual(self.client.post(reverse('admin_staff_edit', args=[membership.pk]), {'role': 'teacher'}).status_code, 403)
        self.assertEqual(self.client.post(reverse('admin_account_recovery', args=[membership.pk])).status_code, 403)

    def test_stream_change_before_activity(self):
        stream = ClassStream.objects.create(school=self.school, name='PRIMARY 2', code='P2-ADMIN')
        self.assertEqual(self.client.post(self.detail(), self.enrollment(class_stream=stream.pk)).status_code, 302)
        row = StudentEnrollment.objects.get(student=self.student, term=self.assignment.term)
        self.assertEqual(row.class_stream, stream)
        self.student.refresh_from_db()
        self.assertEqual(self.student.current_class, stream)

    def test_stream_change_with_grade_is_blocked(self):
        self.grade()
        stream = ClassStream.objects.create(school=self.school, name='PRIMARY 2', code='P2-ADMIN')
        response = self.client.post(self.detail(), self.enrollment(class_stream=stream.pk))
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(StudentEnrollment.objects.get(student=self.student, term=self.assignment.term).class_stream, self.assignment.current_class)
        self.assertEqual(Grade.objects.count(), 1)

    def test_foreign_enrollment_inputs_and_duplicate_rejected(self):
        for data in (self.enrollment(term=self.assignments[1].term_id), self.enrollment(class_stream=self.assignments[1].current_class_id), self.enrollment()):
            response = self.client.post(self.detail(), data)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertEqual(StudentEnrollment.objects.filter(student=self.student).count(), 1)

    def test_complete_and_new_term_preserve_history(self):
        self.grade()
        self.client.post(self.detail(), self.enrollment(action='complete'))
        old = StudentEnrollment.objects.get(student=self.student, term=self.assignment.term)
        self.assertEqual(old.status, 'Completed')
        term = self.term2()
        self.assertEqual(self.client.post(self.detail(), self.enrollment(term=term.pk)).status_code, 302)
        self.assertEqual(StudentEnrollment.objects.filter(student=self.student).count(), 2)
        old.refresh_from_db()
        self.assertEqual(old.status, 'Completed')
        self.assertEqual(Grade.objects.count(), 1)

    def test_transfer_out_revokes_access_without_deleting_history(self):
        self.grade()
        self.assertEqual(self.client.post(self.detail(), self.enrollment(action='transfer')).status_code, 302)
        self.assertEqual(StudentEnrollment.objects.get(student=self.student, term=self.assignment.term).status, 'Transferred')
        self.assertFalse(self.membership(self.student.user).is_active)
        self.assertEqual(Grade.objects.count(), 1)
        self.client.force_login(self.student.user)
        self.assertEqual(self.client.get(reverse('student_dashboard')).status_code, 403)

    def test_historical_enrollment_cannot_be_reopened(self):
        self.client.post(self.detail(), self.enrollment(action='complete'))
        response = self.client.post(self.detail(), self.enrollment())
        self.assertTrue(response.context['form'].errors)

    def test_student_access_toggles_only_school_membership(self):
        url = reverse('admin_student_access', args=[self.student.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.assertFalse(self.membership(self.student.user).is_active)
        self.student.user.refresh_from_db()
        self.assertTrue(self.student.user.is_active)
        self.client.post(url, {'is_active': 'on'})
        self.assertTrue(self.membership(self.student.user).is_active)

    def test_year_and_term_creation_duplicates_and_foreign_year(self):
        url = reverse('admin_periods')
        self.assertEqual(self.client.post(url, {'action': 'create_year', 'name': '2027-2028'}).status_code, 302)
        self.assertEqual(self.client.post(url, {'action': 'create_year', 'name': '2027-2028'}).status_code, 200)
        self.assertEqual(self.client.post(url, {'action': 'create_term', 'academic_year': self.assignment.term.academic_year_id, 'name': 'Term 2'}).status_code, 302)
        response = self.client.post(url, {'action': 'create_term', 'academic_year': self.assignments[1].term.academic_year_id, 'name': 'Term 2'})
        self.assertTrue(response.context['form'].errors)

    def test_activate_term_updates_only_one_school_and_preserves_records(self):
        term = self.term2()
        url = reverse('admin_activate_term', args=[term.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 400)
        self.assertEqual(self.client.post(url, {'confirm': 'yes'}).status_code, 302)
        self.assertEqual(list(Term.objects.filter(school=self.school, is_current=True)), [term])
        self.assertTrue(Term.objects.get(pk=self.assignments[1].term_id).is_current)
        self.assertEqual(StudentEnrollment.objects.filter(school=self.school).count(), 2)

    def test_roll_forward_creates_new_rows_and_preserves_grades(self):
        self.grade()
        term = self.term2()
        self.client.post(reverse('admin_activate_term', args=[term.pk]), {'confirm': 'yes'})
        response = self.client.post(reverse('admin_rollover'), {'source': self.assignment.term_id, 'target': term.pk, 'confirm': 'on'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(StudentEnrollment.objects.filter(school=self.school).count(), 4)
        self.assertEqual(StudentEnrollment.objects.filter(school=self.school, term=self.assignment.term, status='Completed').count(), 2)
        self.assertEqual(Grade.objects.count(), 1)
        self.client.force_login(self.student.user)
        self.assertEqual(self.client.get(reverse('student_dashboard')).status_code, 200)

    def test_roll_forward_duplicate_is_atomic(self):
        term = self.term2()
        StudentEnrollment.objects.create(school=self.school, student=self.students[0][1], term=term, academic_year=term.academic_year, class_stream=self.assignment.current_class)
        response = self.client.post(reverse('admin_rollover'), {'source': self.assignment.term_id, 'target': term.pk, 'confirm': 'on'})
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(StudentEnrollment.objects.filter(student=self.student, term=term).exists())
        self.assertEqual(StudentEnrollment.objects.get(student=self.student, term=self.assignment.term).status, 'Active')

    def test_class_and_subject_edit_scoped_and_grade_maxima_protected(self):
        self.grade()
        url = reverse('admin_academic_edit', args=['subject', self.assignment.subject_id])
        response = self.client.post(url, {'name': 'MATHEMATICS', 'max_cat_marks': '40', 'max_exam_marks': '60'})
        self.assertTrue(response.context['form'].errors)
        self.assignment.subject.refresh_from_db()
        self.assertEqual(self.assignment.subject.max_cat_marks, Decimal('30'))
        url = reverse('admin_academic_edit', args=['class', self.assignment.current_class_id])
        self.assertEqual(self.client.post(url, {'name': 'PRIMARY ONE A'}).status_code, 302)
        self.assertEqual(self.client.get(reverse('admin_academic_edit', args=['subject', self.assignments[1].subject_id])).status_code, 404)

    def test_curriculum_history_protected(self):
        self.grade()
        curriculum = ClassSubject.objects.get(school=self.school)
        response = self.client.post(reverse('remove_curriculum_assignment', args=[curriculum.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ClassSubject.objects.filter(pk=curriculum.pk).exists())
        response = self.client.post(reverse('edit_curriculum_requirement', args=[curriculum.pk]), {})
        self.assertTrue(response.context['form'].errors)
        curriculum.refresh_from_db()
        self.assertTrue(curriculum.is_required)

    def test_non_admins_and_inactive_admin_cannot_get_or_post(self):
        for user in (self.teachers[0], self.student.user):
            self.client.force_login(user)
            for route in self.pages:
                self.assertEqual(self.client.get(reverse(route)).status_code, 403)
                self.assertEqual(self.client.post(reverse(route), {}).status_code, 403)
        self.client.force_login(self.admins[0])
        self.membership(self.admins[0]).__class__.objects.filter(user=self.admins[0]).update(is_active=False)
        self.assertEqual(self.client.post(reverse('admin_students'), self.registration()).status_code, 403)

    def test_cross_school_object_get_and_post_denied(self):
        for url in (self.detail(self.students[1][0]), reverse('admin_staff_edit', args=[SchoolMembership.objects.get(user=self.teachers[1]).pk])):
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, {}).status_code, 404)
        self.assertEqual(self.client.post(reverse('admin_student_access', args=[self.students[1][0].pk]), {'is_active': 'on'}).status_code, 404)

    def test_csrf_blocks_unauthorized_posts(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admins[0])
        for route in self.pages:
            self.assertEqual(client.post(reverse(route), {}).status_code, 403)

    def test_recovery_is_post_only_and_tokens_not_in_response(self):
        user = self.student.user
        user.email = 'recovery-student@example.com'
        user.save(update_fields=['email'])
        url = reverse('admin_account_recovery', args=[self.membership(user).pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(default_token_generator.make_token(user).encode(), response.content)

    def test_forgot_password_generic_response_no_account_enumeration(self):
        self.client.logout()
        self.student.user.email = 'recover@example.com'
        self.student.user.save(update_fields=['email'])
        # Existing generated student has an unusable password, but can request setup.
        known = self.client.post(reverse('password_reset'), {'email': 'recover@example.com'})
        unknown = self.client.post(reverse('password_reset'), {'email': 'unknown@example.com'})
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.url, unknown.url)
        self.assertEqual(len(mail.outbox), 1)

    def reset_url(self, user=None):
        user = user or self.student.user
        return reverse('password_reset_confirm', kwargs={'uidb64': urlsafe_base64_encode(force_bytes(user.pk)), 'token': default_token_generator.make_token(user)})

    def test_setup_link_requires_user_chosen_password_and_cannot_be_reused(self):
        user = self.student.user
        user.email = 'setup@example.com'
        user.save(update_fields=['email'])
        self.client.logout()
        url = self.reset_url(user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        confirm = response.url
        self.assertEqual(self.client.post(confirm, {'new_password1': '123', 'new_password2': '123'}).status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())
        response = self.client.post(confirm, {'new_password1': 'StudentChosenPassword2026!', 'new_password2': 'StudentChosenPassword2026!'})
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password('StudentChosenPassword2026!'))
        self.assertFalse(self.client.get(url).context['validlink'])

    def test_revoked_membership_invalidates_issued_setup_link(self):
        user = self.student.user
        user.email = 'setup@example.com'
        user.save(update_fields=['email'])
        url = self.reset_url(user)
        self.membership(user).__class__.objects.filter(user=user).update(is_active=False)
        self.client.logout()
        self.assertFalse(self.client.get(url).context['validlink'])
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())

    def test_anonymous_and_platform_superuser_cannot_use_school_admin(self):
        self.client.logout()
        for route in self.pages:
            self.assertEqual(self.client.get(reverse(route)).status_code, 302)
        user = get_user_model().objects.create_superuser(username='platform-administration-test', email='platform@example.com', password='PlatformTestPassword2026!')
        self.client.force_login(user)
        for route in self.pages:
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)

    def test_school_suspension_blocks_admin_writes(self):
        School.objects.filter(pk=self.school.pk).update(status='suspended')
        for route in self.pages:
            self.assertEqual(self.client.post(reverse(route), {}).status_code, 403)

    def test_staff_deactivation_blocks_teacher_portal(self):
        membership = self.membership()
        self.assertEqual(self.client.post(reverse('admin_staff_edit', args=[membership.pk]), {'role': 'teacher'}).status_code, 302)
        self.client.force_login(self.teachers[0])
        self.assertEqual(self.client.get(reverse('teacher_dashboard')).status_code, 403)
        self.assertEqual(self.client.post(reverse('input_grades', args=[self.assignment.pk]), {}).status_code, 403)

    def test_school_admin_cannot_change_platform_account_flags(self):
        get_user_model().objects.filter(pk=self.teachers[0].pk).update(is_staff=True, is_superuser=True)
        membership = self.membership()
        self.assertEqual(self.client.post(reverse('admin_staff_edit', args=[membership.pk]), {'role': 'teacher', 'is_active': 'on'}).status_code, 403)
        self.teachers[0].refresh_from_db()
        self.assertTrue(self.teachers[0].is_staff and self.teachers[0].is_superuser)

    def test_staff_and_student_lists_exclude_other_school(self):
        self.assertNotContains(self.client.get(reverse('admin_staff')), self.teachers[1].username)
        self.assertNotContains(self.client.get(reverse('admin_students')), self.students[1][0].user.username)

    def test_same_school_different_registration_is_unique(self):
        self.client.post(reverse('admin_students'), self.registration())
        self.client.post(reverse('admin_students'), self.registration(first_name='Another', email='another-student@example.com'))
        numbers = list(StudentProfile.objects.filter(school=self.school).values_list('registration_number', flat=True))
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_transfer_cannot_move_profile_to_another_school(self):
        self.client.post(self.detail(), self.enrollment(action='transfer', school=self.schools[1].pk, user=self.teachers[1].pk))
        self.student.refresh_from_db()
        self.assertEqual(self.student.school, self.school)
        self.assertNotEqual(self.student.user, self.teachers[1])

    def test_stream_change_with_attendance_is_blocked(self):
        Attendance.objects.create(school=self.school, student=self.student, assignment=self.assignment,
            date=date.today(), status='Present', recorded_by=self.teachers[0])
        stream = ClassStream.objects.create(school=self.school, name='PRIMARY 2', code='P2-WITH-ATT')
        response = self.client.post(self.detail(), self.enrollment(class_stream=stream.pk))
        self.assertTrue(response.context['form'].errors)

    def test_rollover_backwards_unconfirmed_and_foreign_targets_rejected(self):
        target = self.term2()
        for data in ({'source': target.pk, 'target': self.assignment.term_id, 'confirm': 'on'},
                     {'source': self.assignment.term_id, 'target': target.pk},
                     {'source': self.assignment.term_id, 'target': self.assignments[1].term_id, 'confirm': 'on'}):
            response = self.client.post(reverse('admin_rollover'), data)
            self.assertTrue(response.context['form'].errors)
        self.assertEqual(StudentEnrollment.objects.filter(school=self.school).count(), 2)

    def test_year_transition_promotes_without_modifying_prior_marks(self):
        grade = self.grade()
        year = AcademicYear.objects.create(school=self.school, name='2027-2028')
        term = Term.objects.create(school=self.school, academic_year=year, name='Term 1')
        stream = ClassStream.objects.create(school=self.school, name='PRIMARY 2', code='P2-PROMOTE')
        self.client.post(reverse('admin_activate_term', args=[term.pk]), {'confirm': 'yes'})
        response = self.client.post(reverse('admin_rollover'), {'source': self.assignment.term_id, 'target': term.pk, 'target_class': stream.pk, 'confirm': 'on'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(StudentEnrollment.objects.get(student=self.student, term=term).class_stream, stream)
        grade.refresh_from_db()
        self.assertEqual(grade.term, self.assignment.term)
        self.assertEqual(grade.marks_obtained, Decimal('70'))

    def test_foreign_term_activation_denied(self):
        self.assertEqual(self.client.post(reverse('admin_activate_term', args=[self.assignments[1].term_id]), {'confirm': 'yes'}).status_code, 404)
        self.assertTrue(Term.objects.get(pk=self.assignment.term_id).is_current)

    def test_ambiguous_email_and_inactive_account_do_not_receive_reset(self):
        user = self.student.user
        user.email = 'ambiguous@example.com'
        user.save(update_fields=['email'])
        get_user_model().objects.create_user(username='ambiguous-recovery', email=user.email)
        self.client.logout()
        self.client.post(reverse('password_reset'), {'email': user.email})
        self.assertEqual(len(mail.outbox), 0)
        user.email = 'inactive-recovery@example.com'
        user.is_active = False
        user.save(update_fields=['email', 'is_active'])
        self.client.post(reverse('password_reset'), {'email': user.email})
        self.assertEqual(len(mail.outbox), 0)

    def test_expired_or_tampered_setup_token_denied(self):
        from datetime import datetime, timedelta
        from unittest.mock import patch
        user = self.student.user
        user.email = 'expired@example.com'
        user.save(update_fields=['email'])
        url = self.reset_url(user)
        self.client.logout()
        with patch('django.contrib.auth.tokens.PasswordResetTokenGenerator._now', return_value=datetime.now()+timedelta(days=4)):
            self.assertFalse(self.client.get(url).context['validlink'])
        self.assertFalse(self.client.get(url.rstrip('/')+'tampered/').context['validlink'])

    def test_setup_post_after_membership_revocation_is_denied(self):
        user = self.student.user
        user.email = 'revoked-post@example.com'
        user.save(update_fields=['email'])
        self.client.logout()
        url = self.client.get(self.reset_url(user)).url
        SchoolMembership.objects.filter(user=user).update(is_active=False)
        response = self.client.post(url, {'new_password1': 'UnexpectedPassword2026!', 'new_password2': 'UnexpectedPassword2026!'})
        self.assertFalse(response.context['validlink'])
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())

    def test_setup_confirm_requires_csrf(self):
        user = self.student.user
        user.email = 'csrf-setup@example.com'
        user.save(update_fields=['email'])
        client = Client(enforce_csrf_checks=True)
        response = client.get(self.reset_url(user))
        self.assertEqual(client.post(response.url, {'new_password1': 'UnexpectedPassword2026!', 'new_password2': 'UnexpectedPassword2026!'}).status_code, 403)

    def test_new_admin_teacher_student_end_to_end(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('admin_students'), self.registration())
        self.assertEqual(response.status_code, 302)
        student = StudentProfile.objects.get(first_name='New')
        from urllib.parse import urlsplit
        setup = urlsplit(re.search(r'https?://[^\s]+/reset/[^\s]+', mail.outbox[-1].body).group(0)).path
        self.client.logout()
        confirm = self.client.get(setup).url
        self.assertEqual(self.client.post(confirm, {'new_password1': 'StudentWorkflowPassword2026!',
            'new_password2': 'StudentWorkflowPassword2026!'}).status_code, 302)
        self.assertEqual(self.client.post(reverse('login'), {'username': student.user.username,
            'password': 'StudentWorkflowPassword2026!'}).status_code, 302)
        self.client.force_login(self.teachers[0])
        self.client.post(reverse('input_grades', args=[self.assignment.pk]), {f'cat_{student.pk}': '25', f'exam_{student.pk}': '60'})
        grade = Grade.objects.get(student=student)
        self.assertEqual(self.client.post(reverse('finalize_grade', args=[self.assignment.pk, grade.pk]), {'confirm_finalize': 'yes'}).status_code, 302)
        self.client.force_login(student.user)
        response = self.client.get(reverse('student_grades'))
        self.assertEqual(list(response.context['grades_list']), [grade])
        self.client.force_login(self.students[1][0].user)
        self.assertNotIn(grade, self.client.get(reverse('student_grades')).context['grades_list'])

    def test_role_change_keeps_teacher_assignment_validation_usable(self):
        from tenants.forms import TeacherAssignmentForm
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('admin_staff'), self.staff_data())
        user = get_user_model().objects.get(username='new-staff')
        membership = self.membership(user)
        self.assertEqual(self.client.post(reverse('admin_staff_edit', args=[membership.pk]), {'role': 'teacher', 'is_active': 'on'}).status_code, 302)
        self.assertEqual(UserProfile.objects.get(user=user).role, 'Teacher')
        form = TeacherAssignmentForm({'teacher': user.pk, 'current_class': self.assignment.current_class_id,
            'subject': self.assignment.subject_id, 'term': self.assignment.term_id}, school=self.school)
        self.assertTrue(form.is_valid(), form.errors)

    def test_reassign_teacher_preserves_grade_and_changes_access(self):
        self.grade()
        user = get_user_model().objects.create_user(username='replacement-teacher')
        SchoolMembership.objects.create(school=self.school, user=user, role='teacher')
        url = reverse('admin_reassign_teacher', args=[self.assignment.pk])
        self.assertEqual(self.client.post(url, {'teacher': self.teachers[1].pk}).status_code, 200)
        self.assertEqual(self.client.post(url, {'teacher': user.pk}).status_code, 302)
        self.assertEqual(Grade.objects.count(), 1)
        self.client.force_login(self.teachers[0])
        self.assertEqual(self.client.get(reverse('input_grades', args=[self.assignment.pk])).status_code, 404)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('input_grades', args=[self.assignment.pk])).status_code, 200)

    def test_admin_notice_reaches_only_own_school_student(self):
        self.assertEqual(self.client.post(reverse('admin_notices'), {'title': 'School announcement', 'content': 'Classes resume Monday', 'target_class': self.assignment.current_class_id}).status_code, 302)
        self.client.force_login(self.student.user)
        self.assertContains(self.client.get(reverse('student_notices')), 'School announcement')
        self.client.force_login(self.students[1][0].user)
        self.assertNotContains(self.client.get(reverse('student_notices')), 'School announcement')

    def test_notice_foreign_class_and_cross_school_edit_rejected(self):
        from core.models import Notice
        response = self.client.post(reverse('admin_notices'), {'title': 'Bad', 'content': 'Bad', 'target_class': self.assignments[1].current_class_id})
        self.assertIn('target_class', response.context['form'].errors)
        notice = Notice.objects.create(school=self.schools[1], title='Foreign', content='Foreign')
        self.assertEqual(self.client.post(reverse('admin_notice_edit', args=[notice.pk]), {'title': 'Changed', 'content': 'Changed'}).status_code, 404)

    def test_administrator_navigation_links_to_reassignment_and_academic_edit(self):
        response = self.client.get(reverse('teacher_assignment_management'))
        self.assertContains(response, reverse('admin_reassign_teacher', args=[self.assignment.pk]))
        response = self.client.get(reverse('academic_setup'))
        self.assertContains(response, reverse('admin_academic_edit', args=['class', self.assignment.current_class_id]))
        self.assertContains(response, reverse('admin_academic_edit', args=['subject', self.assignment.subject_id]))

    def test_legacy_registration_numbers_do_not_trap_automatic_counter(self):
        from django.utils import timezone
        StudentProfile.objects.filter(pk=self.student.pk).update(registration_number=f'STU/{timezone.localdate().year}/100')
        response = self.client.post(reverse('admin_students'), self.registration())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(StudentProfile.objects.get(first_name='New').registration_number, f'STU/{timezone.localdate().year}/101')

    def test_blank_recovery_email_fails_closed(self):
        from tenants.admin_forms import SchoolPasswordResetForm
        self.assertEqual(list(SchoolPasswordResetForm().get_users('')), [])
        self.assertEqual(list(SchoolPasswordResetForm().get_users('invalid-address')), [])

    def test_setup_email_failure_does_not_expose_token_or_undo_account(self):
        from unittest.mock import patch
        with patch('tenants.admin_services.send_mail', side_effect=RuntimeError('sensitive-provider-details')):
            with self.assertLogs('tenants.admin_services', level='WARNING') as logs:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(reverse('admin_students'), self.registration())
        self.assertEqual(response.status_code, 302)
        user = StudentProfile.objects.get(first_name='New').user
        self.assertFalse(user.has_usable_password())
        self.assertNotIn('sensitive-provider-details', ' '.join(logs.output))
        self.assertNotIn('/reset/', ' '.join(logs.output))

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend')
    def test_console_backend_never_prints_setup_tokens(self):
        from io import StringIO
        from contextlib import redirect_stdout
        output = StringIO()
        with redirect_stdout(output), self.assertLogs('tenants.admin_services', level='WARNING'):
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(reverse('admin_students'), self.registration())
        self.assertEqual(output.getvalue(), '')
        self.assertTrue(StudentProfile.objects.filter(first_name='New').exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend')
    def test_console_backend_never_prints_recovery_tokens(self):
        from io import StringIO
        from contextlib import redirect_stdout
        user = self.student.user
        user.email = 'console-safe@example.com'
        user.save(update_fields=['email'])
        self.client.logout()
        output = StringIO()
        with redirect_stdout(output), self.assertLogs('tenants.admin_services', level='WARNING'):
            response = self.client.post(reverse('password_reset'), {'email': user.email})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(output.getvalue(), '')

    def test_legacy_foreign_class_enrollment_cannot_be_modified(self):
        row = StudentEnrollment.objects.get(student=self.student, term=self.assignment.term)
        StudentEnrollment.objects.filter(pk=row.pk).update(class_stream=self.assignments[1].current_class)
        response = self.client.post(self.detail(), self.enrollment(action='complete'))
        self.assertTrue(response.context['form'].errors)
        row.refresh_from_db()
        self.assertEqual(row.status, 'Active')

    def test_legacy_foreign_profile_class_is_not_disclosed(self):
        StudentProfile.objects.filter(pk=self.student.pk).update(current_class=self.assignments[1].current_class)
        self.assertEqual(self.client.get(self.detail()).status_code, 404)
        self.assertNotContains(self.client.get(reverse('admin_students')), self.student.user.username)

    def test_legacy_foreign_profile_account_is_not_disclosed(self):
        StudentProfile.objects.filter(pk=self.student.pk).update(user=self.teachers[1])
        self.assertEqual(self.client.get(self.detail()).status_code, 404)
        self.assertNotContains(self.client.get(reverse('admin_students')), self.teachers[1].username)

    def test_provisioning_email_length_matches_existing_user_column(self):
        email = 'x'*64 + '@' + '.'.join(['a'*60, 'b'*60, 'c'*60, 'example', 'com'])
        for route, data in (('admin_students', self.registration(email=email)), ('admin_staff', self.staff_data(email=email))):
            response = self.client.post(reverse(route), data)
            self.assertEqual(response.status_code, 200)
            self.assertIn('email', response.context['form'].errors)
        self.assertFalse(StudentProfile.objects.filter(first_name='New').exists())
        self.assertFalse(get_user_model().objects.filter(username='new-staff').exists())
