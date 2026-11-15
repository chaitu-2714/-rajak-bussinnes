# BizPilot AI — Phase 3 Development Report

**Project:** BizPilot AI — AI-Powered Business Automation Desktop Application
**Phase:** 3 of 10 — Central AI Orchestrator
**Version:** 3.0.0
**Date:** 04 November 2026
**Status legend:** ✅ Implemented and verified · 🟡 Implemented, not live-verified · ⛔ Pending

---

## 1. Implemented features

| Feature | Status | Evidence |
| --- | --- | --- |
| Central orchestrator (`process_command`, `process_event`, `execute_workflow`, `cancel_workflow`, `get_workflow_status`, `approve_workflow`) | ✅ | 23 workflow integration tests, live smoke run |
| Intent classifier — 19 intents, rule scoring, confidence, ambiguity, unknown handling | ✅ | 30 unit tests + 19-command live classification sweep |
| LLM-assisted classification (Ollama / Gemini) with registry validation | ✅ | Fake-provider tests; unregistered intent rejected |
| Task planner — deterministic plan templates, dependencies, risk, approval flag | ✅ | 16 unit tests, 4-step purchase plan verified |
| Plan validator — tool allowlist, argument schemas, permissions, cycles, step limit, HIGH-risk block | ✅ | 9 unit tests |
| Tool registry — 27 tools, all Phase 2 service calls | ✅ | Catalogue tests + execution tests |
| Agent registry — 5 agents with intents, tools, permissions, health | ✅ | Health report in UI and tests |
| Workflow executor on LangGraph with SQLite checkpoints | ✅ | Graph compiled, checkpoint file written, resume API |
| Workflow persistence, step persistence, retry, cancellation, restart recovery | ✅ | Integration tests incl. interrupted-workflow recovery |
| Model router — Ollama, Gemini, deterministic fallback, priority, preference, cloud gating | ✅ | 14 unit tests |
| Event-driven orchestration for 8 business events, idempotent per event | ✅ | 7 integration tests |
| Approval workflow for data-changing actions | ✅ | Expense created only after approval |
| AI Command Center UI with background workers | ✅ | 11 UI tests, screenshots |
| AI provider settings (cloud sharing, keys, priority) | ✅ | Settings dialog + service tests |
| Audit logging for AI actions | ✅ | `AI_COMMAND`, `AI_WORKFLOW_*`, `AI_SETTINGS_UPDATED` entries |
| Migration `0003_ai_orchestration` (6 tables) | ✅ | Applied, drift check clean |
| Live Ollama inference | 🟡 | Real client implemented; no Ollama server in this environment |
| Live Gemini inference | 🟡 | Real client implemented; no API key configured |
| Windows executable | ⛔ | Cannot cross-compile from Linux |

## 2. Files created

**AI layer (`app/ai/`)**
`orchestrator/orchestrator.py` · `orchestrator/intent_classifier.py` ·
`orchestrator/task_planner.py` · `orchestrator/workflow_executor.py` ·
`orchestrator/workflow_graph.py` · `orchestrator/workflow_state.py` ·
`registry/tool_registry.py` · `registry/tool_catalogue.py` ·
`registry/tool_inputs.py` · `registry/agent_registry.py` ·
`routing/model_router.py` · `routing/ollama_provider.py` ·
`routing/gemini_provider.py` · `routing/fallback_provider.py` ·
`routing/provider.py` · `routing/credentials.py` ·
`events/event_processor.py` (subscriber + processor + dispatcher) ·
`schemas/intent_schema.py` · `schemas/tool_schema.py` ·
`schemas/workflow_schema.py` · `validators/plan_validator.py` ·
`validators/response_validator.py` · `validators/security.py`

**Service / data / UI**
`app/services/ai_orchestration_service.py` ·
`app/database/models/ai.py` · `app/database/repositories/ai_repository.py` ·
`app/ui/pages/ai_command_page.py` ·
`app/ui/workers/orchestration_worker.py` ·
`app/ui/dialogs/ai_settings_dialog.py` ·
`migrations/versions/0003_ai_orchestration.py`

**Tests**
`unit/test_intent_classifier.py` · `unit/test_task_planner.py` ·
`unit/test_tool_registry.py` · `unit/test_model_router.py` ·
`integration/test_workflow_system.py` · `integration/test_event_orchestration.py` ·
`security/test_ai_security.py` · `ui/test_ai_command_center.py`

