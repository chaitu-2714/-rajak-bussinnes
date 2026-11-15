# BizPilot AI — Phase 9 Development Report

**Project:** BizPilot AI — AI-Powered Business Automation Desktop Application
**Phase:** 9 of 10 — Enterprise Security, AI Governance, Access Control, Audit and Compliance
**Version:** 9.0.0
**Date:** 04 November 2026
**Status legend:** ✅ Implemented and verified · 🟡 Implemented, not fully verified · ⛔ Pending

---

## 1. Initial security assessment

The audit inspected authentication, session management, RBAC, service-layer
permissions, business isolation, secret storage, AI routing, agent tools, workflow
permissions, approvals, document access, vector isolation, audit logging, backups,
file uploads, exports and packaging.

**What was already sound (verified by reading the code and by tests):**

* Argon2id with OWASP-aligned parameters (64 MiB, t=3, p=4); no fast digests.
* Session tokens stored only as SHA-256 hashes, with absolute expiry, idle timeout,
  revocation and purge.
* Service-layer permission checks (`BaseService._authorize`) on every module.
* Secrets in the OS credential store via `keyring`, never in source or the database.
* Audit sanitisation strips password/token fields before they are written.
* Phase 6 autonomy policies are default-deny; Phase 8 cloud sharing is opt-in.

## 2. Findings and severity

| # | Finding | Severity | Component | Evidence | Impact | Correction |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | No multi-factor authentication | HIGH | `auth_service` | No TOTP anywhere in Phases 1–8 | A stolen password gave full access | TOTP + recovery codes + enforcement (✅ §6) |
| F2 | Audit log had no tamper evidence | HIGH | `audit_service` | Rows could be updated by anything with DB access; no chain | Silent history edits | Hash chain + verification + export (✅ §12) |
| F3 | Approvals not bound to the action payload | HIGH | `approvals.py` | `action_details` stored but never re-checked at execution | An approved 10-unit order could execute as 1000 | Canonical payload hash, re-checked before execution (✅ §9) |
| F4 | Agent tools checked only against the user's permissions | MEDIUM | `agent_management_service` | No per-agent allowlist, depth or duration limit | An agent could reach any tool its *user* could | Per-agent policy enforced in the tool runner (✅ §8) |
| F5 | No data classification before cloud AI | MEDIUM | `hybrid_ai_router` | Cloud gated only by a global toggle | Confidential text could reach Gemini once enabled | Classification + policy matrix + hard block on RESTRICTED (✅ §11) |
| F6 | Upload validation trusted the file extension | MEDIUM | `document_parser` | `SUPPORTED_EXTENSIONS` only | A renamed executable reached the parser | Magic-byte check, safe names, path containment (✅ §16) |
| F7 | Business isolation was architectural, not enforced per query | MEDIUM | all services | Single-business design; services do not filter by `business_id` | Multi-tenant future would leak | `AuthorizationService` denies cross-business; knowledge enforces it (🟡 §7) |
| F8 | Backups had no integrity record | LOW | `backup_service` | Restore existed; validation and history did not | Restoring a corrupt file | Validation before recording/restoring + history (✅ §17) |
| F9 | No security monitoring | MEDIUM | — | Nothing turned failures into reviewable events | Slow detection | Detectors over audit/session data (✅ §15) |
| F10 | Self-approval exception for single-user installs | MEDIUM | `approvals.py` | Sole-approver path | One user could approve their own spend | Refused whenever a second approver exists; exception recorded (🟡 §10) |

## 3. Files created

**Security core** `app/security/authz/authorization_service.py` ·
`app/security/mfa/mfa_service.py` · `app/security/data_protection/secret_manager.py`
· `app/security/file_security.py`

**Governance** `app/security/governance/ai_agent_security.py` ·
`ai_data_governance.py` · `approval_governance.py`

**Audit / monitoring / backup** `app/security/audit/audit_integrity.py` ·
`app/security/monitoring/security_monitor.py` · `app/security/backup/secure_backup.py`

**Data** `app/database/models/security.py` ·
`migrations/versions/0009_security_tables.py`

**Service / UI** `app/services/security_service.py` ·
`app/ui/pages/security_center.py`

**Tests** `tests/security/test_phase9_security.py` ·
`tests/security/test_phase9_governance.py` · `tests/ui/test_security_center.py` ·
`tests/helpers_phase9.py`

## 4. Files modified

`app/core/constants.py` (6 permissions, `MODULE_SECURITY`, 18 audit actions) ·
`app/core/application.py` (security layer + enforcement hooks + startup seeding) ·
`app/services/audit_service.py` (hash chain on every append) ·
`app/services/agent_management_service.py` (per-agent tool enforcement) ·
`app/ai/providers/hybrid_ai_router.py` (governance gate before cloud calls) ·
`app/ai/autonomy/approvals.py` (payload binding) ·
`app/ui/navigation.py`, `main_window.py`, `pages/__init__.py` (Security Center) ·
tests asserting schema version · `README.md`.

