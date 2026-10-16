# Controlled-pilot operations — opt-in, not deployed

This milestone does not change `config/settings.py`, WSGI/ASGI defaults, Render
configuration, environment variables or production. Approval for development is
not approval to activate `config.settings_pilot`, provision storage or databases,
send real account emails, or deploy. All evidence here uses synthetic accounts.

## Activation gates and required decisions

| Area | Implemented and locally checked | Still requires approval/evidence |
| --- | --- | --- |
| Platform onboarding | Pending application, initial administrator without global privileges, operator-only reviewed transitions, validated lifecycle actions and review audit, first-school checklist | Operator identity/email verification and administrator recovery policy; review account-level MFA/external rate limits before internet pilot |
| Private media | No public storage URLs; authenticated teacher/student downloads; opaque school-prefixed names; private filesystem permissions; traversal/symlink guards; persistence across storage instances | Choose and approve a durable mount or alternative backend, quota/encryption, file retention/scanning policy, off-volume backup and restart/restore test. Workspace temp-file tests do not prove hosting durability. |
| Account email | Canonical HTTPS links; standard SMTP/TLS configuration; real loopback SMTP transport plus mocked TLS/authentication behavior; disabled token-printing backends; generic failure logs | Approved SMTP service/sender, credentials in secret manager, live delivery and bounce test, SPF/DKIM/DMARC and ownership verification. No message has been sent to a real recipient. |
| Audit/monitoring | Transactional existing Django admin log records and allowlisted operational JSON logs; request IDs, status/duration, no raw reset URLs or request bodies | Approve restricted durable log sink, retention, alert recipients and on-call procedure; external delivery/alerts are unverified. DB audit rows are not tamper-proof against platform DB administrators. |
| Database | Loopback-only synthetic PostgreSQL test settings and race tests; complete SQLite regression suite | PostgreSQL binaries/service unavailable here; run harness on an approved local/non-production server. No PostgreSQL race result or real backup restore is claimed. |
| Deployment | Separate strict pilot profile, exact-host HTTPS/SMTP/private-media checks and rollback instructions | TLS/proxy trust, static collection, actual mounted storage, resource/load limits, browser verification, approved deployment and independent restore evidence |

No migration files or database field definitions are introduced. Audit history
reuses `django_admin_log`; do not purge it as ordinary admin UI history. User
foreign keys on existing log records cascade on account deletion; deactivate
accounts for the pilot and approve a future immutable audit retention design.
Anonymous registration events use the newly created administrator as their actor;
this records application identity, not verified ownership. Other ORM events need
the opt-in AuditMiddleware; scripts must explicitly set a trusted audit actor or
call the audit service. Direct SQL and bulk updates bypass ORM audit signals.

The signup administrator chooses a validated, hashed password; approval also
requests a single-use setup/recovery email. No temporary credentials are displayed.
Approval requires an active administrator created by this application, a unique
nonempty account email and no global staff/superuser privileges. Email uniqueness
is checked in forms/services, not guaranteed by a new DB constraint; concurrent
email collisions fail closed for recovery and require operator review.
Rejected applications are final in the current workflow; an operator should
review a corrected new application rather than silently reopening one. Reactivation
applies only to suspended schools and does not reactivate disabled memberships.

## Pilot profile preparation (no connection required)

Use a separate reviewed secret-manager environment. Never copy live secrets into
source, command history, screenshots, logs or the recovery ZIP. Required names:

- `DJANGO_SECRET_KEY`: dedicated random secret, at least 50 characters.
- `DEBUG=False`, exact `ALLOWED_HOSTS` (no wildcards), and
  `ACCOUNT_PUBLIC_ORIGIN=https://<approved-host>`; links ignore the incoming Host.
- Approved PostgreSQL `DATABASE_URL` with `sslmode=verify-full`, compatible client
  trust roots/certificates and correct role permissions. No SQLite fallback exists
  in the pilot validator. Database credentials are not printed on validation error.
- `PILOT_PRIVATE_MEDIA_ROOT`: dedicated absolute persistent mount path outside
  public/static/repository directories. `PILOT_DURABLE_MEDIA_CONFIRMED=yes` is an
  operator acknowledgment, not automatic proof of durability. Protect mount root
  mode 0700, files 0600; do not expose via webserver/media routes or CDN. Existing
  document names continue to work when their bytes are copied to the private
  root; there is no automatic production media move in this milestone.
