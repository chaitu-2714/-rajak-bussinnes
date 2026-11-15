# BizPilot AI — Security Guide

## Authentication

* Passwords: Argon2id, 64 MiB, 3 iterations, 4 lanes. No other algorithm exists in the code.
* Sessions: random tokens stored only as SHA-256 hashes, with absolute expiry, idle
  timeout, revocation and purge of expired rows.
* Lockout: repeated failures lock the account for a period; unlock is audited.
* MFA: TOTP (SHA-1, 6 digits, 30 s) with eight single-use recovery codes stored as
  hashes. The TOTP secret is Fernet-encrypted with a key in `secrets/app.key` (0600).

## Authorization

One `AuthorizationService` decides access. Order: authenticated actor → agents barred from
administrative permissions → business isolation (absolute) → permission must be registered
→ permission held → resource policy → classification. Unknown permissions are denied.

## AI permissions

Each agent has a policy: enabled state, allowed tools, data categories, execution depth,
task count, duration, cloud eligibility. The tool runner enforces it before every call.
Agents can never hold administrative permissions, approve actions, or change policies.

## Data protection

| Classification | Example | Cloud (Gemini) |
| --- | --- | --- |
| PUBLIC | shop description | allowed |
| INTERNAL | ordinary reports | allowed with opt-in and redaction |
| CONFIDENTIAL | invoices, contracts, customer data | blocked by default; redacted if enabled |
| RESTRICTED | keys, tokens, credentials | **never** |

## Secrets

API keys live in the OS credential store (Windows Credential Manager via `keyring`).
Application secrets are Fernet-encrypted with a key file kept outside the database.
Nothing secret is written to logs; a test asserts a fake key never appears in them.

## Audit

Every audit record is appended to a SHA-256 hash chain (`audit_integrity_records`).
**Security Center → Audit Trail → Verify chain** reports the first broken sequence.
Export includes the chain head so the record can be checked off-machine.

**Limitation:** the chain detects modification but cannot prevent an administrator who
rewrites the whole database from recomputing it. Export to write-once storage for real
tamper resistance.

## File handling

Uploads are validated by magic bytes, not extension; dangerous types are refused; names
are sanitised and every path is confined to the documents directory. Document text is
treated as untrusted data: instructions inside a file are detected and reported, never
executed.

## Backups

Backups are integrity-checked (SQLite `PRAGMA integrity_check`, table and user counts)
before being recorded. Restores require confirmation, re-validate, and take a safety copy
first. Back up `secrets/app.key` separately.

## Known limitations

1. SQLite is not encrypted at rest — use an OS-encrypted volume if required.
2. The encryption key sits beside the database; a compromised filesystem defeats it.
3. Single-user workspaces can approve their own spend when no second approver exists;
   the exception is recorded on the approval and disappears once a second approver exists.
4. Security monitoring is threshold-based over audit records; it cannot see unaudited activity.
5. This is not a compliance certification. Passing the test suite is not GDPR, DPDP or
   ISO 27001 compliance.

## Deployment hardening

1. Install on an encrypted volume.
2. Enforce MFA for every administrator.
3. Export the audit chain head on a schedule.
4. Run under a standard Windows account, not an administrator.
5. Restrict the data directory with NTFS permissions.
6. Keep `backup.restore` to a single administrator.
7. Review open security events weekly.
