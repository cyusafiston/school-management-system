# Student academic portal milestone

Parent checkpoint: 520862bc7346f7665f60c97f944d3945160992da.
Branch: development/teacher-module-verification. Teacher work is retained.

## Implemented behavior

- Shared student context requires an authenticated active account, an active
  student membership in exactly one approved school, a matching linked profile,
  and an active enrollment in that school's current term. Invalid related
  school/year/class relationships fail closed. Posted or queried identity IDs
  never determine the signed-in student's identity.
- Login redirects student members to their secured dashboard. The existing
  school landing page links to it. Other role redirects are unchanged.
- Dashboard and profile use enrollment context, not the profile's mutable
  current-class pointer. Dashboard, notices, profile and password pages reject
  attempts to switch to a historical enrollment.
- Subjects come from school/year/class curriculum. Grades expose only the
  student's finalized results in enrolled curriculum subjects. Historical grade
  terms require an Active or Completed enrollment while current access remains
  active. No student ID URL or edit API exposes another student's profile/grades.
- Existing PDF report rendering and academic rules are reused: Term 1, cumulative
  Term 2, annual Terms 1–3; required results gate overall averages, unassessed
  optional subjects do not, and unconfigured results block certification.
  Reports resolve the academic year through the current enrollment and require
  the student's authorized reporting enrollments. Report attendance is restricted
  to the student's class and term for each reporting period.
- Personal subject and daily attendance histories exclude other students and
  foreign school/assignment relationships. Month/year inputs are validated.
- Homework listings/downloads require the authorized class, term and curriculum.
  Teacher-only download permissions were not widened. Student downloads use a
  separate authorized route with attachment, nosniff and private/no-store headers.
- Notices include only unexpired school-wide or current-class items from the
  student's school. Schedule displays actual enrolled subject/teacher allocations.
- Profile is read-only. Password change uses Django's PasswordChangeForm, old
  password checks, configured validators, CSRF and session hash refresh.
- Academic pages accept GET only; password change is the sole new mutation.
  Authentication form errors are no longer printed to application stdout.

## Template decisions

The legacy student dashboard/base referenced unavailable finance/password routes
and mixed draft and unrelated academic data. Student templates now use a shared
responsive blue/white layout with supported navigation and clear empty states.
The existing PDF layout and academic engine are retained. CAT/exam columns show
recorded raw marks instead of ratios against mutable subject maxima; totals and
percentages use stored finalized values. All models/migrations are unchanged.
No new individual subject-selection or timetable model is invented.

## Testing and review

49 new isolated tests cover real student login, rejected authentication, all
student page routes, inactive accounts/memberships, suspended schools, global
profile-role mismatches, ambiguous school contexts, missing and malformed
current enrollments, cross-student/school identity and term overrides, read-only
methods, password/session handling, notices, schedules, homework downloads,
attendance isolation and the complete teacher-to-student publication workflow.

Academic checks include real parseable PDF output, own identity/content, finalized
visibility, grade thresholds, multiple-subject averages, required/optional and
unconfigured subject handling, cumulative/annual reports and reporting-enrollment
requirements. Test attachments use temporary storage and are removed afterwards.

The first focused run exposed a fixture missing the required attendance recorder;
the fixture was corrected. The next focused run passed 42 tests before six extra
boundary tests were added. Final complete-suite evidence is recorded below.

Use only:

```sh
python manage.py test --settings=config.settings_academic_test
```

Runtime assertions verified only in-memory SQLite and no database routers.
Settings, dependencies, deployment scripts, migrations and production records
are unchanged. No push, merge, deployment or production commands were executed.

## Remaining scope and pilot risks

- There are no lesson day/time/room fields. Schedule truthfully shows subject
  allocations; a timed timetable requires a separately reviewed model/workflow.
- Reports retain the existing current-academic-year scope. Historical grades
  are available through authorized enrollments; older-year PDFs are future work.
- Daily attendance has no term foreign key or term date ranges; its history is
  scoped by student, school and enrolled classes. Do not infer term-specific daily
  statistics from it. Report attendance continues to use subject sessions.
- Finalized totals and percentages use stored grade values. Historical separate
  CAT/exam maxima are not snapshotted by the existing model; the PDF therefore
  shows raw CAT/exam scores rather than potentially misleading ratios.
- Newly generated accounts still need the existing administrator password or
  reset provisioning process. This milestone does not issue default passwords.
- Private durable media storage, orphan-file cleanup and isolated PostgreSQL
  concurrency verification remain prerequisites before real-school use.
- The fresh checkout warns about absent staticfiles; the PDF renderer reports an
  unsupported border-spacing style. Tests verify PDF bytes and extracted content,
  not a full browser/visual regression audit. No deployment assets were built.

## Next recommended milestone (not started)

Complete school administration workflows: safe student account provisioning and
credential reset, enrollment/promotion/transfers, school academic setup integrity,
role/membership lifecycle, and notices management. Include an administrator →
teacher → student two-school regression flow. Then verify finance integrity,
platform onboarding, and pilot infrastructure readiness. Teacher notices/schedule
and remaining account navigation should be closed within those shared workflows.

## Final verification

`python manage.py test --settings=config.settings_academic_test`:
**160 tests passed in 54.063 seconds**, with no Django system-check issues.
This includes all 111 previously passing tests and 49 student portal tests.
The final additional test verifies finalized report totals/percentages remain
unchanged when a subject's current CAT/exam maxima are edited. Python compilation
and Git whitespace checks passed.