## 5. Database migration

`0009_security` (`down_revision = 0008_knowledge`) adds eleven tables; no earlier
table was altered or dropped.

| Table | Purpose |
| --- | --- |
| `security_events` | reviewable indicators with severity, evidence and status |
| `security_policies` | configurable security settings |
| `user_mfa_settings` | TOTP state with the secret stored encrypted |
| `mfa_recovery_codes` | single-use codes, hashes only |
| `session_security_records` | MFA/session events |
| `agent_security_policies` | per-agent tools, data, scope, limits, cloud eligibility |
| `ai_data_governance_policies` | classification × provider matrix |
| `resource_access_policies` | per-resource or per-type rules |
| `audit_integrity_records` | the hash chain |
| `backup_history` | backup and restore attempts with validation |
| `security_incident_reviews` | human review decisions |

Verified: upgrade from a **Phase 8 database with data** kept its rows and created
all eleven tables; `compare_metadata` reports **no drift**.

## 6. Authentication changes

* TOTP enrolment returns a secret, a provisioning URI, a QR PNG and eight
  single-use recovery codes (stored as SHA-256 hashes only).
* Secrets are encrypted with Fernet using a key in `secrets/app.key` (0600).
* Verification accepts a TOTP code or one recovery code; reuse is refused.
* Administrators can enforce MFA per user (`enforce_mfa`), and the roster shows
  who has it enabled or enforced.
* Every MFA action is audited.

Verified: enrolment → verify → status → recovery-code use → reuse refused → wrong
code refused; the stored secret never equals the plaintext.

## 7. Authorization changes

`AuthorizationService.authorize(actor, permission, …)` returns a decision with a
reason. Order of checks: authenticated actor → agents barred from administrative
permissions → business isolation (absolute, superuser included) → **permission must
be registered** (unknown names denied) → permission held → resource policy →
classification (RESTRICTED limited to administrators). Convenience checks cover
documents, agent tools, workflow actions and approval authority. Default deny
throughout.

Verified: unknown permission denied; no-actor denied; cross-business denied for a
superuser; restricted resource denied to a non-administrator.

## 8. AI governance implementation

`AIAgentSecurityPolicyService` seeds a policy per agent (finance = HIGH risk,
others MEDIUM) and enforces: enabled state, tool allowlist, administrative-
permission bar, data categories, execution depth, task count, duration and cloud
eligibility. The tool runner calls it before every tool execution, so an agent
cannot reach a tool outside its policy even if its user could.

Verified: unlisted tool refused with a reason; administrative permission refused;
depth/task/duration limits enforced; disabled agent cannot run; agents refused
cloud eligibility.

## 9. Approval security implementation

`ApprovalGovernanceService` canonicalises the material fields (amount, supplier,
product, quantity, unit cost, items, dates, action name), hashes them, and the
approval stores that hash. Before execution the hash is recomputed from the stored
payload; a mismatch raises and is audited as `APPROVAL_PAYLOAD_MISMATCH`.

Verified: an approval whose amount was changed after approval is refused with "the
action details changed after approval"; agents and system identities cannot
approve; expired and already-decided requests cannot authorise; self-approval is
refused whenever a second eligible approver exists.

## 10. Secret management implementation

* API keys remain in the OS credential store (`keyring`), never in the database or
  source.
* Application-managed secrets (TOTP) are Fernet-encrypted with a key file kept
  outside the database, owner-read/write only.
* `SecretManager.redact()` strips API-key shapes, tokens and `password: …`
  patterns; the router redacts before any cloud call; logs are checked by a test
  that asserts a fake key never appears.

Verified: encrypt/decrypt round-trip, ciphertext differs from plaintext, key file
permissions are 0600, redaction removes key-shaped strings.

## 11. Data protection implementation

Classification (PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED) by signal patterns;
policy matrix per provider; RESTRICTED can never be allowed to a cloud provider
(the update is rejected); CONFIDENTIAL is blocked by default and redacted when
permitted; local providers always allowed. File uploads are validated by signature,
safe name and path containment.

## 12. Audit integrity implementation

Every audit append writes an `audit_integrity_records` row chained by SHA-256 over
the record's own fields plus the previous hash. `verify_chain()` walks the chain
and reports the first broken sequence. `backfill()` chains pre-Phase-9 rows. The
service exposes no update or delete path, and `guard_audit_write` refuses anything
but INSERT/APPEND.

Verified: chain intact after normal operation; editing an audit row makes
verification fail and name the sequence; export writes the CSV plus a chain-head
manifest.

## 13. Security monitoring implementation

Detectors run over real records: repeated failed logins (≥5/hour), repeated access
denials, export bursts, access-control changes and long-running sessions. Events
carry type, severity, user, resource, evidence, recommended response and status,
and are explicitly worded as indicators. Review decisions are recorded.

