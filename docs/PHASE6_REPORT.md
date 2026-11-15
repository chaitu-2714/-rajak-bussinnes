# BizPilot AI — Phase 6 Development Report

**Project:** BizPilot AI — AI-Powered Business Automation Desktop Application
**Phase:** 6 of 10 — Autonomous Business Workflow Engine with Permission-Based Execution
**Version:** 6.0.0
**Date:** 04 November 2026
**Status legend:** ✅ Implemented and verified · 🟡 Implemented, not live-verified · ⛔ Pending

---

## 1. Existing architecture assessment

Phase 5 left exactly the seams Phase 6 needed, so nothing was rebuilt:

* **Orchestrator + tool registry** — 40 permission-checked tools; Phase 6 adds no
  new AI tool and instead reuses `agent_manager` and `collaboration_manager`
  directly from workflow tasks.
* **Five agents** — invoked per task with a task type, returning structured
  findings; their persisted `agent_executions` rows remain the audit trail.
* **Collaboration manager** — used for `AGENT_COLLABORATION` tasks when several
  specialists must be reconciled.
* **Phase 2 services** — every business effect goes through
  `purchasing_service`, `finance_service`, `inventory_service`,
  `sales_service`, `customer_service`. No SQL is written in Phase 6 code.
* **Existing RBAC/audit/export** — reused; only one permission was added
  (`automation.execute`).
* **Gaps found:** nothing executed a decision, nothing gated it by policy, and
  there was no approval store. Phase 6 adds those three things and the scheduler.

## 2. Files created

**Core (`app/ai/autonomy/`)**
`actions.py` (17-action allowlist) · `policy_engine.py` · `approvals.py` ·
`templates.py` (6 workflows) · `engine.py` · `triggers.py` · `scheduler.py` ·
`__init__.py`

**Schemas** `app/ai/schemas/autonomy_schema.py`

**Data** `app/database/models/autonomy.py` ·
`migrations/versions/0006_autonomy_tables.py`

**Service** `app/services/autonomy_service.py`

**UI** `app/ui/pages/operations_center.py`

**Tests** `tests/unit/test_autonomy_policy.py` ·
`tests/integration/test_workflows.py` ·
`tests/security/test_autonomy_security.py` ·
`tests/ui/test_operations_center.py`

## 3. Files modified

`app/core/constants.py` (workflow/task/approval/trigger enums, 18 audit actions,
`automation.execute` permission) · `app/core/application.py` (engine, approvals,
triggers, scheduler, service wiring + startup seeding and recovery) ·
`app/ui/navigation.py`, `main_window.py`, `pages/__init__.py` (Operations Center
replaces the Automation Studio placeholder) · `app/ui/ui_utils.py`
(`show_error` now accepts exceptions) · tests asserting tool counts, schema
version and coming-soon placeholders · `README.md`.

## 4. Database migration

`0006_autonomy` (`down_revision = 0005_collaboration`) adds ten tables. No
earlier table was altered or dropped.

| Table | Purpose |
| --- | --- |
| `autonomous_workflows` | workflow instance: type, trigger, status, phase, retries, verification |
| `workflow_tasks` | task type, agent, action, dependencies, risk, permission, idempotency key, result |
| `workflow_triggers` | unique trigger key per event/schedule slot (duplicate prevention) |
| `autonomy_policies` | mode, maximum amount, allowed roles, approval count, daily limit, enabled |
| `approval_requests` | action, payload, impact, risk, reason, evidence, expiry, decision, execution result |
| `approval_decisions` | immutable decision rows (approved / rejected / expired / cancelled) |
| `workflow_execution_logs` | structured execution log per task |
| `scheduled_workflows` | schedule key, frequency, time, timezone, next run, last status |
| `workflow_idempotency_records` | unique key per executed action |
| `workflow_dead_letters` | events that could not be turned into workflows |

Verified: upgrade from a **Phase 5 database with data** kept its rows and created
all ten tables; `compare_metadata` reports **no drift**; `integrity_check` is `ok`.

## 5. Implemented workflow types

