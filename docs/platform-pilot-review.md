# SaaS platform completion and controlled-pilot readiness

Continues `7738b6f` on `development/teacher-module-verification`. All teacher,
student, school-administration and finance milestones remain intact. No model
field/Meta declarations or migrations change; active production settings, WSGI
configuration and hosting environment remain untouched.

## Functional readiness

- School applications create a pending tenant and a password-validated, hashed
  initial administrator without staff/superuser privileges. A unique, valid
  administrator recovery email is required. Submitted roles/status/global flags
  cannot promote the applicant. Duplicate username/race errors do not leave a
  partially created school. Public password fields are marked sensitive.
- `/platform/schools/` is active staff-superuser-only. Approval, rejection,
  suspension and reactivation use explicit validated state transitions, a school
  row lock and reviewer/time audit. Approval requires a valid active initial
  administrator with an unambiguous email and no cross-school account ownership.
  GET does not change status; POST requires CSRF and confirmation. Repeated or
  invalid transitions fail without rewriting review metadata.
- The existing school admin actions call the same service instead of unrestricted
  bulk updates. Direct status editing, school creation and deletion in that
  editor are disabled. The school list links to the dedicated review workflow.
  Operators do not implicitly gain access to school portals.
- Suspension denies subsequent school administrator, teacher, accountant and
  student access, including homework downloads and password recovery. Reactivation
  preserves disabled memberships and all prior academic/financial records.
  Unknown membership roles fail closed even at the generic school landing page.
- `/school/setup/` gives an ordered, school-scoped academic setup checklist:
  current period, classes, subjects, curriculum, teacher, assignment and enrollment.
  Its completion is not presented as proof of infrastructure readiness.
- Canonical HTTPS origins prevent setup/recovery links from using the request
  Host in the reviewed pilot profile. Account links remain single-use and
  expiring; emails do not display initial credentials or print tokens. Existing
  console/file/dummy backend guards remain intact.

## Pilot infrastructure prepared and isolated checks

`config/settings_pilot.py` is opt-in and not activated. Its pure environment
validator rejects missing/weak secrets, DEBUG, wildcard/mismatched hosts,
non-HTTPS account origins, non-PostgreSQL/TLS-unverified database configuration,
ambiguous SSL query parameters, ephemeral-media acknowledgments, invalid sender
or incomplete/contradictory SMTP settings. A subprocess loads the profile and
runs Django security checks without connecting services. Short initial HSTS
without subdomains/preload is deliberate, not a claim of mature TLS operations.

`PrivateDocumentStorage` disables public URLs, uses restrictive permissions and
blocks traversal/symlink escapes. Homework upload names are opaque and school
prefixed; authorized download views remain the access boundary. Tests reopen
files using an independent storage instance and exercise private homework through
teacher/student HTTP views. Existing files remain readable by their original keys
when their bytes exist in the configured root. Existing missing file metadata no
longer forces a remote/file-size read during ordinary homework form editing.
This implements a persistent-filesystem interface; actual host mount durability,
backup, restart recovery and encryption have not been verified or provisioned.

A real loopback-only SMTP test sends a synthetic message through Django's SMTP
backend into a local test server in memory. Separate mocked transport tests check
STARTTLS/authentication and safe failure behavior. This verifies application
wiring; it does not prove an external sender's TLS, deliverability, ownership,
SPF/DKIM/DMARC or bounce handling. No real recipient received email.

Security events use existing `django_admin_log` rows inside transactions and
allowlisted JSON logs after commit. Lifecycle/application events, authentication,
and request-context membership/grade/payment/enrollment/homework changes are
covered, including homework/membership deletion. No password, reset URL, request
body or email body is logged. Actor context resets between requests. Operational
middleware emits request IDs, route names, response status and duration. The
pilot profile redacts Django HTTP exception/request representations. Hosting,
proxy, mail service and external error reporting need independent redaction.
Audit retention and external alert delivery are not verified.

An opt-in tenant mutation guard serializes request writes with lifecycle changes
using the same school row lock, rechecks active membership/status after locking,
and rolls back failed responses. Local tests verify the status recheck and
rollback; PostgreSQL concurrency semantics are explicitly unverified here.

`/health/live/` is public and database-free. `/platform/readiness/` is operator-only,
returns 503 for unavailable database/storage, and exposes no paths or credentials.
It tests basic dependency accessibility, not durability, backup age or SMTP delivery.
`ops/requirements-pilot.lock` captures tested package versions without MySQL
drivers or private URLs; clean-install reproducibility/security review remains a
release gate. Existing requirements and production settings are preserved.

