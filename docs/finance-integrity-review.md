# Accounting and finance integrity checkpoint

Continues the teacher, student and school-administration work on
`development/teacher-module-verification`, from `f87625b`.

## Completed behavior

- Approved, active school membership and administrator/accountant authorization
  govern finance pages, collection and voiding. Student personal statements
  derive identity from the authenticated school membership and user; a supplied
  student query parameter cannot select another student. Financial staff do not
  gain access to the student-only endpoint. School-admin fee configuration stays
  administrator-only; accountants collect against assigned bills.
- New payment forms have signed, actor/school-bound, 24-hour submission tokens.
  A repeated submission returns the original receipt, including after settlement
  or voiding. Reusing a token with changed financial details is rejected. The
  existing globally unique receipt field is the durable idempotency boundary.
  Bill locks and a second balance/replay check serialize collection on PostgreSQL.
- A distinct form permits a legitimate separate equal cash payment. Blank
  references normalize to NULL, so unrelated cash payments no longer collide on
  an empty unique string. Non-cash collection requires a transaction reference;
  normalized duplicate references are rejected without disclosing other records.
- Only positive, finite, scale-valid Decimal payments can be collected. New
  overpayments remain disallowed under the existing collection policy. Existing
  overpayments are retained and shown as credits; one student's credit never
  reduces another student's outstanding balance. There is no float conversion
  in the enabled financial calculations. Aggregate amounts normalize to two
  places before balance comparisons, including SQLite's Decimal aggregate noise.
- Existing payment money, identity, receipt, collector, date and notes cannot be
  edited through model save. A single void retains actor, reason and time;
  subsequent changes to its audit or active status are rejected. Direct platform
  admin payment creation/deletion is disabled and recorded notes are read-only. Payment delete,
  queryset delete and parent ORM cascades are blocked. The normal void workflow
  is POST/CSRF protected, authorized and locked; GET only confirms.
- Fee generation uses Active enrollment in the selected school/year/term, not
  the mutable current class. It adds missing obligations idempotently, holds the
  school lock, and preserves previously assigned bills and all payment history.
  Fee and obligation model validation rejects negative/nonfinite amounts; the
  setup UI continues requiring positive structure amounts.
- Assigned obligations alone create debt. Fee templates are not silently counted
  as bills. Debtors remain visible when enrollment is removed or transferred.
  Class reports use period enrollment; unassigned obligations remain visible in
  school totals, debtor lists and personal statements rather than being guessed
  into a class. Class debt and credit are independently summed per student.
- Dashboard, debtors, class summary/detail, daily collection filters and student
  statements support authorized historical term selection. Daily reporting uses
  local dates and excludes voided payments. Statements include voided history
  with status and exclude it from paid totals. Receipts and reports retain cents.
- Accountant navigation points to working workflows; unavailable placeholder
  links and accidental Markdown fences were removed. Receipts link to voiding,
  statements link to staff receipts, and students have a personal Finances link.

## Existing constraints inspected before changes

Source models and migrations 0029, 0030, 0031, 0032, 0034, 0044 and the school-FK
migration were reviewed; this is a source review, not an inspection of production.

- FeeCategory: unique school/name; school nullable, protected.
- FeeStructure: unique year/term/class/category; Decimal(12,2); nullable school;
  year/term/class/category relationships currently cascade.
- StudentFee: unique student/year/term; Decimal(12,2); student/year/term PROTECT;
  school nullable. The assigned total is a snapshot, not category line items.
- Payment: globally unique nullable reference and receipt, Decimal(12,2), nullable
  protected school; student/year/term CASCADE and audit users SET_NULL.
- Cross-school FK consistency, positive payments, nonnegative bills, immutable
  ledger and void invariants have no complete database constraint enforcement.

No fields, Meta options, constraints or migration files changed. Python validation
and deletion guards do not require a database migration or rewrite legacy rows.

## Verification and remaining risks