- SMTP `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
  `DEFAULT_FROM_EMAIL`; choose exactly one of `EMAIL_USE_TLS=True` or
  `EMAIL_USE_SSL=True`. Pilot always uses the SMTP backend with a timeout.

Validate using `config.pilot.validate_environment()` in a controlled process;
it only inspects supplied values, never connects. Tests cover missing/insecure
values. `config.settings_pilot` is ready for review but is not activated anywhere.
Before approved release, run Django deployment checks against the reviewed pilot
profile and collect static assets in a staging directory with non-production
secrets. Test HTTPS redirects, cookies, CSRF, proxy header stripping, exact host
rejection and HSTS on that actual proxy. HSTS deliberately starts at one hour,
without subdomains or preload. Raising it is a later operator decision.

AuditMiddleware should wrap TenantWriteGuardMiddleware after authentication.
For authenticated tenant mutations, the guard takes the school row lock and
rechecks membership/status before running the view; platform lifecycle transitions
use the same row lock. A write already holding the lock completes before suspension
is committed; subsequent writes fail closed. Existing school services may take the
same lock again in the transaction. Failed HTTP operations roll back. PostgreSQL
must verify this behavior before a concurrent multi-worker pilot. Async/background
jobs need the equivalent explicit lifecycle checks and locking; no jobs are enabled.

Liveness `/health/live/` is public and does not query data. Readiness
`/platform/readiness/` is active-operator-only, checks SELECT 1 and mount-root
accessibility, returns 503 on failure, and reveals no paths/credentials. It is not
an attestation of backup validity, SMTP delivery or physical storage durability.
Use liveness for process restarts. External monitors for private readiness need a
reviewed authentication approach; do not make the endpoint public for convenience.

## PostgreSQL verification on synthetic data

This workspace cannot install/start PostgreSQL because its package manager's
required user/group privilege separation is prohibited. It has no postgres/initdb
or Docker binaries. No escalation, provider provisioning, external PostgreSQL
connection or alternate production settings were used to bypass that limitation.

On an approved local machine, use a dedicated empty PostgreSQL cluster owned by a
non-root OS user, bound only to numeric loopback on port 15432. Create a dedicated
`SMS_TEST_PGUSER` with CREATEDB limited to this disposable cluster; no credentials
or data from another cluster are permitted. Confirm server identity and isolation
before acknowledging the variables below. Prefer password or local peer/scram
authentication; never expose a trust-authenticated cluster to a network.

```sh
export SMS_SYNTHETIC_POSTGRES_ONLY=yes
export SMS_TEST_PGHOST=127.0.0.1
export SMS_TEST_PGPORT=15432
export SMS_TEST_PGUSER=sms_pilot_test
# Supply SMS_TEST_PGPASSWORD through the isolated secret manager if required.
python manage.py test --settings=config.settings_postgres_pilot_test
```

The settings ignore DATABASE_URL, prohibit non-loopback hosts, use only
`sms_pilot_synthetic` / `test_sms_pilot_synthetic`, have finite connection and SQL
lock timeouts, and allow Django to create/drop only the fixed test database.
The acknowledged cluster must contain no other valuable data: the test user has
CREATEDB. The default SQLite command remains:

```sh
python manage.py test --settings=config.settings_academic_test
```

Three PostgreSQL-only tests are explicitly skipped on SQLite: concurrent distinct
payments competing for one balance, concurrent retries of one signed form, and
exact numeric aggregation. The full suite on PostgreSQL also exercises schema
creation and all existing workflows. Do not replace these races with SQLite
threads and claim equivalent row-lock evidence. Preserve output, PostgreSQL and
client versions and exact commit. Any failure blocks concurrency readiness.
A real production dump restore remains a separate approved procedure.

## Release and rollback sequence — execution requires approval

1. Verify the exact source checkpoint, clean tree, dependencies and complete
   tests. Review pinned dependency versions and supported runtime against the
   staging environment; legacy `requirements.txt` remains unpinned. `ops/requirements-pilot.lock`
   captures the exact locally tested package versions without MySQL drivers,
   private URLs or credentials; a fresh staging install and vulnerability review
   remain unverified. Preserve tested-package evidence.
2. Approve storage, mail, monitoring and synthetic PostgreSQL environment.
   Verify private media persistence after restart and from an independent backup;
   test retrieval with teacher/student permissions and after suspension. Do not
   mount scratch workspace files as the production durable store.
3. Approve the database backup operation and restore destination before the
   target deadline: first verified restore **28 October 2026**; latest safe
   fallback deadline **4 November 2026**, ahead of reported **11 November** expiry.
   Use `docs/postgresql-backup-and-portability-plan.md`. Source ZIP verification
   does not satisfy database restore verification. Do not choose a provider yet.
4. Rehearse this code and opt-in profile with synthetic data behind the intended
   proxy. Verify role navigation, account setup, full workflow, static styles,
   mobile/print report cards, private files, TLS, emails and logs. Many inherited
   templates use external CSS CDNs; offline/CSP and asset bundling need review.
5. Present evidence and remaining decisions for explicit pilot deployment
   approval. No deploy/cutover command is part of this document or code startup.
   Never run `migrate` automatically as a release side effect. This milestone
   requires no new schema migration.
6. Preserve the previous source/configuration, approved database/media snapshots
   and exact release artifact before switching. If reverting before new writes,
   restore the former source and reviewed settings. If writes occurred, freeze
   writes, snapshot the current system and reconcile before any DB rollback;
   reconnecting to an old snapshot can lose fee payments and enrollment changes.
   A code rollback must preserve all newly collected data and audit history.
   Disable affected functionality or suspend the school while investigating;
   never delete history or revert financial rows to make a rollback appear clean.

Suggested monitoring decisions: alert on repeated 5xx, unavailable database or
storage, SMTP failures, unexpected membership/role changes, payment/void failures,
backup age and restore-test age. Log only allowlisted route names/status/IDs,
never reset paths, query strings, passwords, cookies, full request or email bodies.
The opt-in profile redacts Django request/security/server records. Configure the
reverse proxy, hosting access logs, SMTP service, APM and error-reporting tools
separately to suppress reset tokens; application filters cannot control them.
External rate limiting and operator MFA remain pilot gates, not verified features.
