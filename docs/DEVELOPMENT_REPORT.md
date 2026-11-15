# BizPilot AI — Phase 1 Development Report

**Project:** BizPilot AI — AI-Powered Business Automation Desktop Application
**Phase:** 1 of 10 — Foundation
**Version:** 1.0.0
**Date:** 03 November 2026
**Status legend:** ✅ Implemented and verified · 🟡 Implemented, partially verified · ⛔ Pending

---

## 1. Executive summary

Phase 1 is built as a working native desktop application: a Python 3.12 /
PySide6 modular monolith with a real SQLite database, Alembic migrations,
Argon2id authentication, service-level RBAC, an append-only audit trail, user
and role management, settings with SQLite-safe backup/restore, and a light
enterprise dashboard shell.

Everything described as implemented below was executed, not merely generated:
the database was migrated and queried, accounts were created and authenticated,
permission checks were exercised through the service layer, and the UI was
constructed and navigated. **114 automated tests were executed and all 114
passed.** The real application was launched and logged a clean startup.

Two deliverables could not be completed in this environment and are reported as
pending rather than claimed: **the Windows .exe** (PyInstaller cannot
cross-compile from Linux, and no Windows toolchain exists here) and **a run on a
real Windows display** (all UI verification used Qt's offscreen platform).

---

## 2. Environment used for verification

| Item | Value |
| --- | --- |
| OS | Debian 12 (bookworm), x86_64 — Linux container |
| Python | 3.12.13 |
| PySide6 | 6.8.3 (PySide6-Essentials; requirements pin full `PySide6==6.8.3`) |
| SQLAlchemy | 2.1.6 |
| Alembic | 1.20.1 |
| Pydantic | 2.14.2 |
| argon2-cffi | 25.1.0 |
| pyqtgraph | 0.14.0 |
| pytest | 9.2.0 (+ pytest-qt 4.5.0) |
| PyInstaller | 6.22.3 (analysis only — see §9) |
| Qt platform | `offscreen` for all automated UI work |

> The target platform is Windows. Every layer except the PyInstaller bundle is
> platform-independent Python/Qt code, and the Windows-specific behaviour
> (`%LOCALAPPDATA%` data directory, `.ico` icon, `console=False` build) is
> implemented and selected by `sys.platform`, but has not been executed on
> Windows in this environment.

---

## 3. Features: implemented, tested, pending

### 3.1 Foundation and architecture

| Feature | Status | Evidence |
| --- | --- | --- |
| Project structure (7 layers) | ✅ | `app/core`, `database`, `schemas`, `services`, `security`, `ui`, `utils` |
| Dependency injection container | ✅ | `app/core/application.py::ApplicationContext.build` |
| Configuration layer with persistent data dir | ✅ | `app/core/config.py`; DB created in `%LOCALAPPDATA%\BizPilotAI` on Windows |
| Centralised exception hierarchy with safe user messages | ✅ | `app/core/exceptions.py`, 15 error types |
| Rotating application logs, separate from audit trail | ✅ | `app/core/logging_config.py`, `logs/application.log` |
| PyInstaller configuration + Windows build script | 🟡 | `deployment/build.spec`, `deployment/build_windows.bat` — spec syntax and bundled paths verified; bundle not produced (§9) |

### 3.2 Database

| Feature | Status | Evidence |
| --- | --- | --- |
| 8 tables with FK/unique constraints | ✅ | `test_all_tables_are_created`, `test_foreign_keys_are_enforced`, `test_unique_email_constraint`, `test_unique_role_assignment_constraint` |
| Alembic migration `0001_initial` | ✅ | `test_schema_version_is_recorded` → `0001_initial` |
| Migration ↔ model drift check | ✅ | `test_migrations_match_models` (alembic `compare_metadata` returns `[]`) |
| Foreign keys, WAL, busy timeout per connection | ✅ | `test_wal_mode_is_enabled`, pragma listener in `app/database/session.py` |
| Explicit transactions with rollback | ✅ | `BaseService.unit_of_work`, `test_transaction_rollback_discards_changes` |
| Persistence across restart | ✅ | `test_database_persists_across_restart` (dispose → reopen → login) |
| Integrity check | ✅ | `test_integrity_check_passes` (`PRAGMA integrity_check` + `foreign_key_check`) |
| Backup via SQLite online backup API | ✅ | `test_backup_and_restore_round_trip`, `test_backup_listing` |
| Restore with validation + safety copy | ✅ | `test_restore_rejects_invalid_file`; safety copy asserted in the round-trip test |
| Idempotent startup migration | ✅ | `test_initialisation_is_idempotent` |

**Tables created**

| Table | Purpose | Key constraints |
| --- | --- | --- |
| `users` | Accounts | unique `email` (index), Argon2id `password_hash`, `failed_login_attempts`, `locked_until`, `last_login_at` |
| `roles` | RBAC roles | unique `role_name`, `is_system_role` |
| `permissions` | Permission catalogue (36 rows) | unique `permission_key`, indexed `module` |
| `user_roles` | User↔role (many-to-many) | unique (`user_id`,`role_id`), FK cascade, `assigned_by` |
| `role_permissions` | Role↔permission | unique (`role_id`,`permission_id`), FK cascade |
| `sessions` | Auth sessions | unique `session_token_hash` (SHA-256 only) |
| `business` | Workspace profile | single profile enforced in the service layer |
| `audit_logs` | Append-only audit trail | FK `user_id` `SET NULL`, JSON `old_values`/`new_values`, indexed `action`, `module`, `created_at` |

### 3.3 Authentication

| Feature | Status | Evidence |
| --- | --- | --- |
| First-launch setup wizard | ✅ | `test_setup_wizard_opens_on_first_launch`, `test_initial_setup_creates_business_admin_and_session` |
| No default/known admin password | ✅ | Password chosen in the wizard; no seeded credential anywhere in the codebase |
| Wizard unreachable after setup | ✅ | `test_setup_cannot_run_twice` (raises `ConflictError`), `test_login_window_opens_after_initialisation` |
| Argon2id hashing (64 MiB, t=3, p=4) | ✅ | `test_hash_uses_argon2id`, `test_password_is_hashed_with_argon2id` |
| Plain SHA-256 rejected | ✅ | `test_plain_sha256_digest_is_not_accepted` |
| Login success / failure / unknown email | ✅ | `test_login_success_records_last_login_and_audit`, `test_login_with_wrong_password_is_generic`, `test_login_with_unknown_email_is_generic` |
| Generic error message (no account enumeration) | ✅ | Same `Invalid email or password.` for both cases; dummy Argon2 verify equalises timing |
| Account lockout | ✅ | `test_account_locks_after_repeated_failures` (5 attempts → 15-minute lock) |
| Inactive account blocked | ✅ | `test_inactive_account_cannot_sign_in` |
| Session tokens random, stored hashed | ✅ | `test_raw_token_is_never_stored`, `test_session_token_is_not_stored_in_plain_text` |
| Session expiry and idle timeout | ✅ | `test_expired_session_is_rejected`, `test_expired_session_invalidates_context` |
| Logout revokes session | ✅ | `test_logout_revokes_the_session`, `test_logout_returns_to_login` |
| Password change (verifies current, revokes other sessions) | ✅ | `test_change_password_invalidates_old_password`, `test_change_password_revokes_other_sessions`, `test_change_password_requires_correct_current_password` |
| Show/hide password, remember email, version display | ✅ | `test_login_window_has_version_and_password_toggle`; remember-email via `QSettings` |
| Login failures audited without secrets | ✅ | `test_login_failure_is_audited_without_secrets`, `test_audit_never_contains_password_material` |

### 3.4 Authorisation (RBAC)

| Feature | Status | Evidence |
| --- | --- | --- |
| Six system roles seeded with documented permission sets | ✅ | `test_setup_creates_six_roles_and_permission_catalogue`; Super Admin 36, Business Admin 21, Finance 9, Sales 10, Inventory 10, Employee 2 |
| `has_permission` / `require_permission` / `get_user_permissions` | ✅ | `app/security/authorization.py`; used by every service |
| Super Admin holds the whole catalogue | ✅ | `test_super_admin_holds_every_permission` |
| Business Admin: users yes, settings no | ✅ | `test_business_admin_can_manage_users_but_not_settings` |
| Finance Manager cannot manage users | ✅ | `test_finance_manager_cannot_manage_users` |
| Sales Manager cannot read audit or create roles | ✅ | `test_sales_manager_cannot_read_audit_or_create_roles` |
| Inventory Manager restrictions | ✅ | `test_inventory_manager_cannot_approve_finance` |
| Employee minimal access | ✅ | `test_employee_has_minimal_access`, `test_employee_cannot_manage_users` |
| Unauthorised service calls rejected (not just hidden UI) | ✅ | `test_unauthorised_page_cannot_be_opened`, `test_employee_cannot_manage_users` |
| Permission changes take effect immediately | ✅ | `test_permission_change_takes_effect_immediately` |
| Role assignment permission required | ✅ | `test_role_assignment_requires_permission` |
| No privilege escalation by non-superusers | ✅ | `test_non_superuser_cannot_grant_roles_they_do_not_hold` |
| System roles protected from rename/delete | ✅ | `test_system_roles_are_protected` |
| Super Admin role always keeps all permissions | ✅ | `test_super_admin_role_always_keeps_all_permissions` |
| Last active Super Admin protection | ✅ | `test_last_super_admin_cannot_be_deactivated`, `test_last_super_admin_cannot_lose_the_super_admin_role`, `test_admin_cannot_deactivate_self` |
| Authorisation evaluated **before** input validation | ✅ | `test_business_admin_can_manage_users_but_not_settings` (would otherwise leak validation errors) |

### 3.5 Desktop UI

| Feature | Status | Evidence |
| --- | --- | --- |
| Light enterprise theme via QSS | ✅ | `resources/styles/light_theme.qss`, `components.qss` |
| Main window 1440×900, minimum 1180×720, resizable | ✅ | `test_window_can_be_resized` |
| Sidebar with 16 entries, sections, active state, "Soon" badges | ✅ | `test_super_admin_sees_every_module`; screenshots in `docs/screenshots` |
| Navigation hidden for missing permissions | ✅ | `test_sidebar_hides_unauthorised_modules` |
| Header: page title, business, activity count, profile menu | ✅ | `Header` component; `test_notifications_use_real_audit_entries` |
| Dashboard welcome + real counts | ✅ | `test_dashboard_shows_empty_states_not_fake_numbers` |
| Dashboard honest empty states for unimplemented metrics | ✅ | First 7 stat cards render `—` with phase captions; chart cards show "No data yet" |
| Recent activity from real audit rows | ✅ | `test_audit_page_shows_recorded_actions`, `test_notifications_use_real_audit_entries` |
| System status (DB, version, user, auth) | ✅ | `DashboardService.get_summary` + rendered rows |
| User management (list/search/filter/create/edit/deactivate/reset) | ✅ | `test_users_page_lists_and_filters` + 15 service tests |
| Role management (list, details, permissions grouped, custom roles) | ✅ | `test_roles_page_lists_six_system_roles`, `test_custom_role_can_be_created_and_deleted` |
| Audit viewer with filters + JSON detail | ✅ | `test_audit_page_shows_recorded_actions`, `AuditPage` |
| Settings: business / account / application / backup | ✅ | `test_settings_editable_for_super_admin`, `test_settings_read_only_without_permission` |
| Later-phase modules shown as "Coming Soon", never as working | ✅ | `ComingSoonPage`; `test_navigation_between_pages` asserts the page class |
| Responsive resizing of pages (scroll areas, splitters, stretch) | 🟡 | Layout uses scroll areas and stretch factors; verified at 1440×900 and 1280×800 offscreen only |

### 3.6 Audit logging

| Feature | Status | Evidence |
| --- | --- | --- |
| Centralised append-only audit service | ✅ | `app/services/audit_service.py` (no update/delete path) |
| All required actions recorded | ✅ | login success/failure, logout, user create/update/deactivate/activate, role assignment, role create/update, password change/reset, business settings, backup/restore, setup |
| Structured JSON old/new values | ✅ | `test_audit_entry_records_old_and_new_values` |
| Secrets redacted | ✅ | `_sanitise()` + `test_audit_never_contains_password_material` |
| Filtering by user / action / module / date + search | ✅ | `test_audit_filters`, `AuditPage` filters |
| RBAC-restricted audit access | ✅ | `test_sales_manager_cannot_read_audit_or_create_roles`, `test_employee_has_minimal_access` |
| Separate application log files | ✅ | `logs/application.log` written on launch and on every handled error |

---

## 4. Runtime verification (actual execution)

**Application launch** (`python main.py`, temporary data directory):

```
17:21:08 | INFO | bizpilot.main         | Starting BizPilot AI 1.0.0
17:21:08 | INFO | bizpilot.main         | Data directory: /scratch/work/launch_data
17:21:09 | INFO | bizpilot.database     | Database ready at .../launch_data/bizpilot_ai.db
17:21:09 | INFO | bizpilot.application  | Application context ready
17:21:09 | INFO | bizpilot.ui.controller| Fresh workspace detected - opening setup wizard
```

The process stayed alive in the Qt event loop until the harness stopped it, and
the data directory contained `bizpilot_ai.db` (+ `-wal`, `-shm`), `logs/`,
`backups/` and `exports/`.

**End-to-end UI flow executed offscreen:** setup wizard → provisioning →
dashboard → navigation across all pages → user creation → audit view → roles
view → window resize → logout → login → rejected login. All steps completed with
no unhandled exception.

**Backend flow executed:** migrate → provision → create user → RBAC denial for
an Employee → audit denial → bad password → dashboard summary → backup →
restore (with safety copy) → business update → audit count.

---

## 5. Test execution results

Command: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. python -m pytest -q`

```
........................................................................ [ 63%]
..........................................                               [100%]
114 passed in 146.55s (0:02:26)
```

| Suite | Tests | Focus |
| --- | --- | --- |
| `tests/unit` | 26 | Argon2id hashing, session tokens, validation rules |
| `tests/integration` | 33 | schema/constraints/transactions/persistence/backup, user management |
| `tests/security` | 37 | authentication, lockout, sessions, RBAC, escalation guards |
| `tests/ui` | 18 | wizard, login, dashboard, navigation, RBAC in UI, resize, empty states |
| **Total** | **114** | **all passed** |

Isolation: every test uses a temporary data directory and its own migrated
database (`tests/conftest.py`); the real user database is never touched. Real
Argon2id parameters are used in tests (no weakened hashing).

Additional verification executed outside pytest:

* `python -m compileall app main.py config.py tests` → all modules compile.
* Alembic/model drift check → no differences.
* UI screenshots rendered from the running widgets (`docs/screenshots/`).
* `deployment/build.spec` parsed and every bundled path confirmed present.

---

## 6. Files created

97 Python modules (≈10,900 lines) plus resources, tests and packaging files.

```
BizPilot_AI/
├── main.py, config.py, requirements.txt, README.md, .gitignore, .env.example
├── alembic.ini, pytest.ini
├── app/core/          application.py, config.py, database.py, exceptions.py,
│                      logging_config.py, constants.py
├── app/database/      base.py, session.py, seed.py,
│                      models/ (user, role, permission, user_role, role_permission,
│                      session, business, audit_log),
│                      repositories/ (user, role, permission, business, audit, session)
├── app/schemas/       auth_schema, user_schema, role_schema, business_schema
├── app/security/      password_manager, authentication, authorization,
│                      session_manager, validators
├── app/services/      base_service, auth_service, user_service, role_service,
│                      permission_service, business_service, dashboard_service,
│                      audit_service, backup_service
├── app/ui/            main_window, login_window, setup_wizard, app_controller,
│                      theme, navigation, ui_utils,
│                      components/ (sidebar, header, stat_card, notification_panel,
│                      confirmation_dialog),
│                      pages/ (dashboard, users, roles, audit, settings, coming_soon),
│                      dialogs/ (user, role, password, profile)
├── app/utils/         date_utils, formatters, validators
├── migrations/        env.py, script.py.mako, versions/0001_initial_schema.py
├── resources/         styles/light_theme.qss, styles/components.qss,
│                      icons/ (21 SVG + app_icon.ico)
├── tests/             conftest.py, unit/, integration/, security/, ui/
├── deployment/        build.spec, build_windows.bat, installer/
└── docs/              DEVELOPMENT_REPORT.md, screenshots/ (8 PNG)
```

---

## 7. Deliberate deviations from the brief (and why)

1. **Twelve later-phase page modules were not created as empty files.**
   The brief forbids "empty placeholder modules just to satisfy the folder
   structure". Instead one reusable `ComingSoonPage` renders every
   unimplemented module (with its phase and description), and
   `PAGE_FACTORIES` in `main_window.py` maps only the real Phase 1 pages. When a
   phase lands, its module file is added and registered there.
2. **Additional modules not listed in the tree:** `roles_page.py` (role
   management UI is required by §10), `session_repository.py` (session SQL must
   live in the repository layer), `seed.py` (idempotent reference data),
   `backup_service.py` (§11 backup needs a service), `app_controller.py`
   (window state machine), `theme.py`, `navigation.py`, `ui_utils.py`,
   `coming_soon_page.py`. Each exists because a required behaviour had nowhere
   to live under the original layout.
3. **`audit_logs.status` column added** so the required log format
   (`Status: SUCCESS`) and login-failure rows can be represented.
4. **Three permissions added to the catalogue** beyond the example list:
   `auth.change_password`, `users.reset_password`, `analytics.view` — needed to
   gate self-service password change, administrative resets and the Business
   Intelligence module.
5. **`is_superuser` is kept consistent with the Super Admin role** by the user
   service, so the two RBAC representations cannot diverge.
6. **System-role permission sets are re-synced from `app/core/constants.py` at
   every startup** (idempotent). Custom roles are never touched. This keeps the
   security model reproducible; it is documented in the code and README.
7. **`PySide6-Essentials` was used in this environment**; `requirements.txt`
   pins the full `PySide6==6.8.3` as specified. The application imports only
   modules present in both.

---

## 8. Known issues

1. **Windows executable not produced** (see §9). The build configuration is
   complete and static-checked, but no `.exe` was generated or tested.
2. **No Windows display run.** All UI verification used the offscreen Qt
   platform. Fonts, DPI scaling and native window chrome on Windows are
   therefore unverified; the theme specifies `Segoe UI` first, which is the
   Windows default.
3. **No setup-wizard recovery path.** Once provisioned, the wizard cannot be
   reached (by design). An authorised recovery procedure is not implemented —
   the brief marks it as optional for Phase 1, so it is reported as pending
   rather than half-built.
4. **Restore requires a fresh sign-in.** After a restore the app signs the user
   out because the restored session table may not contain the current token.
   This is intentional but worth knowing.
5. **Role filter in the user page reloads roles on each refresh** (small extra
   query). Harmless at Phase 1 data volumes; a cache belongs with the later
   performance work.
6. **Search is server-side `LIKE`** without full-text indexing — fine for
   hundreds of users, worth revisiting at scale.

---

## 9. Pending / not implemented

| Item | Reason |
| --- | --- |
| Windows `.exe` bundle | PyInstaller cannot cross-compile; this environment is Linux and has no Windows toolchain. The spec's analysis phase ran through all Qt/PySide6 hooks without configuration errors, then exceeded the 300-second per-command limit. Build with `deployment\build_windows.bat` on Windows. |
| Verification on a real Windows display | No display/Windows host available here. |
| Setup-wizard recovery procedure | Out of Phase 1 scope (optional in the brief). |
| Dark theme | Brief specifies light theme only. |
| Finance, Sales, CRM, Inventory, Suppliers, AI Agents, Automation, Approvals, BI, Reports | Phases 2–8. Navigation entries exist with "Soon" badges and explicit Coming Soon pages. |
| Multi-computer (LAN) access | Explicitly out of scope; SQLite single-file database. Repository layer is written to allow PostgreSQL later. |

---

## 10. How to run

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
python -m pip install -r requirements.txt
python main.py
```

First launch → setup wizard (business, owner, admin email, strong password) →
dashboard. Data is written to `%LOCALAPPDATA%\BizPilotAI` on Windows.

Tests:

```bash
python -m pytest -q
```

## 11. How to build the Windows executable

```bat
deployment\build_windows.bat
```

which performs: venv → `pip install -r requirements.txt` → `pytest` → 
`python -m PyInstaller deployment\build.spec --noconfirm`, producing
`dist\BizPilotAI\BizPilotAI.exe`. The bundle contains `resources/`,
`migrations/` and `alembic.ini`, and never a database.

---

## 12. Phase 1 completion checklist (verified status)

| Checklist item | Status |
| --- | --- |
| Python environment configured, dependencies installed | ✅ |
| Project structure created | ✅ |
| Database initialised, Alembic migration working | ✅ |
| Application launches successfully | ✅ |
| First-time setup wizard, Super Admin creation | ✅ |
| Secure login, Argon2id hashing | ✅ |
| Account lockout | ✅ |
| Session management, logout, password change | ✅ |
| Six default roles, permission records | ✅ |
| Role assignment, permission validation | ✅ |
| Service-level authorisation, protected system roles | ✅ |
| Light theme, sidebar, header, dashboard, profile | ✅ |
| User management, role management, settings | ✅ |
| Audit log viewer, working navigation | ✅ |
| Correct relationships, FK/unique constraints, transactions | ✅ |
| Persistent database, backup and restore | ✅ |
| Unit, integration, security and UI tests passed | ✅ (114/114) |
| No critical runtime errors | ✅ (launch + flows clean) |
| Windows executable built and tested | ⛔ Pending — no Windows toolchain in this environment |
