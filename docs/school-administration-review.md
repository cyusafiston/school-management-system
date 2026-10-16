# School administration milestone

Parent: 670a63a519f2ee4a9a4ea8c299a583ac41ea8cfc.
Branch: development/teacher-module-verification. Teacher and student commits retained.

## Completed workflows

- All new administration endpoints derive school and administrator role through
  active approved SchoolMembership. Anonymous, inactive, wrong-role, ambiguous,
  suspended-school and platform-superuser contexts cannot use school admin flows.
- Student registration validates scoped class/guardian/profile data, unique
  school registration numbers, and recovery email. Existing model saves allocate
  the account/membership/current enrollment transactionally. Counter alignment
  avoids collisions with imported registration numbers ahead of the saved counter.
- New student/teacher/accountant accounts have unusable passwords. Setup tokens
  go only to the saved email after commit. A user must set their first password
  through Django's validated expiring single-use flow before they can log in.
  No temporary password or setup token is displayed to school administrators.
- Enrollment management supports initial placement, pre-activity stream changes,
  completion, withdrawal and outgoing transfer. Recorded history blocks a
  same-term stream change. Outgoing current-term transfer/withdrawal revokes
  student membership without deleting profile, grades, payments or attendance.
  Administrators can reactivate a student's own school membership separately.
- New-term/year roll-forward requires explicit confirmation, creates new rows,
  completes source rows, and rolls back the whole batch on duplicate/conflicting
  target enrollments. Classes can be retained or a target class selected.
- Current term activation atomically switches only that school's term/year flags.
  It does not silently enroll students or rewrite their past academic records.
- Staff invitation and membership editing allow only teacher/accountant roles.
  Global staff/superuser flags and other schools' memberships cannot be changed.
  Shared or privileged accounts are blocked. Legacy profile roles are synchronized
  only for single-school-owned accounts to preserve TeacherAssignment validation.
- Current teaching assignments must be resolved before teacher role conversion.
  A scoped reassignment form moves teaching responsibility to an active own-school
  teacher while keeping assignment-linked attendance/homework and grades intact.
- Recovery is POST-only for school administrators and never activates a disabled
  account or changes its recovery email. Public recovery uses generic responses,
  supports new unusable-password accounts, and fails closed for duplicate email,
  missing/invalid email or ineligible memberships. Confirmation rechecks eligibility
  on both GET and POST, so revoked membership invalidates an outstanding link.
- Existing class/subject creation is reused. Scoped edit forms allow renaming and
  description changes; subject maxima cannot change once grades exist. Curriculum
  removal/required-status changes are blocked when recorded grades rely on them.
- Years and terms can be created with existing model constraints. No academic
  deletion workflow is added. Classes represent streams in the existing model.
- School-wide/class-targeted notice creation/editing feeds the secured student
  portal. Foreign classes and other schools' notices cannot be selected or edited.
- School dashboard links expose students, staff, years/terms, roll-forward and
  notices; existing academic setup/curriculum/assignment navigation remains.

## Constraint and migration safety

See administration-constraint-review.md for the inspection completed before
implementation. No models, migrations, settings, deployment scripts or production
records are changed. No production connections or live application requests were
made. Only the isolated in-memory SQLite test settings are used.

The existing TeacherRegistrationForm remains as a tested internal compatibility
API; the public teacher-management endpoint now provisions through email setup,
ignoring supplied password and privilege fields rather than issuing a password.

## Verification and fixes

The focused suite first passed 31 tests, then 49 after broader coverage. One
intermediate full run found a malformed tampered-token test URL; fixing the URL
verified the intended invalid-token page. No authorization checks were weakened.
A complete suite passed 212 tests before final edge-case additions.

Tests cover provisioning rollback and duplicates, counters/imported registrations,
email token privacy and delivery failure, old/new password handling, expired and
revoked tokens, CSRF, activation/deactivation, privilege escalation, shared accounts,
foreign GET/POST requests, record-preserving transfers, stream protection,
academic transitions, atomic roll-forward, role/assignment compatibility, notices,
and administrator → initial setup/login → teacher finalization → student access.
All actual email delivery uses the in-memory test backend; no messages are sent
to real recipients by the development tools.

Exact complete-suite command:

```sh
python manage.py test --settings=config.settings_academic_test
```

## Remaining gaps and future decisions

- A distinct recovery email is required per account; ambiguous legacy email
  records fail closed. A shared-guardian/multiple-child recovery policy needs
  a separate UI design. Email equality has application validation but no unique
  case-insensitive DB index, so concurrent cross-school creation still needs
  review alongside PostgreSQL integration testing.
- There is no persistent must-change-password flag. First-time setup is mandatory
  because no usable initial password exists. Forced periodic/administrator-issued
  password rotation would need an explicitly reviewed model/migration design.
- Mid-term multi-placement history, coordinated inter-school transfer consent,
  and arbitrary corrections to completed enrollment records need a richer audited
  workflow. This milestone marks transfer-out, preserving the original tenant;
  receiving-school registration remains independent.
- There is no durable email-job queue or new account-audit event model. Delivery
  failure leaves the account unusable and permits an administrator retry; it never
  prints tokens or provider exception payloads in application logs.
- Locks/constraint behavior still need an isolated PostgreSQL concurrency run.
  Existing class-name/assignment uniqueness has no matching DB constraint; scoped
  school locks serialize the web administration paths, but external writers can
  bypass those application guards.
- The existing default email backend is console output. Account/setup/recovery
  mail now refuses console/file/dummy delivery so live tokens are never printed
  or written by those development backends. Configure SMTP or a reviewed provider
  before real onboarding. No environment settings were changed here.
- Email infrastructure, private durable attachments, static asset collection and
  browser/visual regression checks remain pilot prerequisites. Existing test
  warnings about staticfiles and the PDF border-spacing style remain.

## Next milestone (not started)

Accounting and finance: verify school-owned fee categories/structures, student
obligations, payment recording, receipt generation, balances/arrears and voids;
protect posted foreign keys and transaction integrity, then test the full school
administrator/accountant/student boundary. Platform onboarding and infrastructure
readiness follow. No push, merge or deployment is included.

## Final preservation verification

`python manage.py test --settings=config.settings_academic_test`:
**221 tests passed in 53.824 seconds**, with no Django system-check issues.
All 160 previous tests and 61 administration tests pass. Extra final checks cover
malformed legacy profile/enrollment links, matching email/database field lengths,
blank recovery addresses, imported registration counters, delivery exceptions and
console-backend token suppression. The initial test-collection mail import was
also corrected to django.core.mail; no failed checks remain.

Reviewed the complete implementation/template/test diff. Targeted scans check
changed files for private keys, provider tokens and credential-bearing URLs;
these are not a full repository-history secrets audit. Only intended source,
templates, tests and notes are committed. Settings, models, migrations,
dependencies, deployment scripts, databases and media are excluded from changes.