| Workflow | Tasks | Verified behaviour |
| --- | --- | --- |
| `LOW_STOCK_REPLENISHMENT` | 9 | reads stock + history, Inventory/Sales/Finance agents, recommendation, approval, verification, notification |
| `CUSTOMER_FOLLOWUP` | 6 | history, customer + sales analysis, internal draft, approval step skipped honestly (no provider) |
| `DAILY_SUMMARY` | 4 | metrics, BI consolidation, CSV report, verification — completes offline |
| `UNUSUAL_EXPENSE_REVIEW` | 4 | finance anomaly analysis, BI context, internal alert; expense left untouched |
| `SALES_RECOVERY` | 8 | four agents + BI coordination, action plan for humans |
| `PENDING_PAYMENT_FOLLOWUP` | 6 | overdue invoices, customer context, reminder draft, approval |

Task types used: `DATA_RETRIEVAL`, `BUSINESS_ANALYSIS`, `AGENT_COLLABORATION`,
`VALIDATION`, `RECOMMENDATION`, `APPROVAL_REQUEST`, `BUSINESS_ACTION`,
`NOTIFICATION`, `REPORT_GENERATION`, `VERIFICATION` — all ten declared and
validated by schema.

## 6. Implemented autonomous triggers

* **Events** (`StockBelowMinimum`, `ExpenseRecorded` above a 10,000 threshold).
  Live run: 2 events → 2 workflows, 4 events ignored (unmapped), and a second scan
  created **0** more.
* **Schedules**: daily summary, daily payment follow-up, weekly sales review, each
  with a timezone-aware next run and slot claiming.
* **Manual**: any workflow can be started from the Operations Center.
* `PurchaseOrderCreated` and `GoodsReceived` are deliberately unmapped so a
  purchase order can never re-trigger purchase automation.

## 7. Permission and approval implementation

* `AutonomyPolicyEngine` evaluates **default deny**: unknown action → denied;
  hard-restricted action → denied; missing/disabled policy → denied; role not
  allowed → denied; missing action permission → denied; daily limit reached →
  denied. An amount above the automatic ceiling escalates to approval.
* 17 default policies seeded at startup (10 automatic, 6 approval, 1 restricted).
* Approval requests carry the exact payload, financial impact (3,600.00 in the
  live run), risk, reason and evidence; they expire after 48 hours.
* Approving re-checks permission, policy, expiry and live state, executes once,
  records the decision, resumes the workflow and audits it. Rejecting requires a
  reason and blocks execution. A requester cannot self-approve unless they are the
  only eligible approver (single-user workspaces would otherwise deadlock) — that
  exception is recorded on the request and in the audit log.
* `delete_financial_transaction` can never be approved or automated.

## 8. Scheduler implementation

`ScheduledWorkflow` rows persist frequency, time-of-day, weekday and timezone
(Asia/Kolkata). `next_run_time` computes the next slot in the business timezone and
stores it as UTC. Each slot is claimed by inserting a unique
`SCHEDULE:<key>:<slot>` trigger, so a restart or a double tick cannot run the same
slot twice. The UI exposes enable/disable and "run due now"; the desktop timer
calls `tick()` off the UI thread.

## 9. Recovery and idempotency

* Every executed action writes a `workflow_idempotency_records` row keyed by
  `<workflow_ref>:<task_key>` (or `approval:<ref>`); a retry or replay returns the
  stored result instead of repeating the effect.
* Workflows left `RUNNING` by a crash are paused at startup with a `RECOVERED` log
  entry and can be resumed; completed tasks and executed actions are preserved.
* Stale approvals expire at startup.
* Rollback compensates only actions declared reversible (purchase order → cancel,
  expense → reverse, price change → restore) and reports the rest as not
  reversible.

## 10. UI implementation

**Operations Center** (Intelligence → Operations Center, gated by
`automation.view`): five live cards, workflow list with real task progress, detail
panel (objective, trigger, status, verification results, approvals, activity log),
task table (type, agent/action, status, risk, retries, error), and three tabs —
Workflows (start, resume, retry, cancel, roll back), Approval Center (pending
requests with action, impact, risk, requester, expiry, evidence; approve / reject /
expire) and Autonomy Settings (policy table with mode, maximum amount, daily limit,
enabled; schedule table with enable/disable and run-due). Long runs use background
workers. Screenshots: `docs/screenshots/50…52`.

## 11. Tests executed and actual results