Full command: `python manage.py test --settings=config.settings_academic_test`.
Result: **266 tests passed in 37.660 seconds**, including **45 new finance tests**.
The full output is retained in the recovery package.
The settings were verified to contain only in-memory SQLite and no routers.
The finance regression module adds authorization/CSRF, school/student isolation,
invalid amounts, cent precision, retries/references, overpayments, void audit,
immutable/deletion protection, historical reporting, missing bills, inactive or
ambiguous membership, enrollment transitions, duplicate fee setup and generation.
The complete suite also retains all teacher, student and school-admin regressions.

Release review:

1. SQLite cannot demonstrate PostgreSQL row-lock/concurrent transaction behavior.
   PostgreSQL concurrency testing with synthetic data needs a separately approved
   isolated environment. Receipt uniqueness is present already; no new production
   schema protection was assumed. Direct SQL, bulk_update and QuerySet.update
   bypass model save guards; do not use these to modify financial records.
2. A later explicit migration review should consider NOT NULL school fields,
   amount checks, stronger foreign-key tenant consistency, payment FK PROTECT,
   retention of audit actors and database-enforced immutable ledger. Before any
   such migration, obtain a verified backup/restore, inventory malformed/null
   rows, review a cleanup policy without deleting or rewriting payment history,
   assess locks and rollout/rollback. No cleanup is authorized by this milestone.
3. The pre-existing global reference constraint means a legitimate identical
   reference at two schools is rejected. Changing to per-school normalized
   uniqueness requires a reviewed schema/data policy. Reference matching remains
   case-sensitive to preserve existing semantics; confirmation of provider codes
   is a later policy decision.
4. This is student fee collection, not a full double-entry ledger. Refunds,
   credit allocation, discounts, bill adjustments, bank settlement imports,
   invoice line items and external gateway webhook reconciliation need explicit
   accounting rules and likely new audit models. No arbitrary adjustment or
   refund UI is exposed. Legacy/imported credits are displayed without silently
   moving money across students or terms. Payment notes are immutable and void
   reasons remain visible in the student's own statement.
5. Fee generation is additive: changing a template does not revise a historic
   obligation, and adding a category after billing needs an approved adjustment
   workflow. Completed/Transferred enrollments are intentionally not newly billed
   by automatic generation. Already billed historical debt remains visible.
6. Class reports use per-student queries and need pagination/batched aggregation
   before large deployments. No real browser/print/static asset verification or
   production-like load test was performed. Existing suite emits the known
   missing staticfiles warning and xhtml2pdf unsupported border-spacing warning.
7. Production backup status remains unverified. Follow
   `postgresql-backup-and-portability-plan.md`: target first approved restore by
   28 October, latest safe completion 4 November 2026, before reported expiry on
   11 November. No production data, credentials or hosting were accessed.

Recommended next MVP milestone: operational readiness for a controlled pilot —
private durable media, real account email delivery, tenant-aware audit/monitoring,
configuration/static checks and PostgreSQL rehearsal with synthetic data. Carry
out the separately approved backup/restore before the preservation deadline even
if feature development continues. Hosting migration and deployment remain separate
approval decisions; do not deploy from this checkpoint automatically.

## Changed files

- `config/urls.py`
- `core/admin.py`
- `core/finance.py`
- `core/models.py`
- `core/templates/accountant/class_collection_detail.html`
- `core/templates/accountant/class_collections_report.html`
- `core/templates/accountant/components/sidebar.html`
- `core/templates/core/accountant_dashboard.html`
- `core/templates/core/daily_collection_report.html`
- `core/templates/core/debtors_list.html`
- `core/templates/core/finance_ledger.html`
- `core/templates/core/finance_period_filter.html`
- `core/templates/core/payment_receipt.html`
- `core/templates/core/record_payment.html`
- `core/templates/core/student_base.html`
- `core/views.py`
- `docs/finance-integrity-review.md`
- `docs/postgresql-backup-and-portability-plan.md`
- `tenants/test_finance_integrity.py`