Verified: six failed logins produce a `REPEATED_FAILED_LOGINS` event with count
evidence and status OPEN; acknowledging it moves it to ACKNOWLEDGED.

## 14. Backup and recovery implementation

`SecureBackupService` wraps the Phase 1 SQLite backup: it creates the backup, opens
it read-only, runs `PRAGMA integrity_check`, counts tables and users, hashes the
file and records the result. Restore requires explicit confirmation, re-validates,
takes a safety copy of the live database first, and records both outcomes.

Verified: a fresh backup is VERIFIED; a corrupt file is rejected; restore without
confirmation raises `PermissionError`; restore of an invalid file raises before
touching the live database.

## 15. Security test results

```
tests/unit                          199 passed
tests/security                      150 passed (38 new Phase 9 tests)
tests/integration                   278 passed
tests/ui                             80 passed (6 new)
-----------------------------------------------------
total                               707 passed
```

Required coverage: unauthorized finance access ✅ · cross-business access ✅ ·
restricted agent tools ✅ · agents cannot change their own permissions ✅ ·
workflow cannot bypass autonomy ✅ · self-approval refused ✅ · expired approval ✅ ·
changed payload invalidates approval ✅ · restricted data never to cloud ✅ ·
cloud disabled ✅ · no API keys in logs ✅ · RAG cannot retrieve restricted docs ✅ ·
injection cannot execute tools ✅ · path traversal rejected ✅ · unauthorized export ✅ ·
users cannot modify audit history ✅ · hash chain detects tampering ✅ ·
backup validated before restore ✅ · sessions expire and revoke ✅ ·
security events recorded ✅.

## 16. Remaining vulnerabilities

| Item | Severity | Why it remains |
| --- | --- | --- |
| Database is not encrypted at rest | MEDIUM | Standard SQLite has no built-in encryption; needs an encrypted volume or SQLCipher build |
| Encryption key beside the database | MEDIUM | Convenience for a desktop app; a compromised filesystem defeats it |
| Hash chain can be recomputed by a DB administrator | MEDIUM | Detects edits, does not prevent a full rewrite; mitigated by exporting the head |
| Single-user self-approval exception | MEDIUM | Keeps a one-person install usable; refused as soon as a second approver exists |
| Business isolation not enforced in every legacy query | MEDIUM | Single-business design; the authorization layer blocks cross-business access, but old services do not filter by `business_id` |
| No OS-level process isolation | LOW | A desktop app running as the user inherits their file access |

## 17. Known limitations

1. MFA is TOTP only; no WebAuthn/hardware keys.
2. No session concurrency limit (the policy hook exists, the limit does not).
3. Security monitoring is threshold-based over audit records, not anomaly
   detection over traffic; it cannot see activity that was never audited.
4. Approval multi-stage plans are defined (`multi_stage_plan`) but the Phase 6
   flow still executes single-stage approvals.
5. Backup covers the database and optionally knowledge files; the vector index is
   rebuilt rather than backed up.

## 18. Recommended deployment hardening

1. Store the database and `secrets/` on an OS-encrypted volume (BitLocker/LUKS).
2. Back up `secrets/app.key` separately from the database; without it, MFA
   enrolments cannot be decrypted.
3. Enforce MFA for every Super Admin and Business Admin account.
4. Export the audit chain head to write-once or off-machine storage on a schedule.
5. Run the app under a dedicated Windows account with no administrator rights.
6. Restrict the data directory with NTFS ACLs to that account.
7. Keep `backup.restore` permission to a single administrator.
8. Review open security events weekly.

## 19. Commands

```bash
# application
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py

# security suites
python -m pytest tests/security -v
python -m pytest tests/security/test_phase9_security.py tests/security/test_phase9_governance.py -v

# everything (batches, because a full run exceeds 5 minutes)
python -m pytest tests/unit
python -m pytest tests/security
python -m pytest tests/integration
python -m pytest tests/ui
```

---

## 20. Phase 9 completion checklist

| Criterion | Status |
| --- | --- |
| Authentication security verified | ✅ |
| MFA works where enabled | ✅ (TOTP + recovery codes) |
| RBAC at service level | ✅ (pre-existing, re-verified) |
| Contextual authorization | ✅ |
| Business isolation verified | 🟡 enforced at the authorization layer; legacy queries not re-filtered |
| AI agent permissions enforced | ✅ |
| Workflow execution permissions enforced | ✅ (autonomy policy + restricted actions) |
| Approval separation of duties | ✅ (with the documented single-user exception) |
| AI data governance | ✅ |
| Restricted information blocked from cloud AI | ✅ |
| Secrets stored securely | ✅ (keyring + encrypted key file) |
| Audit history protected | ✅ (append-only + hash chain) |
| Security monitoring | ✅ |
| Document security | ✅ (signature, names, containment) |
| Backup and recovery verified | ✅ |
| Security dashboard | ✅ |
| Security tests pass | ✅ 707 total, 44 new |
| Known vulnerabilities documented | ✅ §16 |