## 3. Files modified

`app/core/constants.py` (AI statuses, risk levels, provider names, trigger types,
6 AI audit actions, 3 AI permissions, role grants) ·
`app/core/application.py` (AI layer wiring) · `app/core/exceptions.py`
(`safe_message`) · `app/database/models/__init__.py` ·
`app/services/ai_orchestration_service.py` (new) · `app/ui/navigation.py`
(Command Center live, gated by `agents.view`) · `app/ui/main_window.py`
(page registration, graceful page shutdown) · `app/ui/pages/__init__.py` ·
`resources/styles/components.qss` (chat bubbles, chat chrome) ·
`tests/conftest.py` (conversation fixtures) ·
`tests/integration/test_database.py` (schema version) ·
`requirements.txt` · `README.md`.

## 4. Database changes

Migration `0003_ai_orchestration` (`down_revision = 0002_core_business`) creates
six tables; **no Phase 1 or Phase 2 table was altered or dropped**.

| Table | Purpose | Key constraints |
| --- | --- | --- |
| `ai_conversations` | chat threads per user | FK → users (cascade) |
| `ai_messages` | user/assistant messages + JSON metadata | FK → ai_conversations (cascade), indexed by time |
| `ai_workflows` | one row per workflow: intent, plan JSON, status, provider, result, attempts | unique `workflow_id`; unique `source_event_id` (event idempotency); FK → conversations, users, business_events |
| `ai_workflow_steps` | one row per tool call: input, output, status, duration, error | unique (`workflow_id`, `step_number`) |
| `ai_tool_registry` | mirror of the tool catalogue (name, permission, risk, enabled) | unique `tool_name` |
| `ai_model_settings` | provider config: model, enabled, priority, JSON configuration | unique `provider` |

Migration status: applied automatically at startup (`upgrade head`), verified with
`compare_metadata` → **no drift**, and a Phase 2 database was upgraded in place
during the smoke run without data loss.

## 5. Supported intents (actual, verified)

All 19 intents classified correctly in a live sweep of natural-language commands:

```
"Show this month's revenue."                        → GET_REVENUE (0.85)
"What are my expenses this month?"                  → GET_EXPENSES (0.85)
"Calculate my business profit."                     → CALCULATE_PROFIT (0.86)
"Show my cash flow."                                → GET_CASH_FLOW (0.91)
"Analyse my sales."                                 → ANALYZE_SALES (0.73)
"Which products are selling the most?"              → GET_TOP_PRODUCTS (0.91)
"Check the stock of Assam Tea."                     → CHECK_STOCK (0.81)
"Find products running out of stock."               → LOW_STOCK_ANALYSIS (0.93)
"Tell me about my customers."                       → CUSTOMER_ANALYSIS (0.73)
"Show customers who haven't purchased recently."    → GET_INACTIVE_CUSTOMERS (0.95)
"Show supplier details."                            → GET_SUPPLIER_DETAILS (0.81)
"Prepare my monthly financial report."              → GENERATE_FINANCIAL_REPORT (0.95)
"Generate a sales report."                          → GENERATE_SALES_REPORT (0.95)
"Generate an inventory report."                     → GENERATE_INVENTORY_REPORT (0.95)
"Create a sale of 2 Assam Tea for Asha Rao."        → CREATE_SALES_ORDER (0.91)
"Record an expense of 5000 for shop rent."          → CREATE_EXPENSE (0.93)
"Check whether I can purchase 50 units of Assam Tea."→ CREATE_PURCHASE_RECOMMENDATION (0.91)
"How is my business doing?"                         → GENERAL_BUSINESS_ANALYSIS (0.81)
"Sing me a song."                                   → UNKNOWN_INTENT (0.00)
```

Ambiguous commands ("revenue and expenses") return a clarification question
instead of guessing.

## 6. Registered tools (27)

