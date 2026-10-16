# Teacher grading milestone

Base: main at f2c05f8183008ad40640d8e10764f523ba87caaf.
Development branch: development/teacher-module-verification.

## Checkpoint reconciliation

The two original checkpoint test files have now been supplied and reconciled.
All six roster tests are retained in `tenants/test_teacher_student_access.py`.
Its administrator test now creates an actual administrator membership, instead
of testing an account with no school membership. The fixture is imported as a
module to avoid discovering its unrelated TestCase a second time.

The original grade file is consolidated into
`tenants/test_teacher_grading_workflow.py`; it is intentionally not copied as a
second duplicate suite. Two unique GET/anonymous cases were added. All original
assertions are represented, including draft status, unchanged locked marks, and
finalization actor/time. Shared two-school setup is in
`tenants/teacher_test_fixtures.py`, a plain mixin with no inherited test methods.

| Original grading case | Consolidated case |
| --- | --- |
| Own grade page | teacher_can_open_own_grade_page |
| Other school grade page | cross_school_assignment_rejected_for_get_and_post |
| Valid submission | saves_and_calculates_grade |
| Above-limit marks | invalid_numeric_values_leave_no_records |
| Foreign student submission | foreign_student_fields_cannot_create_foreign_grade |
| Finalized grade edit | tampered_finalized_marks_reject_entire_batch |
| Successful finalization | finalization_records_actor_and_time |
| Confirmation required | finalization_requires_confirmation |
| Repeat finalization | repeated_finalization_preserves_audit |
| Foreign grade finalization | foreign_grade_cannot_be_finalized |
| Anonymous grade page | anonymous_user_cannot_open_grade_page |
| Inactive membership | inactive_membership_blocks_grades_and_finalization |

Reconciled complete suite: **85 tests passed**, before attendance/homework work.

## Changes

- Allow unchanged finalized rows in bulk submissions; reject altered locked marks
  and preserve atomic validation of the entire submitted batch.
- Lock existing grade rows during saving, coordinating with finalization's row
  lock and model guard against modifying a finalized grade.
- Restore View Students, Input Grades, and teacher dashboard navigation.
- Show scoped grade values and assignment attendance counts on the roster.
- Add regression tests for finalization, calculations, enrollment, tenant and
  role restrictions, CSRF, and bulk submission behavior.

## Safety and limitations

No schema changes, production database commands, remote pushes, or deployments.
Use only `python manage.py test --settings=config.settings_academic_test`.
Runtime verification must confirm the sole database is in-memory SQLite and
there are no database routers before running tests.

The unpinned requirements resolved in this environment; the legacy mysqlclient
package could not build because pkg-config and MySQL development libraries are
absent. The isolated test environment excludes only mysqlclient. Deployment
requirements are unchanged. Dependency reproducibility remains follow-up work.

SQLite cannot verify PostgreSQL row-lock concurrency semantics. A separate
isolated PostgreSQL integration run is still required before a production pilot.
The broader teacher module, homework, student portal, finance, and onboarding
remain separate milestones; this change does not certify the whole SaaS MVP.

## Verification

- Runtime assertions verified exactly one database, SQLite `:memory:` for both
  NAME and TEST.NAME, with no database routers.
- New grading workflow suite: 24 tests passed.
- Initial full run: 53 existing tests passed; new fixture failed because it
  duplicated automatic enrollment. The fixture was corrected and all 24 new
  tests then passed.
- Python syntax compilation and git diff whitespace validation passed.
- Test middleware warns that staticfiles/ is absent in this fresh checkout;
  production static asset collection has not been run here.
- Final combined run: **77 tests passed in 62.095 seconds** using
  `python manage.py test --settings=config.settings_academic_test`.
  Django system checks reported no issues.
- Test runtime: Python 3.12, Django 6.1.2, django-unfold 0.110.0.
