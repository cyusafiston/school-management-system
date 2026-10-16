# PostgreSQL preservation and portability plan

Planning date: 16 October 2026. The user reports that the current free Render
PostgreSQL expires on **11 November 2026**; this account-specific date has not
been independently checked. No production account, data or credentials were
accessed. No backup, restore, provider creation or hosting change was performed.
A source recovery ZIP is not a database backup. Existing database backups remain
**unverified** until an actual restore and reconciliation succeed.

## Deadline and ownership

Aim for the first approved, encrypted backup and successful isolated restore by
**28 October 2026**, with **4 November 2026 (Africa/Kigali)** as the latest safe
completion deadline, seven days before the reported expiry. Record an owner and
an earlier exact time in the operational calendar. Do not depend on a grace
period. If development is not complete by then, preserve the database anyway;
that does not require migrating hosting. After approval, refresh backups daily
until the hosting decision and before any expiry/cutover; choose a retention and
recovery-point objective with the owner. Backups after the last snapshot contain
new transactions and require refreshed restore/reconciliation evidence.

## Procedure for a separately approved operator

These are instructions for later execution, not authorization to connect now.

1. Obtain explicit approval for source read access, handling personal and
   financial records, encrypted backup locations, and an isolated restore
   destination. Verify the actual expiry in the provider dashboard. Inventory
   PostgreSQL/server versions, database size, extensions, collation/encoding,
   application commit, applied migration identifiers, roles/permissions,
   connection limits and external media. Never print connection URLs or secrets.
2. Use trusted PostgreSQL clients compatible with the source major version
   (prefer the same major; pg_dump cannot dump a newer server than itself).
   Prefer the same destination major initially; downgrade is not assumed safe.
   Use a direct TLS endpoint for dump/restore, not a transaction pooler. Require
   certificate/hostname verification where supported; validate provider CA and
   network access. Grant the approved backup account only the privileges needed
   for a complete dump. Do not bypass row policies or accept an incomplete dump.
3. In a private operator directory (umask 077), configure libpq service entries
   `sms_backup_source` and `sms_restore_sandbox`, with verified different hosts
   and database identities. Put passwords in a protected passfile (mode 0600) or
   approved secret manager; never in this repo, commands, screenshots or logs.
   Stop if destination identity is ambiguous. Provision an empty isolated
   destination manually under the approved provider account. Restrict network
   access; disable application workers, email, webhooks and public app access.
4. Run a consistent logical dump. Live pg_dump gives a consistent snapshot but
   does not include later writes. Collect a reconciliation baseline from the
   same exported snapshot with an experienced operator, or briefly freeze
   writes for an exact source baseline. Do not claim later source counts match
   an earlier live snapshot. Review exit status and warnings, not just filesize.

   ```sh
   umask 077
   pg_dump --dbname='service=sms_backup_source' --format=custom --file=sms-backup.dump
   pg_restore --list sms-backup.dump > archive-contents.txt
   sha256sum sms-backup.dump > sms-backup.dump.sha256
   ```

   The list and checksum are archive checks, not proof of restorability. Encrypt
   the dump promptly with the approved encryption tool and recipient/key policy;
   retain keys separately. Keep two access-controlled durable copies in separate
   failure domains, including offline/off-provider recovery where practical.
   Decrypt a test copy in the restricted destination for restoration. Do not
   place real backups in the code recovery archive or public GitHub.
5. Record verified source/destination identity privately. Only after confirming
   that the destination is empty and isolated, restore into it:

   ```sh
   pg_restore --exit-on-error --single-transaction --no-owner --no-privileges \
     --dbname='service=sms_restore_sandbox' sms-backup.dump
   ```

   Never point this command at production. Avoid `--clean` and `--create` here.
   Use only a trusted source dump; restoring can execute source-defined code.
   Apply a deliberately mapped least-privilege destination role/ACL policy;
   ownership and grants are intentionally not copied by these options. Inventory
   roles separately without exporting passwords. Extension support must be
   checked before restore. No application migration is part of this procedure.
6. Verify constraints, indexes, sequence state, extensions, applied migrations
   and exact per-table counts against the snapshot baseline. Reconcile each
   school/year/term and each student: assigned obligations, active and voided
   payment counts/sums, references and receipts, expected-minus-paid balances,
   outstanding debt and overpayment credits calculated independently per student.
   Detect duplicate receipts/references, nonpositive/nonfinite payments,
   malformed school/term/year relationships, missing bills and orphaned records.
   Check sampled full payment histories and void actor/reason/timestamp audit
   fields. Preserve discrepancies for review; do not auto-correct source data.