```
tests/unit + tests/security                 281 passed in 230.07s
tests/integration (core)                    146 passed (+1 schema-version fix)
tests/integration (db, agents, collab, wf)   88 passed in 216.30s
tests/ui                                     61 passed (after navigation fix)
------------------------------------------------------------
total                                        568 passed
```

| Suite | Tests | Phase 6 additions |
| --- | --- | --- |
| `tests/unit` | 189 | 16 policy/allowlist tests |
| `tests/integration` | 226 | 17 workflow tests |
| `tests/security` | 92 | 10 automation security tests |
| `tests/ui` | 61 | 7 Operations Center tests |

Required test coverage: low-stock event → workflow ✅ · multi-agent coordination ✅ ·
no purchase order before approval ✅ · approval executes exactly once ✅ ·
rejection blocks execution ✅ · expired approval cannot authorise ✅ ·
unauthorised approver refused ✅ · duplicate events ignored ✅ · duplicate retries
don't duplicate records ✅ · daily report on schedule ✅ · restart recovery ✅ ·
failed agent never reported as success ✅ · UI reflects real records ✅ · offline
workflow completes ✅ · workflow cannot change its own policy ✅.

## 12. Verified working features (real database)

* `LOW_STOCK_REPLENISHMENT` ran 9 tasks (Inventory, Sales and Finance agents all
  completed), stopped at `WAITING_APPROVAL` with **0** purchase orders, and after
  approval created **exactly one** `PO-2026-0001` (3,600.00) and finished
  `COMPLETED` with verification `True`.
* `DAILY_SUMMARY` completed offline with a real CSV report and verification passed.
* Event scan: 2 workflows created, 4 ignored, second scan created none.
* Policy edit persisted; making `delete_financial_transaction` automatic was
  refused; a restricted action was denied at evaluation time.
* Rollback reversed the purchase order and reported nothing else reversible.
* Persisted rows after the smoke run: 4 workflows, 26 tasks, 2 approvals,
  17 policies, 3 schedules, 28 log entries, 11 idempotency records.

## 13. Partially implemented features

| Item | Status |
| --- | --- |
| Customer/payment messaging | 🟡 drafts are produced and stored; no provider is connected, so the approval step is skipped with an explicit reason |
| Conditional branching inside a workflow | 🟡 dependency graphs and approval gates are supported; arbitrary `if/else` branching is not modelled (templates are fixed graphs) |
| Live Ollama/Gemini reasoning in workflows | 🟡 router available, no model or key in this environment |

## 14. Known limitations

1. Templates are fixed task graphs; operators choose a workflow, not individual tasks.
2. Single-user approval exception (documented above) — with two eligible approvers
   self-approval is refused.
3. Rollback cannot reverse stock adjustments or payments; those are recorded as not
   reversible rather than compensated silently.
4. One scheduler instance per desktop (SQLite, single machine) — deliberate.
5. Sales-recovery and payment-follow-up thresholds are static constants; making them
   per-business settings belongs to a later phase.
6. Dead letters are retried manually (button/service call), not on a timer.
7. Windows `.exe` still requires a Windows build.

## 15. Commands

```bash
# application
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py

# tests (batches, because a full run exceeds 5 minutes)
python -m pytest tests/unit tests/security
python -m pytest tests/integration
python -m pytest tests/ui

# single workflow suite
python -m pytest tests/integration/test_workflows.py -v

# Windows build
deployment\build_windows.bat
```

---

## 16. Phase 6 completion checklist

| Criterion | Status |
| --- | --- |
| Event-driven workflow triggers | ✅ |
| Workflow planning | ✅ |
| Multiple agents per workflow | ✅ (3–5 agents) |
| Automatic execution for permitted actions | ✅ (10 automatic actions) |
| Approval-required actions pause | ✅ |
| Approval and rejection work | ✅ |
| Approved workflows resume | ✅ |
| Restricted actions blocked | ✅ |
| Duplicate execution prevented | ✅ (idempotency + trigger keys) |
| Scheduled workflows work | ✅ |
| Restart recovery works | ✅ |
| Audit logs record real actions | ✅ (18 new actions) |
| Offline workflows work | ✅ |
| Operations Center works | ✅ |
| Integration tests pass | ✅ 226 |
