"""Run only on the separately acknowledged synthetic PostgreSQL test database."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import close_old_connections, connection
from django.test import Client, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from core.finance import SALT
from core.models import StudentFee, Payment
from core.views import PaymentForm, generate_student_fees_for_term
from tenants.models import SchoolMembership
from tenants.teacher_test_fixtures import TeacherWorkflowFixture


@skipUnlessDBFeature('has_select_for_update')
class PostgreSQLConcurrencyTests(TeacherWorkflowFixture, TransactionTestCase):
    def setUp(self):
        if connection.vendor != 'postgresql' or connection.settings_dict['NAME'] != 'test_sms_pilot_synthetic':
            self.skipTest('Synthetic PostgreSQL test database required.')
        self.setUpTestData()
        self.user = get_user_model().objects.create_user(username='concurrent-accountant')
        SchoolMembership.objects.create(school=self.schools[0], user=self.user, role='accountant')
        self.student = self.students[0][0]
        self.term = self.assignments[0].term
        StudentFee.objects.create(school=self.schools[0], student=self.student, term=self.term,
            academic_year=self.term.academic_year, total_expected=Decimal('100.30'))

    def collect(self, token, amount):
        close_old_connections()
        try:
            client = Client()
            client.force_login(get_user_model().objects.get(pk=self.user.pk))
            response = client.post(reverse('record_payment'), {'student': self.student.pk,
                'academic_year': self.term.academic_year_id, 'term': self.term.pk,
                'amount_paid': amount, 'payment_method': 'Cash', 'submission_token': token})
            return response.status_code, getattr(response, 'url', None)
        finally:
            connection.close()

    def token(self):
        return signing.dumps({'school': self.schools[0].pk, 'user': self.user.pk,
            'nonce': uuid.uuid4().hex}, salt=SALT)

    def race(self, tokens, amount):
        barrier = Barrier(2, timeout=10)
        original = PaymentForm.is_valid
        def validate(form):
            result = original(form)
            if result:
                barrier.wait()
            return result
        with patch.object(PaymentForm, 'is_valid', validate), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.collect, token, amount) for token in tokens]
            return [future.result(timeout=25) for future in futures]

    def test_simultaneous_distinct_payments_cannot_overcollect(self):
        responses = self.race([self.token(), self.token()], '80.20')
        self.assertEqual(sorted(status for status, _ in responses), [200, 302])
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(Payment.objects.get().amount_paid, Decimal('80.20'))

    def test_simultaneous_retry_creates_one_payment_and_same_receipt(self):
        token = self.token()
        responses = self.race([token, token], '30.10')
        self.assertEqual(responses[0], responses[1])
        self.assertEqual(responses[0][0], 302)
        self.assertEqual(Payment.objects.count(), 1)

    def test_decimal_field_precision_is_exact_in_postgresql(self):
        from django.db.models import Sum
        Payment.objects.create(school=self.schools[0], student=self.student, term=self.term,
            academic_year=self.term.academic_year, amount_paid=Decimal('0.10'))
        Payment.objects.create(school=self.schools[0], student=self.student, term=self.term,
            academic_year=self.term.academic_year, amount_paid=Decimal('0.20'))
        self.assertEqual(Payment.objects.aggregate(total=Sum('amount_paid'))['total'], Decimal('0.30'))