| Category | Tools | Risk |
| --- | --- | --- |
| Finance | `get_revenue`, `get_expenses`, `calculate_profit`, `get_cash_flow`, `get_outstanding_payments` | READ_ONLY |
| Finance (export) | `generate_financial_report` | LOW |
| Sales | `get_sales_summary`, `get_sales_history`, `get_top_products`, `get_sales_trends`, `get_pending_orders` | READ_ONLY |
| Customers | `get_customer_summary`, `get_inactive_customers`, `get_customer_history`, `get_customer_purchase_history` | READ_ONLY |
| Inventory | `get_product_stock`, `get_low_stock_products`, `get_stock_movements`, `get_stock_valuation` | READ_ONLY |
| Suppliers | `get_supplier_details`, `get_supplier_purchase_history`, `get_purchase_order_status` | READ_ONLY |
| Reporting | `generate_sales_report`, `generate_inventory_report` | LOW |
| Actions | `prepare_sales_order`, `prepare_expense` (drafts, never write) | MEDIUM (approval) |
| Actions | `create_purchase_recommendation` | READ_ONLY |

Every tool declares an input schema (Pydantic), a permission, a risk level and a
timeout. Handlers call existing services — no tool contains SQL or business logic.

## 7. Model integration results

| Provider | Implementation | Verified here |
| --- | --- | --- |
| Ollama (`ollama` 0.6.3) | `chat()` with JSON mode, model listing for health, 20 s timeout | Client constructed, health correctly reports "not reachable — start it with `ollama serve`". **No server available in this environment, so no live inference.** |
| Gemini (`google-genai` 2.34.0) | `generate_content` with JSON mime type and system instruction | Client code complete; reports "No Gemini API key configured". **No key available, so no live inference.** |
| Deterministic fallback | Templates composed from verified tool output | ✅ Every command in this report ran through it |

Routing verified by tests: priority order, explicit preference, disabled
providers, cloud gating (Gemini is skipped while cloud sharing is off), both
providers down → fallback, empty model replies discarded.

**Honest statement:** the AI providers are real client integrations, but only the
deterministic path was exercised end to end. Claiming live LLM behaviour would be
false.

## 8. Workflow execution results

Live run (offscreen Qt, real database):

* "Show this month's revenue." → `GET_REVENUE`, 1 step, COMPLETED, answer
  "Revenue for this month is 3,120.00 (net of refunds)."
* "Which products are selling the most?" → 1 step, COMPLETED, ranked product list.
* "Find products running out of stock." → 1 step, COMPLETED, 1 product flagged.
* "Check whether I can purchase 50 units of Assam Tea." → 4 steps
  (`get_product_stock` → `get_sales_history` → `get_cash_flow` →
  `create_purchase_recommendation`), COMPLETED, recommendation produced with
  stock, demand, cost and cash context.
* "Record an expense of 5000 for shop rent." → prepared, `WAITING_FOR_APPROVAL`,
  then approved → `EXP-2026-0002` for 5,000.00 created via the Phase 2 finance
  service.
* "Sing me a song." → `UNKNOWN_INTENT`, workflow recorded with guidance.
* Event processing: 3 business events → 3 AI workflows with trigger `EVENT`
  (`GET_EXPENSES`, `GET_EXPENSES`, `LOW_STOCK_ANALYSIS`), all COMPLETED.

Workflow state machine verified: PENDING → RUNNING → COMPLETED / FAILED /
CANCELLED / WAITING_FOR_APPROVAL, with step-level statuses persisted.

## 9. Test results

Executed in three batches (the runner caps a single command at 300 s):

```
tests/unit + tests/security   165 passed in 100.00s
tests/integration             153 passed in 195.04s
tests/ui                       38 passed in  72.85s
---------------------------------------------------
total                         356 passed
```

| Suite | Tests | Coverage |
| --- | --- | --- |
| `tests/unit` | 103 | Intent classifier, planner, plan validator, tool registry, model router, money, auth primitives |
| `tests/integration` | 153 | Workflow system, events, Phase 2 business modules, end-to-end sale/finance |
| `tests/security` | 62 | RBAC (Phase 1–3), AI denials, cross-user isolation, injection, redaction |
| `tests/ui` | 38 | Login/wizard/navigation, business pages, AI Command Center |

Phase 3 specific: 74 new tests (30 classifier, 16 planner, 17 tool registry,
14 router, 23 workflow, 7 events, 14 security, 11 UI — some counted in more than
one file). All Phase 1 and Phase 2 tests still pass.

## 10. Security verification

