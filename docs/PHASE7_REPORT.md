# BizPilot AI — Phase 7 Development Report

**Project:** BizPilot AI — AI-Powered Business Automation Desktop Application
**Phase:** 7 of 10 — Advanced Business Intelligence, Predictive Analytics and Anomaly Detection
**Version:** 7.0.0
**Date:** 04 November 2026
**Status legend:** ✅ Implemented and verified · 🟡 Implemented, not live-verified · ⛔ Pending

---

## 1. Existing architecture assessment

Phase 6 left every seam Phase 7 needed:

* **Phase 2 services** (`sales`, `finance`, `inventory`, `customer`, `purchasing`)
  are the only source of records. The analytics collector calls them, so analytics
  inherits their RBAC and their accounting rules instead of re-deriving figures.
* **`finance_service.summary()`** already computes revenue, COGS, gross profit,
  operating expenses, net profit, cash received and receivables from the ledger —
  Phase 7 reuses it rather than writing a second accounting engine.
* **Phase 4 agents / Phase 3 orchestrator** — Phase 7 adds six read-only tools, so
  the Business Intelligence Agent and the chat can reach analytics without a
  parallel AI path.
* **Export service** (`write_pdf_report`, `write_report_csv`) — reused for the ten
  report types.
* **Gap found and fixed:** `SalesService` had no `list_invoices()`, which Phase 6's
  `retrieve_overdue_invoices` action assumed. It is now implemented, so receivables
  aging and the payment-follow-up workflow both work.

## 2. Files created

**Analytics package (`app/analytics/`)**
`schemas.py` · `periods.py` · `data_collector.py` · `data_validator.py` ·
`dataset_builder.py` · `analytics_engine.py`
`finance/financial_analytics.py` · `sales/sales_analytics.py` ·
`customers/customer_analytics.py` · `inventory/inventory_analytics.py` ·
`suppliers/supplier_analytics.py`
`anomaly/anomaly_detection.py` ·
`forecasting/forecasting_engine.py`, `model_selector.py`, `forecast_validator.py`,
`forecast_metrics.py` ·
`risk/business_risk_engine.py` · `simulation/business_simulation.py` ·
`kpi/kpi_engine.py` · `reports/analytics_report_service.py`

**Data** `app/database/models/analytics.py` ·
`migrations/versions/0007_analytics_tables.py`

**AI** `app/ai/registry/analytics_tools.py` (6 tools)

**Service** `app/services/analytics_service.py`

**UI** `app/ui/pages/business_intelligence.py`

**Tests** `tests/analytics_helpers.py` · `tests/unit/test_analytics_calculations.py` ·
`tests/integration/test_analytics_engine.py` · `tests/integration/test_forecasting.py` ·
`tests/security/test_analytics_security.py` · `tests/ui/test_business_intelligence.py`

## 3. Files modified

`app/core/constants.py` (5 intents, `analytics.manage` permission, 5 audit actions) ·
`app/core/application.py` (analytics engine + service wiring) ·
`app/ai/schemas/intent_schema.py` (5 intent definitions) ·
`app/ai/orchestrator/intent_classifier.py` (5 rule families) ·
`app/ai/orchestrator/task_planner.py` (5 plan templates + granularity/target helpers) ·
`app/ai/registry/tool_catalogue.py` (registers the analytics tools) ·
`app/services/sales_service.py` (`list_invoices`) ·
`app/ui/navigation.py`, `main_window.py`, `pages/__init__.py` (Business Intelligence
replaces the analytics placeholder) · tests asserting tool counts and schema
version · `README.md`.

## 4. Database migration

`0007_analytics` (`down_revision = 0006_autonomy`) adds eleven tables. No earlier
table was altered or dropped.

| Table | Purpose |
| --- | --- |
| `analytics_snapshots` | derived period bundle (no copy of raw business rows) |
| `business_kpis` | KPI reading with formula, completeness and sources |
| `detected_anomalies` | anomaly findings with method, evidence, severity, review status |
| `anomaly_reviews` | human review decisions |
| `forecast_runs` | method, windows, data size, horizon, version, status |
| `forecast_values` | per-period values with `is_forecast` flag |
| `forecast_model_metrics` | MAE, RMSE, MAPE, sMAPE, bias per run |
| `business_risk_assessments` | risk with likelihood, impact, score and formula |
| `business_simulations` | scenario, parameters, assumptions, hypothetical label |
| `simulation_results` | baseline vs simulated per metric |
| `analytics_report_history` | generated reports with period and file |

