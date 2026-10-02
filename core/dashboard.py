from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import FeeStructure, Payment, StudentEnrollment, StudentFee, StudentProfile, Term

ZERO = Decimal("0")


def _expected_for_term(term):
    """Same rule as the debtors list: StudentFee if present, else the class FeeStructure."""
    fees = StudentFee.objects.filter(term=term)
    expected = fees.aggregate(t=Sum("total_expected"))["t"] or ZERO
    has_fee = set(fees.values_list("student_id", flat=True))
    per_class = {
        r["class_stream"]: r["t"]
        for r in FeeStructure.objects.filter(term=term).values("class_stream").annotate(t=Sum("amount"))
    }
    seen = set()
    for e in StudentEnrollment.objects.filter(term=term).values("student_id", "class_stream_id"):
        sid = e["student_id"]
        if sid in has_fee or sid in seen:
            continue
        seen.add(sid)
        expected += per_class.get(e["class_stream_id"], ZERO)
    return expected


def dashboard_callback(request, context):
    term = Term.objects.filter(is_current=True).select_related("academic_year").first()
    today = timezone.localdate()
    valid = Payment.objects.filter(is_voided=False)

    collected_today = valid.filter(date_paid__date=today).aggregate(t=Sum("amount_paid"))["t"] or ZERO
    collected_term = expected = ZERO
    by_method, voided_count = [], 0

    if term:
        term_payments = valid.filter(term=term)
        collected_term = term_payments.aggregate(t=Sum("amount_paid"))["t"] or ZERO
        expected = _expected_for_term(term)
        voided_count = Payment.objects.filter(term=term, is_voided=True).count()
        for row in term_payments.values("payment_method").annotate(t=Sum("amount_paid")).order_by("-t"):
            pct = int(row["t"] * 100 / collected_term) if collected_term else 0
            by_method.append({"method": row["payment_method"], "total": row["t"], "pct": pct})

    outstanding = max(expected - collected_term, ZERO)
    rate = int(min(collected_term * 100 / expected, 100)) if expected else 0

    context["sms"] = {
        "term": term,
        "total_students": StudentProfile.objects.count(),
        "collected_today": collected_today,
        "collected_term": collected_term,
        "expected": expected,
        "outstanding": outstanding,
        "rate": rate,
        "voided_count": voided_count,
        "by_method": by_method,
        "recent": Payment.objects.select_related("student", "term").order_by("-date_paid")[:8],
    }
    return context