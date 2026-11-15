# BizPilot AI — Phase 4 Development Report

**Project:** BizPilot AI — AI-Powered Business Automation Desktop Application
**Phase:** 4 of 10 — Specialised Multi-Agent AI System
**Version:** 4.0.0
**Date:** 04 November 2026
**Status legend:** ✅ Implemented and verified · 🟡 Implemented, not live-verified · ⛔ Pending

---

## 1. Implemented agents

| Agent | Status | What it actually does | Verified |
| --- | --- | --- | --- |
| **Finance Agent** (`finance_agent`) | ✅ | Revenue level and period movement, expense mix and concentration, gross/net margins, cash vs revenue, receivables, median/IQR expense anomalies, 3–4 prioritised recommendations | Real run: 9 findings, 3 recommendations, confidence 0.90 |
| **Sales Agent** (`sales_agent`) | ✅ | Volume and average order value, month-over-month decline, top/low product by revenue with quantity kept separate, demand level and variability from completed orders | Real run: 5 findings, 1 recommendation, confidence 0.80 |
| **Customer Agent** (`customer_agent`) | ✅ | Transparent rule-based segmentation, inactivity detection, historical customer value and concentration, ranked follow-up suggestions | Real run: 3 findings, confidence 0.60 |
| **Inventory Agent** (`inventory_agent`) | ✅ | Low-stock detection, demand-aware reorder point and suggested quantity, overstock by days-of-cover, dead stock with an explicit "not necessarily obsolete" caveat, purchase recommendations | Real run: 3 findings, 1 recommendation, confidence 0.70, lead-time gap declared |
| **Business Intelligence Agent** (`business_intelligence_agent`) | ✅ | Runs all four specialists, de-duplicates findings, detects stockout risk and cost structure, ranks business risks, compares periods, simulates a price change | Real run: 4 agents, 20 findings, 9 risks, 5 recommendations, confidence 0.90 |

Each agent is a real analysis pipeline (`collect_context` → `analyse` →
`validate_output`), not a prompt wrapper. No agent returns hardcoded findings.

## 2. Registered tools (39 total)

| Group | Tools |
| --- | --- |
| Phase 2/3 business tools (27) | finance (6), sales (5), customers (4), inventory (4), suppliers (3), reporting (2), approval-gated actions (3) |
| **Phase 4 agent data tools (7)** | `get_expense_breakdown`, `get_monthly_financial_summary`, `get_product_velocity`, `get_low_performing_products`, `get_customer_portfolio`, `get_business_snapshot`, `schedule_customer_followup` (LOW risk) |
| **Agent runners (5)** | `run_finance_agent`, `run_sales_agent`, `run_customer_agent`, `run_inventory_agent`, `run_business_intelligence_agent` |

Deterministic capabilities that are pure functions (unit-tested, no DB access):
`detect_expense_anomalies`, `calculate_reorder_quantity`, `detect_overstock`,
`detect_dead_stock`, `segment_customers`, `calculate_customer_value`,
`get_customer_last_purchase`, `compare_business_periods`,
`analyze_revenue_and_expenses`, `analyze_sales_and_inventory`,
`identify_business_risks`, `simulate_business_scenario`,
`compare_sales_periods`, `generate_management_report` (via the export tools).

## 3. Successful execution tests (real database, real records)

Seeded business: 3 products with opening stock, 3 customers, 3 completed sales
with partial payments, 5 expenses (one deliberately large), one stock write-off,
one approved purchase order.

```
finance_agent:   COMPLETED  confidence 0.90  findings [REVENUE_LEVEL, EXPENSE_LEVEL,
                 EXPENSE_CONCENTRATION(MEDIUM), PROFIT_MARGIN(HIGH), OPEX_SHARE(MEDIUM)] +4
sales_agent:     COMPLETED  confidence 0.80  findings [SALES_VOLUME, TOP_PRODUCT, DEMAND_LEVEL]
customer_agent:  COMPLETED  confidence 0.60  findings [SEGMENTATION, CUSTOMER_VALUE(MEDIUM),
                 CUSTOMER_CONCENTRATION(MEDIUM)]
inventory_agent: COMPLETED  confidence 0.70  findings [LOW_STOCK(MEDIUM), OVERSTOCK(LOW),
                 DEAD_STOCK(LOW)]  gap: "supplier lead time (not recorded in Phase 4)"
business_intelligence_agent: COMPLETED confidence 0.90
                 agents_run [finance, sales, customer, inventory]
                 20 findings, 9 risks, 5 recommendations
```