Verified: upgrade from a **Phase 6 database with data** kept its rows and created
all eleven tables; `compare_metadata` reports **no drift**; `integrity_check` is
`ok`. Persistence uses atomic upserts, so concurrent refreshes cannot collide.

## 5. Analytics modules implemented

All ten required engine methods exist on `BusinessAnalyticsEngine`:
`collect_business_data`, `validate_analytics_data`, `prepare_analytics_dataset`,
`calculate_business_kpis`, `analyze_business_performance`,
`compare_reporting_periods`, `calculate_growth_metrics`,
`generate_business_insights`, `identify_performance_gaps`,
`generate_analytics_report`. Periods: daily, weekly, monthly, quarterly, yearly
and custom, all resolved in the business timezone.

Verified on real records (November 2026 fixture): revenue 7,800.00, cash collected
3,500.00, COGS 5,400.00, gross profit 2,400.00, operating expenses 98,800.00, net
profit −96,400.00, receivables 25,920.00, growth −9.09%, 20 KPIs, 9 risks.

## 6. Anomaly detection methods

| Method | Used for |
| --- | --- |
| Z-score (threshold 2.5) | expense unusually high within its category |
| Median deviation (3× median) | expense spikes |
| Rule-based | duplicate-looking expenses, repeated stock adjustments, valuation inconsistencies, purchase price changes, delivery delays |
| Moving average (3-day window) | revenue drops (−40%) and sales spikes (+100%) |
| IQR (3× upper fence) | unusual order values |
| Period comparison | cash-flow deterioration |

Every finding stores `anomaly_id` (deterministic hash, so refreshes do not
duplicate), category, affected record, method, observed/expected values,
deviation, severity (LOW–CRITICAL), evidence, explanation, `detected_at` and
review status. Verified: a deliberately inserted 95,000.00 expense among four
~1,000.00 expenses was flagged by median deviation at HIGH severity, and no
finding anywhere contains the word "fraud".

## 7. Forecasting algorithms

* **NAIVE**, **MOVING_AVERAGE_3**, **EXPONENTIAL_SMOOTHING** (α = 0.3) always;
  **SEASONAL_NAIVE** (season 7) only with 14+ observations.
* Selection is by measured validation MAE; the naive baseline is always reported.
* Validation is walk-forward: each validation point is predicted from the history
  before it. Records are never shuffled.
* Prediction interval = ±1.96 × mean absolute validation residual (labelled as
  residuals, not a statistical confidence interval).
* Fewer than 4 monthly observations ⇒ `INSUFFICIENT_HISTORICAL_DATA` with the
  reason; leading all-zero months are not counted as observations.

## 8. Actual forecast validation results

Measured on the Phase 7 fixture (13 monthly observations, 3 validation points):

| Model | MAE | Selected |
| --- | --- | --- |
| NAIVE | 520.00 | ✅ (best) |
| MOVING_AVERAGE_3 | 1,328.89 | |
| EXPONENTIAL_SMOOTHING | 2,709.18 | |

Selected model metrics: RMSE 561.66, MAPE 6.30%, sMAPE 6.19%, bias −173.33.
A second fixture (UI run) selected MOVING_AVERAGE_3 with MAE 4,715.56 against a
naive baseline of 5,560.00 — reported exactly as measured, including when a model
fails to beat the baseline.

## 9. KPI formulas (20 KPIs)

Finance: revenue growth, gross margin, operating expense ratio, net cash flow,
outstanding receivables. Sales: sales growth, average order value, units sold, top
product contribution. Customers: new customers, repeat purchase rate, inactive
customers, customer concentration. Inventory: stock turnover, low-stock count,
stockout products, slow-moving stock value. Suppliers: on-time delivery rate,
average lead time, purchase price variation. Each carries its formula, period,
actual, comparison, unit, completeness, source records and limitation.

## 10. Dashboard implementation

**Business Intelligence** (Intelligence → Business Intelligence, gated by
`analytics.view`): six live cards (revenue, cash, expenses, net profit, growth,
receivables), a period selector, and ten tabs — Executive (20 KPIs + insights +
gaps), Financial (revenue/expense chart over six months, summary, expense split,
receivables aging), Sales, Customers (segments with rules, cohorts), Inventory,
Suppliers, Anomalies (with acknowledge/dismiss), Forecast (actual vs forecast
chart, validation metrics), Risk and What-if. Calculations run on background
workers; a missing module permission is explained inline instead of blocking the
UI. Screenshots: `docs/screenshots/60…65`.

## 11. Report implementation

