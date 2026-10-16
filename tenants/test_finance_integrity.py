"""Isolated end-to-end financial integrity and tenant boundary regressions."""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.db import transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.finance import SALT
from core.models import (ClassStream, FeeCategory, FeeStructure, Payment, StudentEnrollment,
                         StudentFee, Term)
from core.views import generate_student_fees_for_term
from tenants.models import SchoolMembership
from tenants.teacher_test_fixtures import TeacherWorkflowFixture


class FinanceIntegrityTests(TeacherWorkflowFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.staff = {}
        for index, school in enumerate(cls.schools):
            for role in ('accountant', 'administrator'):
                user = get_user_model().objects.create_user(username=f'{role}_{index}')
                SchoolMembership.objects.create(school=school, user=user, role=role)
                cls.staff[index, role] = user
            for student in cls.students[index]:
                StudentFee.objects.create(school=school, student=student,
                    academic_year=cls.assignments[index].term.academic_year,
                    term=cls.assignments[index].term, total_expected=Decimal('100.30'))

    def setUp(self):
        self.school = self.schools[0]
        self.student = self.students[0][0]
        self.term = self.assignments[0].term
        self.year = self.term.academic_year
        self.stream = self.assignments[0].current_class
        self.client.force_login(self.staff[0, 'accountant'])

    def token(self, client=None):
        return (client or self.client).get(reverse('record_payment')).context['form'].initial['submission_token']

    def data(self, **overrides):
        return {'student': self.student.pk, 'academic_year': self.year.pk, 'term': self.term.pk,
                'amount_paid': '30.10', 'payment_method': 'Cash', 'reference_number': '',
                'notes': '', 'submission_token': self.token(), **overrides}

    def pay(self, **overrides):
        return self.client.post(reverse('record_payment'), self.data(**overrides))

    def payment(self, index=0, student=None, amount='30.10', **extra):
        term = self.assignments[index].term
        return Payment.objects.create(school=self.schools[index], student=student or self.students[index][0],
            academic_year=term.academic_year, term=term, amount_paid=Decimal(amount), **extra)

    def structure(self, amount='45.15', stream=None, term=None):
        category, _ = FeeCategory.objects.get_or_create(school=self.school, name='Tuition')
        term = term or self.term
        return FeeStructure.objects.create(school=self.school, academic_year=term.academic_year,
            term=term, class_stream=stream or self.stream, category=category, amount=Decimal(amount))

    def staff_pages(self):
        return [reverse(name) for name in ('accountant_dashboard', 'record_payment', 'student_search',
            'debtors_list', 'daily_collection_report', 'class_collections_report')] + [
            reverse('student_financial_profile', args=[self.student.pk]),
            reverse('class_collection_detail', args=[self.stream.pk]),
            reverse('student_financial_statement', args=[self.student.pk])]

    def test_staff_pages_render_and_navigation_has_working_links(self):
        for url in self.staff_pages():
            self.assertEqual(self.client.get(url).status_code, 200, url)
        response = self.client.get(reverse('accountant_dashboard'))
        self.assertNotContains(response, 'href="#"')
        self.assertNotContains(response, '```')

    def test_administrator_can_collect_and_configure_accountant_cannot_configure(self):
        self.assertEqual(self.client.get(reverse('fee_configuration')).status_code, 403)
        self.client.force_login(self.staff[0, 'administrator'])
        self.assertEqual(self.client.get(reverse('fee_configuration')).status_code, 200)
        self.assertEqual(self.pay().status_code, 302)
        self.assertContains(self.client.get(reverse('accountant_dashboard')), reverse('fee_configuration'))

    def test_students_and_teachers_denied_all_staff_gets_and_posts(self):
        for user in (self.teachers[0], self.student.user):
            self.client.force_login(user)
            for url in self.staff_pages() + [reverse('fee_configuration')]:
                self.assertEqual(self.client.get(url).status_code, 403, url)
                self.assertEqual(self.client.post(url, {}).status_code, 403, url)
        self.assertEqual(Payment.objects.count(), 0)

    def test_inactive_membership_denied(self):
        SchoolMembership.objects.filter(user=self.staff[0, 'accountant']).update(is_active=False)
        for url in self.staff_pages():
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_unapproved_school_denied(self):
        self.school.status = 'pending'
        self.school.save()
        self.assertEqual(self.client.get(reverse('accountant_dashboard')).status_code, 403)

    def test_anonymous_finance_redirects(self):
        self.client.logout()
        for url in self.staff_pages():
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_cross_school_object_access_and_void_denied(self):
        foreign = self.payment(index=1)
        for name, pk in [('payment_receipt', foreign.pk), ('void_payment', foreign.pk),
                ('student_financial_profile', self.students[1][0].pk),
                ('student_financial_statement', self.students[1][0].pk),
                ('class_collection_detail', self.assignments[1].current_class_id)]:
            url = reverse(name, args=[pk])
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, {'void_reason': 'Unauthorized'}).status_code, 404)
        foreign.refresh_from_db()
        self.assertFalse(foreign.is_voided)

    def test_cross_school_payment_form_fields_rejected(self):
        foreign = self.assignments[1].term
        for changes in ({'student': self.students[1][0].pk}, {'term': foreign.pk},
                        {'academic_year': foreign.academic_year_id}):
            response = self.pay(**changes)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertFalse(Payment.objects.exists())

    def test_school_and_receiver_are_server_controlled(self):
        response = self.pay(school=self.schools[1].pk, received_by=self.teachers[1].pk)
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get()
        self.assertEqual(payment.school, self.school)
        self.assertEqual(payment.received_by, self.staff[0, 'accountant'])

    def test_identical_retry_returns_original_receipt_even_when_balance_zero(self):
        data = self.data(amount_paid='100.30')
        first = self.client.post(reverse('record_payment'), data)
        second = self.client.post(reverse('record_payment'), data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(first.url, second.url)
        self.assertEqual(Payment.objects.count(), 1)

    def test_used_token_cannot_change_amount_student_or_notes(self):
        data = self.data()
        self.client.post(reverse('record_payment'), data)
        for changes in ({'amount_paid': '30.11'}, {'student': self.students[0][1].pk}, {'notes': 'Changed'}):
            self.assertEqual(self.client.post(reverse('record_payment'), {**data, **changes}).status_code, 400)
        self.assertEqual(Payment.objects.count(), 1)

    def test_fresh_form_allows_separate_equal_cash_payments_without_reference(self):
        for _ in range(2):
            self.assertEqual(self.pay().status_code, 302)
        self.assertEqual(Payment.objects.count(), 2)
        self.assertEqual(Payment.objects.filter(reference_number__isnull=True).count(), 2)
        self.assertEqual(len(set(Payment.objects.values_list('receipt_number', flat=True))), 2)

    def test_tampered_missing_expired_or_other_users_token_rejected(self):
        data = self.data()
        for token in ('', data['submission_token'] + 'tamper', signing.dumps(
                {'school': self.school.pk, 'user': self.teachers[0].pk, 'nonce': 'a'*32}, salt=SALT)):
            self.assertEqual(self.client.post(reverse('record_payment'), {**data, 'submission_token': token}).status_code, 400)
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp()+90000):
            self.assertEqual(self.client.post(reverse('record_payment'), data).status_code, 400)
        self.assertFalse(Payment.objects.exists())

    def test_duplicate_reference_normalized_and_rejected_without_exposing_foreign_record(self):
        self.assertEqual(self.pay(reference_number='  BANK-001  ').status_code, 302)
        response = self.pay(reference_number='BANK-001')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(Payment.objects.get().reference_number, 'BANK-001')
        self.payment(index=1, reference_number='FOREIGN-REF')
        response = self.pay(reference_number='FOREIGN-REF')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, str(self.students[1][0]))
        self.assertEqual(Payment.objects.count(), 2)

    def test_invalid_zero_negative_nonfinite_excess_precision_and_overpayment_rejected(self):
        for amount in ('0', '-1', 'NaN', 'Infinity', '0.001', '100.31', '100000000000'):
            response = self.pay(amount_paid=amount)
            self.assertEqual(response.status_code, 200, amount)
            self.assertTrue(response.context['form'].errors, amount)
        self.assertFalse(Payment.objects.exists())

    def test_missing_bill_and_wrong_year_term_rejected(self):
        StudentFee.objects.filter(student=self.student).delete()
        self.assertTrue(self.pay().context['form'].errors)
        self.assertFalse(Payment.objects.exists())

    def test_decimal_partial_and_final_payment_exact_balance(self):
        self.assertEqual(self.pay(amount_paid='0.10').status_code, 302)
        self.assertEqual(self.pay(amount_paid='100.20').status_code, 302)
        response = self.client.get(reverse('student_financial_statement', args=[self.student.pk]))
        self.assertEqual(response.context['paid'], Decimal('100.30'))
        self.assertEqual(response.context['balance'], Decimal('0.00'))
        self.assertTrue(self.pay(amount_paid='0.01').context['form'].errors)

    def test_void_preserves_receipt_and_audit_excludes_totals_and_retry_does_not_reactivate(self):
        data = self.data()
        self.client.post(reverse('record_payment'), data)
        payment = Payment.objects.get()
        url = reverse('void_payment', args=[payment.pk])
        self.client.get(url)
        payment.refresh_from_db()
        self.assertFalse(payment.is_voided)
        self.client.post(url, {'void_reason': ''})
        payment.refresh_from_db()
        self.assertFalse(payment.is_voided)
        self.client.post(url, {'void_reason': 'Duplicate bank notice'})
        payment.refresh_from_db()
        self.assertTrue(payment.is_voided)
        self.assertEqual(payment.voided_by, self.staff[0, 'accountant'])
        self.assertIsNotNone(payment.voided_at)
        old_time = payment.voided_at
        self.client.post(url, {'void_reason': 'Overwrite'})
        self.client.post(reverse('record_payment'), data)
        payment.refresh_from_db()
        self.assertEqual(payment.voided_at, old_time)
        self.assertEqual(payment.void_reason, 'Duplicate bank notice')
        statement = self.client.get(reverse('student_financial_statement', args=[self.student.pk]))
        self.assertEqual(statement.context['paid'], Decimal('0'))
        self.assertContains(statement, 'Voided')
        self.assertEqual(Payment.objects.count(), 1)

    def test_payment_fields_and_void_audit_are_immutable(self):
        payment = self.payment()
        for field, value in [('amount_paid', Decimal('50')), ('school_id', self.schools[1].pk),
                ('student_id', self.students[0][1].pk), ('notes', 'edit'), ('receipt_number', 'new')]:
            setattr(payment, field, value)
            with self.assertRaises(ValidationError):
                payment.save()
            payment.refresh_from_db()
        self.client.post(reverse('void_payment', args=[payment.pk]), {'void_reason': 'Correction'})
        payment.refresh_from_db()
        payment.is_voided = False
        with self.assertRaises(ValidationError):
            payment.save()

    def test_deletion_and_parent_cascade_cannot_destroy_payment_history(self):
        payment = self.payment()
        with self.assertRaises(ValidationError):
            payment.delete()
        with self.assertRaises(ProtectedError), transaction.atomic():
            Payment.objects.filter(pk=payment.pk).delete()
        StudentFee.objects.filter(student=self.student).delete()
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.student.delete()
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())

    def test_model_amount_validators(self):
        structure = self.structure()
        fee = StudentFee.objects.get(student=self.student)
        for obj, field in [(structure, 'amount'), (fee, 'total_expected')]:
            for value in (Decimal('-1'), Decimal('NaN'), Decimal('Infinity')):
                setattr(obj, field, value)
                with self.assertRaises(ValidationError):
                    obj.save()
        for value in (Decimal('0'), Decimal('-1'), Decimal('NaN'), Decimal('Infinity')):
            with self.assertRaises(ValidationError):
                self.payment(amount=str(value))

    def test_bill_generation_is_idempotent_and_uses_term_enrollment_not_current_class(self):
        StudentFee.objects.filter(school=self.school).delete()
        self.structure()
        later_class = ClassStream.objects.create(school=self.school, name='PRIMARY 2', code='P2')
        type(self.student).objects.filter(pk=self.student.pk).update(current_class=later_class)
        self.assertEqual(generate_student_fees_for_term(school=self.school, term=self.term), 2)
        self.assertEqual(generate_student_fees_for_term(school=self.school, term=self.term), 0)
        self.assertEqual(StudentFee.objects.get(student=self.student).total_expected, Decimal('45.15'))
        FeeStructure.objects.filter(school=self.school).update(amount=Decimal('99'))
        generate_student_fees_for_term(school=self.school, term=self.term)
        self.assertEqual(StudentFee.objects.get(student=self.student).total_expected, Decimal('45.15'))

    def test_generation_excludes_inactive_enrollment_and_foreign_term(self):
        StudentFee.objects.filter(school=self.school).delete()
        self.structure()
        StudentEnrollment.objects.filter(student=self.student).update(status='Transferred')
        self.assertEqual(generate_student_fees_for_term(school=self.school, term=self.term), 1)
        self.assertFalse(StudentFee.objects.filter(student=self.student).exists())
        with self.assertRaises(ValidationError):
            generate_student_fees_for_term(school=self.school, term=self.assignments[1].term)

    def test_templates_do_not_create_debt_or_inflate_reports(self):
        StudentFee.objects.filter(school=self.school).delete()
        self.structure()
        self.assertEqual(self.client.get(reverse('accountant_dashboard')).context['total_expected'], Decimal('0'))
        self.assertEqual(self.client.get(reverse('debtors_list')).context['debtors'], [])
        rows = self.client.get(reverse('class_collections_report')).context['class_data']
        self.assertEqual(rows[0]['total_expected'], Decimal('0'))
        details = self.client.get(reverse('class_collection_detail', args=[self.stream.pk]))
        self.assertEqual(details.context['class_total_expected'], Decimal('0'))

    def test_overpaid_student_cannot_offset_another_students_debt(self):
        self.payment(amount='120.40')  # Retain legacy/imported overpayment as credit.
        dashboard = self.client.get(reverse('accountant_dashboard')).context
        self.assertEqual(dashboard['total_collected'], Decimal('120.40'))
        self.assertEqual(dashboard['outstanding_balance'], Decimal('100.30'))
        self.assertEqual(dashboard['total_overpaid'], Decimal('20.10'))
        statement = self.client.get(reverse('student_financial_statement', args=[self.student.pk])).context
        self.assertEqual(statement['credit'], Decimal('20.10'))
        self.assertEqual(statement['outstanding'], Decimal('0'))
        self.assertTrue(self.pay(amount_paid='1').context['form'].errors)

    def test_foreign_finances_never_enter_our_totals_or_history(self):
        self.payment(index=1, amount='999.99')
        self.payment(amount='30.10')
        for route, key in [('accountant_dashboard', 'total_collected'), ('daily_collection_report', 'total_collection')]:
            response = self.client.get(reverse(route))
            self.assertEqual(response.context[key], Decimal('30.10'))
            self.assertNotContains(response, '999.99')
        statement = self.client.get(reverse('student_financial_profile', args=[self.student.pk]))
        self.assertEqual(len(statement.context['payments']), 1)

    def test_historical_term_reporting_and_foreign_term_filter(self):
        second = Term.objects.create(school=self.school, academic_year=self.year, name='Term 2')
        StudentFee.objects.create(school=self.school, student=self.student, academic_year=self.year,
            term=second, total_expected=Decimal('20'))
        Payment.objects.create(school=self.school, student=self.student, academic_year=self.year,
            term=second, amount_paid=Decimal('10'))
        for route in ('accountant_dashboard', 'debtors_list', 'class_collections_report'):
            response = self.client.get(reverse(route), {'term': second.pk})
            self.assertEqual(response.context['current_term'], second)
            self.assertEqual(self.client.get(reverse(route), {'term': self.assignments[1].term_id}).status_code, 404)
            self.assertEqual(self.client.get(reverse(route), {'term': 'bad'}).status_code, 404)
        url = reverse('student_financial_statement', args=[self.student.pk])
        self.assertEqual(self.client.get(url, {'term': second.pk}).context['balance'], Decimal('10'))
        self.assertEqual(self.client.get(url, {'term': self.term.pk}).context['balance'], Decimal('100.30'))

    def test_student_statement_uses_authenticated_identity_ignores_other_student_query(self):
        self.payment(amount='30.10')
        self.payment(student=self.students[0][1], amount='44.44')
        self.client.force_login(self.student.user)
        response = self.client.get(reverse('student_finances'), {'student': self.students[0][1].pk})
        self.assertEqual(response.context['student'], self.student)
        self.assertEqual(response.context['paid'], Decimal('30.10'))
        self.assertNotContains(response, '44.44')
        self.assertEqual(self.client.get(reverse('student_finances'), {'term': self.assignments[1].term_id}).status_code, 404)
        self.assertEqual(self.client.get(reverse('payment_receipt', args=[Payment.objects.first().pk])).status_code, 403)

    def test_staff_and_teachers_cannot_enter_personal_student_statement(self):
        for user in (self.staff[0, 'accountant'], self.staff[0, 'administrator'], self.teachers[0]):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('student_finances')).status_code, 403)

    def test_csrf_required_for_payment_post(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff[0, 'accountant'])
        self.assertEqual(client.post(reverse('record_payment'), {}).status_code, 403)
        self.assertFalse(Payment.objects.exists())

    def test_non_post_methods_do_not_collect(self):
        self.assertEqual(self.client.put(reverse('record_payment'), {}).status_code, 405)
        self.assertFalse(Payment.objects.exists())

    def test_fee_configuration_duplicates_and_invalid_amounts(self):
        self.client.force_login(self.staff[0, 'administrator'])
        url = reverse('fee_configuration')
        self.client.post(url, {'action': 'create_category', 'name': 'Tuition'})
        self.client.post(url, {'action': 'create_category', 'name': 'Tuition'})
        self.assertEqual(FeeCategory.objects.filter(school=self.school, name='Tuition').count(), 1)
        category = FeeCategory.objects.get(school=self.school, name='Tuition')
        data = {'action': 'create_structure', 'academic_year': self.year.pk, 'term': self.term.pk,
                'class_stream': self.stream.pk, 'category': category.pk, 'amount': '10.20'}
        for amount in ('NaN', '-1', '0', '0.001'):
            self.client.post(url, {**data, 'amount': amount})
        self.assertFalse(FeeStructure.objects.exists())
        self.client.post(url, data)
        self.client.post(url, data)
        self.assertEqual(FeeStructure.objects.count(), 1)

    def test_non_cash_reference_required_and_can_be_collected_once(self):
        for method in ('Bank Deposit', 'Mobile Money', 'Check'):
            self.assertTrue(self.pay(payment_method=method).context['form'].errors)
        self.assertEqual(self.pay(payment_method='Mobile Money', reference_number='MOMO-12').status_code, 302)
        self.assertTrue(self.pay(payment_method='Mobile Money', reference_number='MOMO-12').context['form'].errors)
        self.assertEqual(Payment.objects.count(), 1)

    def test_debt_remains_visible_after_enrollment_is_removed(self):
        StudentEnrollment.objects.filter(student=self.student).delete()
        rows = self.client.get(reverse('debtors_list')).context['debtors']
        row = next(row for row in rows if row['student'] == self.student)
        self.assertEqual(row['balance'], Decimal('100.30'))
        self.assertIsNone(row['class'])

    def test_class_report_separates_debt_from_credit(self):
        self.payment(amount='120.40')
        row = self.client.get(reverse('class_collections_report')).context['class_data'][0]
        self.assertEqual(row['balance'], Decimal('100.30'))
        self.assertEqual(row['credit'], Decimal('20.10'))
        self.assertIsInstance(row['collection_rate'], Decimal)
        response = self.client.get(reverse('class_collection_detail', args=[self.stream.pk]))
        self.assertEqual(response.context['class_balance'], Decimal('100.30'))
        self.assertEqual(response.context['class_credit'], Decimal('20.10'))

    def test_wrong_year_term_cannot_collect(self):
        from core.models import AcademicYear
        other = AcademicYear.objects.create(school=self.school, name='2027-2028')
        response = self.pay(academic_year=other.pk)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(Payment.objects.exists())

    def test_receipt_preserves_cents_and_school_name(self):
        payment = self.payment(amount='0.10')
        response = self.client.get(reverse('payment_receipt', args=[payment.pk]))
        self.assertContains(response, '0.10 RWF')
        self.assertContains(response, self.school.name)

    def test_daily_report_can_limit_to_term_and_excludes_voided_payments(self):
        payment = self.payment()
        self.client.post(reverse('void_payment', args=[payment.pk]), {'void_reason': 'Correction'})
        second = Term.objects.create(school=self.school, academic_year=self.year, name='Term 2')
        Payment.objects.create(school=self.school, student=self.student, academic_year=self.year,
            term=second, amount_paid=Decimal('10.20'))
        url = reverse('daily_collection_report')
        self.assertEqual(self.client.get(url).context['total_collection'], Decimal('10.20'))
        self.assertEqual(self.client.get(url, {'term': self.term.pk}).context['total_collection'], Decimal('0'))
        self.assertEqual(self.client.get(url, {'term': self.assignments[1].term_id}).status_code, 404)

    def test_malformed_legacy_school_links_are_hidden_even_from_our_staff(self):
        payment = self.payment()
        Payment.objects.filter(pk=payment.pk).update(student=self.students[1][0])
        for name in ('payment_receipt', 'void_payment'):
            self.assertEqual(self.client.get(reverse(name, args=[payment.pk])).status_code, 404)
            self.assertEqual(self.client.post(reverse(name, args=[payment.pk]), {'void_reason': 'x'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('daily_collection_report')).context['total_transactions'], 0)
        self.assertEqual(self.client.get(reverse('accountant_dashboard')).context['total_collected'], Decimal('0'))

    def test_account_deactivation_and_ambiguous_membership_fail_closed(self):
        user = self.staff[0, 'accountant']
        SchoolMembership.objects.create(user=user, school=self.schools[1], role='accountant')
        self.assertEqual(self.client.get(reverse('accountant_dashboard')).status_code, 403)
        SchoolMembership.objects.filter(user=user, school=self.schools[1]).delete()
        user.is_active = False
        user.save()
        self.assertEqual(self.client.get(reverse('accountant_dashboard')).status_code, 302)

    def test_no_current_term_has_safe_empty_state_and_history_is_still_selectable(self):
        Term.objects.filter(school=self.school).update(is_current=False)
        response = self.client.get(reverse('accountant_dashboard'))
        self.assertFalse(response.context['finance_ready'])
        self.assertEqual(response.context['total_expected'], Decimal('0'))
        response = self.client.get(reverse('accountant_dashboard'), {'term': self.term.pk})
        self.assertEqual(response.context['total_expected'], Decimal('200.60'))

    def test_multi_category_decimal_bill_total_and_generation_does_not_change_payment(self):
        StudentFee.objects.filter(school=self.school).delete()
        self.structure(amount='0.10')
        category = FeeCategory.objects.create(school=self.school, name='Lunch')
        FeeStructure.objects.create(school=self.school, academic_year=self.year, term=self.term,
            class_stream=self.stream, category=category, amount=Decimal('0.20'))
        generate_student_fees_for_term(school=self.school, term=self.term)
        self.assertEqual(StudentFee.objects.get(student=self.student).total_expected, Decimal('0.30'))
        self.assertEqual(self.pay(amount_paid='0.30').status_code, 302)
        payment = Payment.objects.get()
        before = (payment.amount_paid, payment.receipt_number, payment.date_paid)
        generate_student_fees_for_term(school=self.school, term=self.term)
        payment.refresh_from_db()
        self.assertEqual((payment.amount_paid, payment.receipt_number, payment.date_paid), before)

    def test_statement_without_current_term_uses_one_period_and_never_offsets_terms(self):
        self.payment(amount='120.40')
        second = Term.objects.create(school=self.school, academic_year=self.year, name='Term 2')
        StudentFee.objects.create(school=self.school, student=self.student, academic_year=self.year,
            term=second, total_expected=Decimal('50'))
        Term.objects.filter(school=self.school).update(is_current=False)
        response = self.client.get(reverse('student_financial_statement', args=[self.student.pk]))
        self.assertEqual(response.context['term'], second)
        self.assertEqual(response.context['outstanding'], Decimal('50'))
        self.assertEqual(response.context['credit'], Decimal('0'))

    def test_inactive_student_cannot_read_personal_finances(self):
        self.client.force_login(self.student.user)
        SchoolMembership.objects.filter(user=self.student.user).update(is_active=False)
        self.assertEqual(self.client.get(reverse('student_finances')).status_code, 403)

    def test_platform_payment_editor_cannot_bypass_collection_or_erase_ledger(self):
        from core.admin import PaymentAdmin
        from django.contrib import admin
        from django.test import RequestFactory
        request = RequestFactory().get('/admin/')
        request.user = get_user_model().objects.create_superuser(username='platform-finance-test')
        model_admin = PaymentAdmin(Payment, admin.site)
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertIn('notes', model_admin.get_readonly_fields(request, self.payment()))