Database rows after those runs (verified with SQL counts):
`agents 5 · agent_executions 13 · agent_findings 63 · agent_recommendations 17 · agent_memory 22`.

## 4. Multi-agent coordination

* `AgentCoordinator` owns registration, discovery and delegation with a **hard
  depth limit of 1** — agents cannot recurse.
* `run_many` isolates failures: a failing agent becomes a `FAILED` result, the
  others complete (verified with a non-existent agent in the batch).
* Batch runs adapt the task type to each agent's default when the batch task does
  not apply, so one task can drive several specialists.
* The BI agent de-duplicates findings by type + description (highest severity
  wins) and merges metrics per agent.

## 5. Orchestrator integration (8/8 commands routed correctly)

```
"Analyze my monthly finances."              → FINANCIAL_ANALYSIS        → run_finance_agent
"Show my top-selling products."             → GET_TOP_PRODUCTS          → run_sales_agent
"Identify inactive customers."              → GET_INACTIVE_CUSTOMERS    → run_customer_agent
"Which products should I reorder?"          → LOW_STOCK_ANALYSIS        → run_inventory_agent
"Find unusual business expenses."           → ANALYZE_EXPENSE_ANOMALIES → run_finance_agent
"Give me a complete business health report."→ BUSINESS_HEALTH_REPORT    → run_business_intelligence_agent
"Identify business risks."                  → BUSINESS_RISK_ANALYSIS    → run_business_intelligence_agent
"Compare sales and inventory performance."  → COMPARE_SALES_INVENTORY   → run_business_intelligence_agent
```

Each workflow stores the agent's findings, evidence, recommendations, metrics,
data gaps and confidence; the chat shows the agent summary plus its two most
important findings, and **Details** lists every finding with its evidence and
every recommendation.

## 6. Agent dashboard (PySide6)

Five live cards (status, last run, completed/failed, tools, open recommendations)
and four tabs per agent: Overview (intents, data tools, capabilities, memory),
Findings (severity, period), Recommendations (accept/dismiss/done) and Executions
(task, status, confidence, duration, summary). Every value comes from the
database — nothing is simulated. Screenshots: `docs/screenshots/30…33`.

## 7. Database changes

Migration `0004_agent_tables` (`down_revision = 0003_ai_orchestration`) adds five
tables; **no earlier table was altered or dropped**.

| Table | Key constraints |
| --- | --- |
| `agents` | unique `agent_code` |
| `agent_executions` | FK → agents/users, indexed status + workflow_id |
| `agent_findings` | FK → executions (cascade), severity indexed |
| `agent_recommendations` | FK → executions (cascade), status indexed |
| `agent_memory` | FK → agents (cascade) + source execution (set null) |

Verified: `upgrade head` from a Phase 3 database succeeded, `compare_metadata`
reports **no drift**, `integrity_check` is `ok`, and a Phase 2 database upgraded
in place earlier in this project with its data intact.

## 8. Security verification

| Attack / mistake | Result |
| --- | --- |
| Employee listing or running agents | `AuthorizationError` ✅ |
| Sales Manager running the Finance Agent | Completes with **data gaps**, every finance metric 0.00 — no data leak ✅ |
| Read-only role changing a recommendation | `AuthorizationError` ✅ |
| Invalid recommendation status (`HACKED`) | `ValidationError` ✅ |
| Agent attempting to place a purchase order | Impossible: no such tool; PO count unchanged after an inventory run ✅ |
| Finding without evidence | Rejected by `validate_output` ✅ |
| Prompt injection stored in a customer name | Treated as data; no instruction followed ✅ |
| Agent run without audit | Every run writes `AGENT_EXECUTED` / `AGENT_FAILED` ✅ |

## 9. Test results

```
tests/unit + tests/security        209 passed in 123.79s
tests/integration (excl. agents)   154 passed in 217.01s
tests/integration/test_agents.py    29 passed in  53.65s
tests/ui                            46 passed in 117.26s
----------------------------------------------------
total                              438 passed
```