Ten report types (executive, financial, sales, customer, inventory, supplier,
anomaly, forecast, risk, simulation) rendered to **PDF** and **CSV** through the
existing export service, each carrying the business name, period, generation
timestamp, actual metrics, forecast metrics where applicable, evidence basis,
assumptions and limitations. Every generation is recorded in
`analytics_report_history` and audited. Verified: a 12-row executive PDF and an
anomaly CSV were written and read back.

## 12. Test results

```
tests/unit                                   199 passed
tests/security                               103 passed in 255.05s
tests/integration (core)                     146 passed (+1 schema-version fix)
tests/integration (agents + analytics)        51 passed in 114.06s
tests/integration (db, workflows, collab)     88 passed
tests/ui                                      68 passed
------------------------------------------------------------
total                                         618 passed
```

| Suite | Tests | Phase 7 additions |
| --- | --- | --- |
| `tests/unit` | 199 | 10 calculation tests |
| `tests/integration` | 248 | 22 analytics + forecasting tests |
| `tests/security` | 103 | 11 analytics security tests |
| `tests/ui` | 68 | 7 BI dashboard tests |

Required coverage: financial figures match the database ✅ · unpaid invoices are
not cash ✅ · cancelled sales excluded ✅ · growth across periods ✅ · segmentation
rules ✅ · no turnover without cost data ✅ · inserted anomaly detected ✅ · no
fraud labelling ✅ · chronological validation ✅ · no forecast on thin history ✅ ·
forecasts separated from actuals ✅ · metrics match manual maths ✅ · simulations
write nothing ✅ · risk formula ✅ · dashboard uses real results ✅ · reports carry
period and sources ✅ · offline analytics ✅ · RBAC and module isolation ✅.

## 13. Verified working features

* All ten analytics sections compute from real records, and the numbers reconcile
  with the ledger (revenue ≠ cash, receivables = invoiced − paid).
* Six analytics tools are registered (46 total) and reachable from the
  orchestrator: "How did my business perform this month?" routes to
  `get_business_analytics`, "Forecast next month sales." to
  `forecast_business_metric`.
* Anomaly detection found the inserted outlier and persisted it; a review decision
  survives later refreshes.
* Forecasts are stored with their train/validation windows and measured metrics;
  insufficient history is stored with its reason.
* Simulations persist their baseline and results while leaving orders, expenses
  and stock untouched (asserted by count comparisons in tests).
* PDF and CSV reports are written, recorded in history and audited.

## 14. Partially implemented features

| Item | Status |
| --- | --- |
| Budget vs actual | 🟡 the engine reports "no budgets configured" because no budget table exists |
| Year-over-year comparison | 🟡 implemented, but only meaningful once a year of history exists |
| Product profitability | 🟡 gross margin per product is derivable, but historical per-sale cost is not stored |
| Customer churn model | 🟡 rule-based risk indicators only; no labelled history to train on |
| LLM narration of analytics | 🟡 tools and prompts are wired; live Ollama/Gemini inference unverified here |

## 15. Missing data limitations

1. No budget records, so budget variance cannot be calculated.
2. No supplier lead-time field; lead times come from purchase-order-to-receipt gaps
   and on-time delivery needs expected delivery dates.
3. Cost of goods sold uses the current product cost price (historical per-sale cost
   is not stored), so a cost change restates past margins.
4. No customer-communication or marketing data, so channel analytics are absent.
5. History is short (months, not years), so seasonal models and any ML approach
   (Isolation Forest, churn classifiers) are deliberately not trained.

## 16. Commands

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

# analytics suites only
python -m pytest tests/unit/test_analytics_calculations.py tests/integration/test_forecasting.py -v

# Windows build
deployment\build_windows.bat
```

---

## 17. Phase 7 completion checklist

| Criterion | Status |
| --- | --- |
| Financial analytics | ✅ |
| Sales analytics | ✅ |
| Customer analytics | ✅ |
| Inventory analytics | ✅ |
| Supplier analytics | ✅ |
| Anomaly detection | ✅ (6 methods, persisted, reviewable) |
| Forecasting where data allows | ✅ |
| Forecast validation | ✅ (walk-forward, measured metrics) |
| Risk assessment | ✅ (9 risks, documented formulas) |
| What-if simulations without modifying records | ✅ (5 scenarios) |
| KPI calculations verified | ✅ (20 KPIs, formula + provenance) |
| BI dashboard shows real results | ✅ |
| Reports export correctly | ✅ (PDF + CSV) |
| Orchestrator reaches analytics via registered tools | ✅ (6 tools) |
| Security and business isolation | ✅ |
| Works offline for supported analytics | ✅ |
