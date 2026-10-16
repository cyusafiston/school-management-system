"""Finance entry points. No production connections or schema changes."""
from decimal import Decimal, InvalidOperation
import uuid

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.http import HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from tenants.access import require_school_context, require_school_role
from .models import Payment, StudentFee, StudentProfile, Term

ZERO = Decimal('0.00')
SALT = 'finance.payment-submission.v1'


def money(value):
    """Canonical scale for DecimalField sums (SQLite aggregates add trailing noise)."""
    return Decimal(value or ZERO).quantize(Decimal('0.01'))


def period(request, school):
    terms = Term.objects.filter(school=school, academic_year__school=school).select_related('academic_year')
    raw = request.GET.get('term')
    if raw is not None and raw != "":
        if not raw.isdecimal():
            from django.http import Http404
            raise Http404
        return get_object_or_404(terms, pk=int(raw))
    return terms.filter(is_current=True).first()


def records(model, school):
    """Fail closed on malformed legacy foreign keys as well as direct tenancy."""
    return model.objects.filter(school=school, student__school=school,
        academic_year__school=school, term__school=school,
        term__academic_year_id=F('academic_year_id'))


def replay_matches(payment, data):
    try:
        return (payment.student_id == int(data.get('student', '')) and
            payment.academic_year_id == int(data.get('academic_year', '')) and
            payment.term_id == int(data.get('term', '')) and
            payment.amount_paid == Decimal(data.get('amount_paid', '')) and
            payment.payment_method == data.get('payment_method') and
            (payment.reference_number or '') == data.get('reference_number', '').strip() and
            (payment.notes or '') == data.get('notes', '').strip())
    except (ValueError, TypeError, InvalidOperation):
        return False


@login_required
def record_payment(request):
    from .views import PaymentForm
    context = require_school_context(request.user)
    require_school_role(context, 'administrator', 'accountant')
    if request.method not in ('GET', 'POST'):
        return HttpResponseNotAllowed(['GET', 'POST'])
    if request.method == 'GET':
        token = signing.dumps({'school': context.school.pk, 'user': request.user.pk,
                              'nonce': uuid.uuid4().hex}, salt=SALT)
        form = PaymentForm(school_context=context, initial={'submission_token': token})
    else:
        form = PaymentForm(request.POST, school_context=context)
        try:
            payload = signing.loads(request.POST.get('submission_token', ''), salt=SALT, max_age=86400)
            if payload['school'] != context.school.pk or payload['user'] != request.user.pk:
                raise signing.BadSignature
            receipt = 'REC-' + uuid.UUID(hex=payload['nonce']).hex.upper()
        except (signing.BadSignature, KeyError, ValueError, TypeError):
            return HttpResponseBadRequest('Invalid or expired payment form. Open a new payment form.')
        # The bill lock serializes collection and replay checks in PostgreSQL.
        try:
            with transaction.atomic():
                existing = Payment.objects.filter(school=context.school, receipt_number=receipt).first()
                if existing:
                    if not replay_matches(existing, request.POST):
                        return HttpResponseBadRequest('This payment form was already used for different details.')
                    return redirect('payment_receipt', payment_id=existing.pk)
                if form.is_valid():
                    payment = form.save(commit=False)
                    bill = records(StudentFee, context.school).select_for_update().get(
                        student=payment.student, term=payment.term, academic_year=payment.academic_year)
                    existing = Payment.objects.filter(school=context.school, receipt_number=receipt).first()
                    if existing:
                        if not replay_matches(existing, request.POST):
                            return HttpResponseBadRequest('This payment form has already been used.')
                        return redirect('payment_receipt', payment_id=existing.pk)
                    paid = records(Payment, context.school).filter(student=payment.student,
                        term=payment.term, is_voided=False).aggregate(total=Sum('amount_paid'))['total'] or ZERO
                    if payment.amount_paid > bill.total_expected - money(paid):
                        raise ValidationError('Payment exceeds the remaining balance.')
                    payment.school = context.school
                    payment.received_by = request.user
                    payment.receipt_number = receipt
                    payment.save()
                    return redirect('payment_receipt', payment_id=payment.pk)
        except (ValidationError, IntegrityError, StudentFee.DoesNotExist):
            form.add_error(None, 'Payment was not recorded. Check the bill, balance and transaction reference.')
    return render(request, 'core/record_payment.html', {'form': form, 'school': context.school})


@login_required
def ledger(request, student_id=None):
    context = require_school_context(request.user)
    personal = student_id is None
    if personal:
        require_school_role(context, 'student')
        student = get_object_or_404(StudentProfile, school=context.school, user=request.user)
    else:
        require_school_role(context, 'administrator', 'accountant')
        student = get_object_or_404(StudentProfile, school=context.school, pk=student_id)
    selected = period(request, context.school)
    if selected is None:
        # Keep a single explicit period even when the school has no current term.
        selected = Term.objects.filter(school=context.school,
            academic_year__school=context.school).order_by('-academic_year_id', '-pk').first()
    fees = records(StudentFee, context.school).filter(student=student)
    payments = records(Payment, context.school).filter(student=student)
    if selected:
        fees = fees.filter(term=selected)
        payments = payments.filter(term=selected)
    else:
        fees, payments = fees.none(), payments.none()
    expected = fees.aggregate(total=Sum('total_expected'))['total'] or ZERO
    paid = payments.filter(is_voided=False).aggregate(total=Sum('amount_paid'))['total'] or ZERO
    expected, paid = money(expected), money(paid)
    return render(request, 'core/finance_ledger.html', {
        'school': context.school, 'student': student, 'term': selected,
        'terms': Term.objects.filter(school=context.school, academic_year__school=context.school),
        'payments': payments.select_related('term', 'academic_year').order_by('-date_paid', '-pk'),
        'expected': expected, 'paid': paid, 'balance': expected - paid,
        'outstanding': max(expected-paid, ZERO), 'credit': max(paid-expected, ZERO),
        'personal': personal,
    })