## End-to-end evidence

The synthetic HTTP workflow executes registration → approval → administrator
single-use password setup → year/term and activation → classes/subjects and
curriculum → teacher/accountant invitation → teacher assignment → student account
and enrollment → attendance → private homework upload/download → draft grades →
finalization → student PDF report card → fee category/structure → assigned bill →
bank payment and receipt → idempotent retry → student zero-balance statement →
suspension/access denial → reactivation with grades/payments intact. Cross-school
student registration and unauthorized student payment attempts are denied. Existing
cross-school/cross-student, inactive membership and finance integrity suites remain.

The full command is `python manage.py test --settings=config.settings_academic_test`.
**Result: 300 tests discovered; 297 passed, 3 PostgreSQL-only tests skipped,
in 58.130 seconds.** All 266 prior tests remain passing. The 34 new tests include
31 passing local/platform checks and 3 unexecuted PostgreSQL checks.
The exact output is preserved in the recovery package.
The settings were independently checked to contain only in-memory SQLite and no
routers. Known pre-existing warnings concern missing collected staticfiles and
xhtml2pdf's unsupported border-spacing. No production data is used.

## Explicit blockers and decisions

1. PostgreSQL binaries, initdb and Docker are absent. A local package-manager
   attempt failed because the workspace prohibits its required privilege
   separation. No provider was selected/provisioned and no production or external
   PostgreSQL endpoint was contacted. Three PostgreSQL-only tests are skipped on
   SQLite: competing payments against one balance, concurrent retry idempotency,
   and exact PostgreSQL Decimal sums. Loopback-only acknowledged settings and
   instructions are prepared in `ops/pilot-readiness.md`; an approved local/server
   environment must actually run them before a concurrent pilot.
2. Approve a private durable storage environment and retention/scanning/backup
   policy; demonstrate restart and restore. Approve an SMTP sender and verify
   real delivery. Approve a restricted durable log sink, alert recipients,
   operator MFA and external authentication/signup rate limiting. No external
   service configuration or notifications have been enabled.
3. A verified production backup restore still requires explicit approval,
   appropriate backup and an isolated destination. Target **28 October 2026**,
   with **4 November** as the prior plan's latest safe deadline before reported
   **11 November** expiry. Source recovery verification does not verify a DB dump.
4. Email uniqueness is checked at application level, not protected by a new
   unique DB constraint. Ambiguous imports/races block recovery and need review.
   DB audit rows can be altered by privileged DB operators and cascade on user
   deletion; deactivate accounts and review immutable retention before expansion.
   Bulk/direct SQL changes bypass ORM audit and need separate controls.
5. Large-school load/concurrency, real browsers, print appearance, CDN/CSP/static
   assets, reverse-proxy trust, actual TLS and a fresh dependency install remain
   unverified. The pilot profile must not be activated or deployed automatically.

Functional workflows are ready for a controlled staging rehearsal. An external
multi-user pilot remains blocked by the infrastructure and operational evidence
above. The next work is to close those gates with approved services/environments,
not to claim deployment readiness or begin deployment.

## Changed files

- `config/pilot.py`
- `config/settings_pilot.py`
- `config/settings_postgres_pilot_test.py`
- `config/urls.py`
- `core/private_storage.py`
- `core/teacher_forms.py`
- `core/views.py`
- `docs/platform-pilot-review.md`
- `docs/postgresql-backup-and-portability-plan.md`
- `ops/pilot-readiness.md`
- `ops/requirements-pilot.lock`
- `tenants/access.py`
- `tenants/admin.py`
- `tenants/admin_forms.py`
- `tenants/admin_services.py`
- `tenants/apps.py`
- `tenants/audit.py`
- `tenants/audit_signals.py`
- `tenants/forms.py`
- `tenants/pilot_middleware.py`
- `tenants/pilot_views.py`
- `tenants/platform_services.py`
- `tenants/platform_views.py`
- `tenants/templates/admin/tenants/school/change_list.html`
- `tenants/templates/tenants/platform_schools.html`
- `tenants/templates/tenants/school_home.html`
- `tenants/templates/tenants/setup_checklist.html`
- `tenants/test_pilot_end_to_end.py`
- `tenants/test_platform_pilot.py`
- `tenants/test_postgres_pilot.py`
- `tenants/views.py`