| Attack / mistake | Result |
| --- | --- |
| Command `os.system`, `eval`, `run_sql`, `delete_user`, `grant_admin`, `read_file` | Rejected: tool not registered ✅ |
| Plan containing an unknown tool | Rejected by the validator ✅ |
| Plan with invalid arguments (negative amount, empty description) | Rejected before execution ✅ |
| Plan requiring a permission the user lacks | Rejected with the exact permission named ✅ |
| Plan with a circular dependency / >8 steps / HIGH risk | Rejected ✅ |
| Employee running an AI command | `AuthorizationError` ✅ |
| Reading another user's conversation or workflow | `AuthorizationError` ✅ |
| Prompt injection in a command | Flagged, never sent to a model, handled by rules ✅ |
| Injection text stored in business data (customer name) | Ignored by the pipeline ✅ |
| API key in the database or audit log | Never written (redacted as `***redacted***`) ✅ |
| API key in the source tree | Not present; stored in the OS credential store ✅ |
| Model output containing SQL or secrets | Redacted by the response validator ✅ |
| Cloud leakage by default | Gemini skipped unless an admin enables cloud sharing ✅ |

## 11. Known bugs

1. **QThread warning in the UI smoke script** — a background event worker can
   still be running when a test window is destroyed. The application handles this
   in `MainWindow.closeEvent` → `page.shutdown()`, which waits for workers; the
   warning appears only in the scripted test harness.
2. **Bubble height measurement is metric-based** — long answers are measured with
   `QFontMetrics` plus 8 px slack. Correct for the current theme; a large custom
   font could still clip by a line.
3. **Step timeout is cooperative** — a SQLite call that hangs cannot be killed
   (Python threads are not pre-emptible); the workflow fails after the timeout
   instead of the thread being terminated.
4. **Document numbering remains max+1** (Phase 2 behaviour) — fine for a
   single-user desktop app.

## 12. Incomplete / pending functionality

| Item | Status |
| --- | --- |
| Live Ollama inference | 🟡 client complete, no server here |
| Live Gemini inference | 🟡 client complete, no API key here |
| Specialised agent reasoning (Phase 4) | ⛔ registry and interfaces only, by design |
| Automated actions from events | ⛔ events trigger read-only analysis in Phase 3 |
| Workflow resumption from checkpoint mid-plan | ⛔ restarts mark workflows FAILED and offer retry (checkpoint API is in place) |
| Windows executable | ⛔ must be built on Windows |
| Cross-module scheduled reports | ⛔ Phase 8 |

## 13. Instructions to run

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

1. Complete the setup wizard (first launch).
2. Create a product and opening stock, a customer, then complete a sale — so the
   Command Center has real data to analyse.
3. Open **AI Command Center** and try "Show this month's revenue".
4. Optional: install Ollama (`ollama pull llama3.2`) for model-generated prose;
   configure Gemini in **AI settings** and enable cloud sharing if you want it.

Tests: `python -m pytest tests/unit tests/security`, then `tests/integration`,
then `tests/ui`.

Build: `deployment\build_windows.bat` on Windows → `dist\BizPilotAI\BizPilotAI.exe`.

---

## 14. Phase 3 completion checklist

| Criterion | Status |
| --- | --- |
| Central Orchestrator implemented | ✅ |
| Intent classifier implemented | ✅ |
| Task planner implemented | ✅ |
| Tool registry implemented (27 tools) | ✅ |
| Agent registry implemented (5 agents) | ✅ |
| Workflow executor implemented | ✅ |
| LangGraph integration working | ✅ (graph + SQLite checkpointer) |
| Ollama integration verified | 🟡 client verified as unavailable/healthy detection only |
| Gemini integration verified when configured | 🟡 client complete, no key available |
| Offline fallback working | ✅ (all reported commands ran offline) |
| Business event processing working | ✅ |
| Workflow persistence working | ✅ |
| Permission validation working | ✅ |
| AI Command Center functional | ✅ |
| Background processing functional | ✅ (Qt worker threads) |
| Workflow cancellation functional | ✅ |
| Audit logging functional | ✅ |
| Unit tests passed | ✅ 103 |
| Integration tests passed | ✅ 153 |
| Security tests passed | ✅ 62 |
| Existing Phase 1 and Phase 2 features preserved | ✅ (all earlier tests still green) |
