# Administration constraint and migration review

Inspected source/migrations before implementation at parent 670a63a.
No production connection is used for this review.

- SchoolMembership: unique (school,user); role and active status exist. There is
  no password-change-required field. User privilege flags are global.
- StudentProfile: unique (school,registration_number); linked user is one-to-one;
  save() allocates the school/year counter, creates an unusable-password user,
  fixes the profile role, creates membership, and auto-enrolls in the current term.
  Existing student school and user reassignment is rejected by model validation.
- StudentEnrollment: unique (student,academic_year,term). Class and status exist,
  but there is no placement-event history. Grades do not contain class IDs, and
  DailyClassAttendance has no term ID/date-range model.
- Term: unique (name,academic_year), with one current term per school enforced
  by a conditional unique constraint. AcademicYear has unique (school,name),
  but no unique current-year constraint.
- ClassStream has globally unique generated code, no unique school/name index;
  Subject has unique school/name and globally unique generated code. Existing
  scoped forms also reject case-insensitive duplicates. ClassSubject is unique
  by school/year/class/subject. TeacherAssignment lacks a matching DB unique key.

Implementation decision: no models or migrations are changed. Setup email links
use Django password tokens; the first password must be set before login because
new passwords are unusable. No shared or temporary password is displayed.
Operations lock the school row to serialize new administration writes. Those
locks require a later isolated PostgreSQL concurrency check.

Class changes within an enrollment are permitted only before academic records
exist; otherwise the existing row is preserved and the request rejected. New
terms/years create new enrollments and never delete previous ones. Outgoing
transfers mark enrollment Transferred and revoke current student membership;
student records are never moved between tenants. Receiving-school onboarding is
separate. Full mid-term placement history and coordinated inter-school transfer
would need an explicitly reviewed model/migration design.

Changing subject maxima or required curriculum after results exist may change
academic meaning. Administration edits block those changes once relevant grades
exist. No delete workflow is added for academic history or user accounts.