| Suite | Tests | Phase 4 coverage |
| --- | --- | --- |
| `tests/unit` | 137 | agent analysis maths (anomalies, reorder formula, segmentation, overstock, dead stock, comparison, simulation), framework contract, confidence rules |
| `tests/integration` | 183 | each agent on real data, multi-agent isolation, persistence, memory, routing (8 commands), recommendation lifecycle |
| `tests/security` | 72 | RBAC for agents, cross-role data isolation, evidence enforcement, no purchase creation, injection, audit |
| `tests/ui` | 46 | agents dashboard, recommendation updates, permission-gated buttons, command centre with agent answers |

All Phase 1–3 tests still pass (updated where Phase 4 legitimately changed
routing: analysis intents now plan an agent step instead of a raw tool).

## 10. Bugs found and fixed during development

1. `Evidence(...)` was constructed positionally in several analysis modules —
   Pydantic models need keywords (would have crashed every agent).
2. Two agents were missing `default_task_type`, so `run_agent` defaulted to
   `"ANALYSIS"` and input validation rejected it.
3. `get_low_performing_products` sorted on a formatted money string and crashed
   parsing `"1,234.00"`.
4. Phase 3's `get_stock_valuation` tool referenced a non-existent
   `total_quantity` field (`total_stock_quantity`).
5. `get_product_velocity` passed an unsupported `limit=` to `list_orders`.
6. The agent card read `info["tool_count"]`, a property not present in
   `model_dump()`.
7. The dashboard called `selected_row_id()` where the table exposes `selected_id()`.
8. A classifier regex had an unparenthesised alternation
   (`…\binventory|stock\b`) that made "stock" alone match *compare sales and
   inventory*.
9. `utcnow()` truncates microseconds, so agent duration was always 0 ms —
   replaced with `perf_counter`.
10. Batch coordination sent one task type to every agent, failing agents that
    did not support it; batches now adapt per agent.

## 11. Incomplete / pending

| Item | Status |
| --- | --- |
| Live Ollama narration of agent findings | 🟡 router wired, no local model in this environment |
| Live Gemini narration | 🟡 client complete, no API key configured, cloud sharing off by default |
| Scheduled / event-triggered agent runs | ⛔ automation phase (events currently trigger analysis workflows, not agents) |
| Supplier lead-time data | ⛔ not in the schema; reorder maths declares it as a missing input |
| Demand-elasticity scenarios | ⛔ simulation holds volume constant and says so |
| Cross-agent free-form conversation | ⛔ delegation is bounded and orchestrator-controlled by design |
| Windows executable | ⛔ must be built on Windows |

## 12. Instructions to run

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

1. Complete the setup wizard.
2. Add a product with opening stock, a customer, then complete a sale and record
   an expense — the agents need real records.
3. Open **AI Agents** → select an agent → **Run agent** (choose task + period).
4. Or use the **AI Command Center**: "Give me a complete business health report."

Tests: `python -m pytest tests/unit tests/security`, then `tests/integration`,
then `tests/ui`.

Build: `deployment\build_windows.bat` on Windows.

---

## 13. Phase 4 completion checklist

| Criterion | Status |
| --- | --- |
| Base agent framework | ✅ |
| Finance Agent | ✅ verified on real data |
| Sales Agent | ✅ |
| Customer Agent | ✅ |
| Inventory Agent | ✅ |
| Business Intelligence Agent | ✅ |
| Agent registration (coordinator + `agents` table) | ✅ |
| Agent tool integration (7 data tools + 5 runners) | ✅ |
| Structured output validation | ✅ |
| Agent execution history | ✅ |
| Agent findings + evidence | ✅ |
| Recommendation storage + lifecycle | ✅ |
| Agent memory | ✅ |
| Multi-agent coordination with failure isolation | ✅ |
| AI Command Center integration (8 commands routed) | ✅ |
| Agent monitoring dashboard | ✅ |
| RBAC enforcement | ✅ |
| Offline operation | ✅ (deterministic analysis, no network) |
| Ollama integration tested | 🟡 not live-verified here |
| Gemini integration tested when configured | 🟡 not live-verified here |
| Unit tests passed | ✅ 137 |
| Integration tests passed | ✅ 183 |
| Existing application functionality preserved | ✅ all earlier tests green |
