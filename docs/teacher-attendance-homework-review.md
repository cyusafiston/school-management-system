# Teacher attendance and homework review

Branch: development/teacher-module-verification (local only).
Base: main at f2c05f8. No push, merge, deployment, or production data access.

## Completed workflows

- Subject attendance selects active students enrolled in the assignment's term,
  year, and class, rather than relying on the profile's latest class. Validated
  statuses save atomically. Existing attendance loads and can be corrected.
- Subject submission locks the assignment, including first-time submissions.
- Daily roll call requires a current-term teaching assignment and active
  enrollments. It locks the class and rechecks for existing attendance inside
  the transaction before writing. Repeated submission preserves locked records.
- Teacher homework supports create, list, edit, and POST-only deletion, with
  bound form validation and retained input. School and assignment come from
  authorized server context, never posted IDs.
- Homework model validation rejects mismatched school/assignment relationships.
- Attachments accept PDF, Word, PNG, and JPEG files up to 10 MiB. Downloads
  resolve active membership, teacher ownership, school and homework IDs before
  opening storage, and return attachment responses with private/no-store and
  nosniff headers. Forms/listings use authorized download links rather than
  exposing storage URLs. Existing attachments survive edits without reupload.
- Dashboard and class links restore attendance and homework entry points;
  attendance dates render in ISO format, and feedback messages are visible.
- Legacy homework management entry delegates to the secured implementation.

## Validation

25 focused workflow tests passed. Coverage includes successful creates/updates,
role and membership failures, cross-school GET/POST manipulation, same-school
unassigned teachers, invalid dates/statuses, empty/inactive rosters, duplicate
daily submissions, homework validation, attachment limits, protected downloads,
attachment preservation on edit, delete methods and CSRF on creation endpoints.
All uploads in tests use temporary storage cleaned up after execution.

A first focused run caught model validation occurring before the server-owned
school/assignment fields were populated. The form now receives an authorized
instance before validation; the focused rerun passed.

## Integration and pilot considerations

No schema migrations are introduced or executed. Existing school-less legacy
homework remains stored, but is excluded from teacher access; any backfill must
be separately reviewed against actual school ownership.

Deleted/replaced homework files are retained in storage; a reviewed orphan-file
cleanup process is future work. File extension/size validation does not scan
attachment contents for malware. Production storage must remain private and
must not expose a public /media route that bypasses the authorized download.
Render attachment durability needs verification against the actual storage
configuration before a pilot.

SQLite tests verify application authorization and workflow behavior. PostgreSQL
row-lock concurrency still needs an isolated PostgreSQL integration test.
No production connection is used to verify it here. The fresh checkout's missing
staticfiles warning remains; deployment asset collection was not executed.

Student homework access, schedules, notices, and broader MVP modules remain
separate milestones; this review does not certify the whole system for a pilot.

## Final suite result

`python manage.py test --settings=config.settings_academic_test`:
**110 tests passed in 46.458 seconds**, with no Django system-check issues.
Runtime assertions confirmed a single in-memory SQLite connection and no routers.

Teacher sidebar links were then restored to secured entry points, malformed
nested navigation spans corrected, and viewport/style blocks added. The focused
25-test workflow suite is rerun after that navigation-only polish.

Changed implementation files: core/views.py, core/models.py,
core/teacher_forms.py, config/urls.py, and teacher templates for the base,
dashboard, classes, homework, subject attendance and daily attendance. Test
changes include the shared fixture, consolidated grading tests, retained
original roster tests, and the new attendance/homework suite.
Focused verification after navigation polish: **25 tests passed in 3.034 seconds**.