7. Validate a representative restored read-only workflow in a private sandbox
   only with separate approval to use restored personal data. All automated
   Django tests for this milestone remain strictly in-memory SQLite with
   `python manage.py test --settings=config.settings_academic_test`; do not point
   that test command or default Django settings at a real restored database.
   PostgreSQL concurrency validation should later use synthetic data in an
   explicitly approved separate environment.
8. Save evidence: timestamp/timezone, dump/client/server versions, snapshot
   baseline identity, source code commit, checksums, encryption/key custody,
   destination identity, successful restore log, reconciliation results,
   reviewer sign-off, and measured recovery duration. Redact credentials and
   personal records from general development reports. Test access to both backup
   copies and decryption keys. Restore is verified only when these checks pass.
   Keep ongoing backups and periodic restore rehearsals; one successful dump is
   not a long-term backup service.

Database dumps do not include uploaded homework/media. Preserve private media
separately with matching paths/permissions and a corresponding timestamp. Save
nonsecret configuration inventory and recovery instructions separately from
secret-manager exports. Ensure the recovery code version matches migration state.

## Free PostgreSQL options (official information checked 16 October 2026)

| Provider | Relevant free limits | Operational fit and limits |
| --- | --- | --- |
| Neon | 100 projects; 1 GB PostgreSQL storage/project (20 GB total); 100 CU-hours/project/month; 5 GB public transfer/project/month; 10 branches/project; sleeps after 5 idle minutes; up to 2 CU. Restore history up to 6 hours, capped at 1 GB of changes. | Preferred candidate for a small development/MVP database if measured storage, compute, latency and connection requirements fit. Short restore history is insufficient as the sole backup. Sleeping can delay the first request. Quotas can suspend service; confirm current behavior, region availability and connection limits before selecting. |
| Supabase | 500 MB database/project; 2 active free projects; shared CPU/500 MB RAM; 5 GB egress; projects pause after a week of inactivity. | Suitable small PostgreSQL candidate. Daily managed backup availability begins on paid plans; free users should export their own backups. Extra Auth/Storage services are optional and do not require rewriting Django authentication. Verify direct IPv4/IPv6 connectivity and pooler semantics from Render before choosing. |
| Render free PostgreSQL | Expires 30 days after creation; no provider-created logical backups on Free. | Unsuitable for preserving this database indefinitely. Keeping current hosting during development is fine only with a verified external backup and a timely approved decision before expiry. An application host and database host can be chosen independently. |

Limits change. Recheck official plan tables immediately before provisioning;
older Neon blog posts show different quotas. Free plans are capacity constraints,
not a guarantee of production availability or a disaster-recovery policy.
No recommendation assumes that the current uninspected database fits a free tier.

## Later migration sequence and rollback

1. Finish functional milestones while preserving source checkpoints; obtain
   backup approval early enough to meet the deadline above. Measure the actual
   source rather than guessing. Present provider, region, privacy/data residency,
   backup cost, connection budget and restoration evidence for user approval.
2. Rehearse on an empty approved destination. Compare extension/version support,
   TLS, role mapping, timezones, Decimal precision, sequence values and Django
   transactions. If a pooler is selected for runtime, explicitly test its mode
   and Django connection/server-side-cursor behavior with synthetic data first.
3. Agree a maintenance window and rollback point. Freeze writes to the old app
   and workers, take the final snapshot, restore/reconcile, then update secrets
   through the approved secret manager. Do not edit or commit credentials.
   No schema migration is necessary merely to change PostgreSQL providers.
4. With explicit deployment/cutover approval, switch the app connection, verify
   school-isolated financial and academic workflows, and resume writes only
   after reconciliation. Keep the old source read-only where the provider allows
   and retain encrypted external snapshots independently of its expiration.
5. Before any new-destination writes, rollback can reconnect to the frozen source
   if still available. After writes occur, simple rollback loses new payments;
   stop writes, back up the new destination and reconcile/replay approved changes
   before rollback. Never run both as writable masters. Do not delete the old
   database or backups without approval and an agreed retention period.

## Primary references

- https://www.postgresql.org/docs/current/app-pgdump.html
- https://www.postgresql.org/docs/current/app-pgrestore.html
- https://www.postgresql.org/docs/current/libpq-pgservice.html
- https://www.postgresql.org/docs/current/libpq-pgpass.html
- https://neon.com/faqs/free-plan-limits-and-quotas
- https://neon.com/docs/introduction/plans
- https://neon.com/pricing
- https://supabase.com/pricing
- https://supabase.com/docs/guides/platform/backups
- https://render.com/docs/free
- https://render.com/docs/postgresql-backups
