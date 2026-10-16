# Review: tenant-scoped teacher academic workflows

## Problem and resulting behavior

Teachers can now move from their dashboard to their authorized roster, grading,
attendance and homework workflows. An unchanged finalized row no longer blocks
saving other draft grades; altered locked marks still reject the whole batch.
Roster grades and attendance summaries are school- and assignment-scoped.
Attendance follows active term enrollments. Daily submissions recheck existing
records under a class lock. Homework supports validated creation/editing,
POST-only deletion and authorized attachment downloads.

## Scope and reconciliation

Original roster tests are retained. Overlapping original grading tests are
consolidated with the extended grading suite, with a mapping in
teacher-grading-review.md. Shared fixtures do not inherit duplicate test cases.
A final diff review removed stale disabled attendance/homework buttons beside
working class-page links and added a regression test for that duplication.

## Preservation review

- Reviewed the implementation, routes, templates, fixtures, tests and notes.
- Targeted scanning of changed source found no private keys, common provider
  tokens or credential-bearing connection URLs. This was a pattern scan and
  manual diff review, not a complete repository-history secrets audit.
- Only intended source, templates, tests and documentation are included.
  Credentials, databases, user media, environment files and virtual environments
  are excluded. No unexpected untracked files were found in the checkout.
- Settings, migrations, dependencies and deployment scripts are unchanged.
  No production database commands, data changes or live requests were made.
- GitHub currently reports push permission. The branch is prepared locally only;
  no remote branch or pull request has been created. Push needs user approval.

## Verification

Use only:

```sh
python manage.py test --settings=config.settings_academic_test
```

Runtime assertions verified a sole SQLite in-memory connection, including its
test database name, and no database routers before execution. Final test results
are recorded below after execution. The earlier complete suite passed 110 tests;
the final review adds one class-navigation regression case.

Known limitations: SQLite does not establish PostgreSQL concurrency behavior.
Private durable attachment storage and the absence of public media bypasses need
verification before a pilot. Legacy school-less homework needs reviewed ownership
mapping before any backfill. The fresh checkout has a missing-staticfiles warning;
asset collection has not been run. These checks do not certify the whole MVP.

## Proposed next milestone (not started)

Secure the student academic portal so teacher-entered work reaches the correct
student. Existing student views need review before routes are re-enabled.

1. Resolve student identity through active membership, approved school and the
   linked profile; derive class and term from authorized enrollments.
2. Restore dashboard/profile and subject information using scoped queries.
3. Expose only the student's finalized grades; verify report-card calculations,
   selected-term authorization and download isolation.
4. Add personal subject/daily attendance history and enrollment-authorized
   homework listings/downloads, without widening teacher-only attachment access.
5. Secure notices and academic schedule visibility for both portals, and close
   teacher password/navigation gaps through the existing authentication flow.
6. Test a two-school teacher-to-student workflow, including inactive accounts,
   revoked memberships and URL/POST manipulation, then rerun the isolated suite.

After that: school administration workflow completion, finance isolation and
payment integrity, platform onboarding, then PostgreSQL/storage pilot readiness.
No deployment is part of this proposed implementation sequence.

Final preservation run: **111 tests passed in 54.872 seconds**, with no Django
system-check issues. Whitespace validation passed. This includes the new
class-navigation regression test and all previously passing scenarios.
