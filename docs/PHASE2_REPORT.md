# BizPilot AI — Phase 2 Development Report

**Project:** BizPilot AI — AI-Powered Business Automation Desktop Application
**Phase:** 2 of 10 — Core Business Management Modules
**Version:** 2.0.0
**Date:** 04 November 2026
**Status legend:** ✅ Implemented and verified · 🟡 Implemented, partially verified · ⛔ Pending

---

## 1. Modules completed

| Module | Status | What actually works |
| --- | --- | --- |
| Finance Management | ✅ | Expense create/edit/reverse, transaction ledger, revenue vs cash separation, gross/net profit, 6 reports, CSV + PDF export, PyQtGraph trend charts |
| Sales Management | ✅ | Multi-product order builder, draft → confirmed → completed, atomic completion (stock + invoice + revenue), invoices, partial/full payments, cancellation with stock and financial reversal |
| Customer Relationship Management | ✅ | Records with duplicate detection, purchase history, outstanding balance, payment history, rule-based segmentation, local follow-up reminders, CSV export |
| Inventory Management | ✅ | Categories, products (SKU generation, Decimal pricing), opening stock, additions, reductions, damage, full movement ledger, low-stock alerts, cost-basis valuation |
| Supplier Management | ✅ | Supplier directory, purchase orders (draft → approved → ordered → partially/fully received), partial goods receipts, over-receipt prevention, supplier purchase history |
| Business event foundation | ✅ | Transactional outbox for 8 event types, dispatched after commit, retryable, inspection via the audit permission |
| Report export | ✅ | CSV (inventory, sales, customers, expenses) and PDF (invoice, 6 financial reports) — fully offline via ReportLab |

**Deliberately not implemented** (and clearly marked "Soon" in the UI): AI
Command Center, AI Agents, Automation Studio, Approval Center, Business
Intelligence, Reports (cross-module). No placeholder data or dead buttons exist
in the delivered application.

---

## 2. Files created

| Area | Files |
| --- | --- |
| Models | `catalog.py`, `inventory.py`, `crm.py`, `sales.py`, `finance.py`, `purchasing.py`, `events.py`, `types.py` (Money TypeDecorator) |
| Repositories | `catalog_repository.py`, `inventory_repository.py`, `crm_repository.py`, `sales_repository.py`, `finance_repository.py`, `supply_repository.py`, `event_repository.py` |
| Schemas | `catalog_schema.py`, `inventory_schema.py`, `crm_schema.py`, `sales_schema.py`, `finance_schema.py`, `purchasing_schema.py` |
| Services | `inventory_service.py`, `customer_service.py`, `sales_service.py`, `finance_service.py`, `purchasing_service.py`, `event_service.py`, `export_service.py`, `numbering.py` |
| UI pages | `finance_page.py`, `sales_page.py`, `customers_page.py`, `inventory_page.py`, `suppliers_page.py` |
| UI dialogs | `catalog_dialogs.py` (product, category, stock adjustment), `crm_dialogs.py` (customer, follow-up), `sales_dialogs.py` (order builder, payment, invoice, reason), `finance_dialogs.py` (expense), `supply_dialogs.py` (supplier, purchase order, goods receipt) |
| UI components | `tables.py` (sortable data table with empty states) |
| Migration | `migrations/versions/0002_core_business_tables.py` (19 tables) |
| Tests | `unit/test_money.py`, `integration/test_inventory.py`, `test_sales.py`, `test_finance.py`, `test_customers.py`, `test_purchasing.py`, `test_events.py`, `test_end_to_end.py`, `security/test_module_rbac.py`, `ui/test_business_pages.py` |

## 3. Files modified

`app/core/constants.py` (48 permissions, re-scoped roles, business enums, event
types, audit actions) · `app/core/application.py` (wiring for 13 repositories,
8 new services) · `app/core/exceptions.py` (ValidationError now surfaces its
specific message) · `app/core/config.py` (version 2.0.0) ·
`app/database/seed.py` (default branch seeding) · `app/database/models/__init__.py`
· `app/database/repositories/__init__.py` ·
`app/services/dashboard_service.py` (real metrics + chart series) ·
`app/services/__init__.py` · `app/ui/navigation.py` (five modules now live) ·
`app/ui/main_window.py` (page registry) · `app/ui/pages/dashboard_page.py`
(charts with data + honest badges) · `app/ui/pages/__init__.py`,
`app/ui/dialogs/__init__.py` · `tests/conftest.py` (business fixtures) ·
`tests/integration/test_database.py`, `tests/ui/test_ui_flows.py` (updated for
Phase 2 behaviour) · `README.md` · `requirements.txt` (ReportLab).

## 4. Database tables created

19 new tables (28 total including Phase 1 and `alembic_version`):

| Table | Purpose / key constraints |
| --- | --- |
| `branches` | Business location; one default branch seeded (inventory needs a location) |
| `categories` | Unique category name, active flag |
| `products` | Unique SKU, `NUMERIC(14,2)` prices, min-stock, check constraints for non-negative values |
| `inventory` | One row per (product, branch) — unique constraint; non-negative quantities |
| `stock_movements` | Append-only ledger: type, quantity, previous/new quantity, reference, user, timestamp |
| `customers` | Unique code, indexed email/phone, customer type, active flag |
| `customer_follow_ups` | Local reminders: due date, assignee, status, completed_at |
| `sales_orders` | Unique order number, statuses, payment status, Decimal totals |
| `sales_order_items` | Line with `unit_price` and `cost_price_snapshot` (historical pricing) |
| `invoices` | Unique invoice number, one per order (unique FK), status, due date |
| `payments` | Partial payments per invoice, method, reference, status |
| `expenses` | Unique expense number, category, status (RECORDED/REVERSED) |
| `financial_transactions` | Signed ledger; **unique (reference_type, reference_id, category)** prevents double posting |
| `purchase_orders` | Unique PO number, supplier FK, status |
| `purchase_order_items` | Ordered vs received quantity with `received <= ordered` check |
| `goods_receipts` | Receipt header per delivery |
| `goods_receipt_items` | Received quantity per PO line |
| `business_events` | Outbox: type, payload, status, attempts, dispatched_at |
| `suppliers` | Unique code, tax identifier, active flag |

All required relationships from the brief exist (Category→Products,
Product→Inventory/StockMovements, Customer→SalesOrders, SalesOrder→Items/Invoice,
Invoice→Payments, Supplier→PurchaseOrders, PO→Items, Product→order lines,
User→Expenses/SalesOrders/StockMovements/AuditLogs).

## 5. Database migration status

* Revision `0002_core_business`, `down_revision = 0001_initial`. Generated with
  Alembic autogenerate, then reviewed (money columns emitted as
  `sa.Numeric(14,2)`, check constraints preserved).
* **Drift check:** `compare_metadata` between the migrated database and the
  SQLAlchemy metadata returns `[]` — no differences.
* **Upgrade path verified with existing data:** a database created at
  `0001_initial`, populated with a user and a business row, was opened by the
  application and upgraded to `0002_core_business`; the legacy user and business
  row survived and all 19 new tables appeared.
* Startup applies `upgrade head` automatically; nothing is dropped or recreated.

## 6. Sales workflow verification

Executed end-to-end (`tests/integration/test_sales.py`, `test_end_to_end.py`, and
the runtime smoke run):

1. Draft order for 2 products → `subtotal 380.00`, status `DRAFT`, **no** stock
   or revenue movement.
2. Confirm → stock availability validated, status `CONFIRMED`.
3. Complete → stock deducted (10 → 8, 20 → 19), `SALE` movements written with
   before/after quantities, invoice `INV-2026-0001` created, revenue
   `380.00` posted, status `COMPLETED`, `SaleCompleted` event dispatched.
4. Partial payment `200.00` → invoice `PARTIALLY_PAID`, outstanding `180.00`,
   order `paid_amount` updated, `PaymentReceived` event.
5. Overpayment `500.00` → rejected with a specific message; outstanding unchanged.
6. Insufficient stock (999 units) → rejected; stock, invoice and revenue all
   unchanged (proved by assertions after the failure).
7. Duplicate completion → `ConflictError`; stock and revenue posted exactly once.
8. Cancellation → 4 units returned to stock (`RETURN` movement), revenue reversed
   to `0.00`, cash refund recorded, invoice `CANCELLED`, payments `REFUNDED`,
   order `CANCELLED`; second cancellation rejected.
9. Order numbers, invoice numbers and movement references are all traceable
   (`SO-2026-0001`, `INV-2026-0001`, `SALES_ORDER SO-2026-0001`).

## 7. Finance calculation verification

Verified against hand-computed expectations (2 × tea @150 with 100 cost, plus one
expense):

| Figure | Expected | Actual |
| --- | --- | --- |
| Revenue | 380.00 | 380.00 ✅ |
| COGS | 250.00 | 250.00 ✅ |
| Gross profit | 130.00 | 130.00 ✅ |
| Operating expenses | 1000.00 | 1000.00 ✅ |
| Net profit | −870.00 | −870.00 ✅ |
| Cash received (partial payment) | 200.00 | 200.00 ✅ |
| Outstanding receivables | 180.00 | 180.00 ✅ |
| After cancellation: revenue / refunds | 0.00 / 200.00 | 0.00 / 200.00 ✅ |

* Unpaid invoices never count as cash (separate assertions).
* The same invoice cannot post revenue twice — a uniqueness constraint on
  `(reference_type, reference_id, category)` plus an explicit duplicate check.
* `PURCHASE`-category expenses are excluded from operating expenses so inventory
  purchases are not double counted with COGS (dedicated test).
* Reports (income, expense, P&L, cash flow, outstanding, monthly) all build from
  real rows and carry the accounting basis text; CSV and PDF files were written
  and the PDFs verified by magic-byte check.
* Money is Decimal throughout — `0.1 + 0.2 == 0.30` and 1000 × 19.99 sums exactly
  (unit tests).

## 8. Inventory verification

* Opening stock, additions, reductions, damage and returns each write exactly one
  movement row with correct before/after quantities (16 tests).
* Stock can never go negative — attempted over-issue raises `ConflictError` and
  leaves the quantity unchanged.
* Low stock: crossing the threshold (10 → 4 with minimum 5) produces a low-stock
  alert with a suggested reorder quantity **and** a `StockBelowMinimum` event.
  Out-of-stock filter verified separately.
* Valuation = quantity × **cost** price; verified `10×100 + 20×50 = 2000.00`, and
  the dashboard reports the same figure. Selling price is never used.
* Sales deduction and purchase addition were both verified through their own
  workflows (not by direct quantity writes).

## 9. Customer management verification

* Creation with automatic `CUST-0001` codes; duplicate email and duplicate phone
  rejected (case-insensitive email).
* Purchase history, lifetime value, last purchase date and outstanding balance are
  derived from real completed orders and invoices (never stored counters).
* Segmentation rules are explicit and documented in the UI:
  high value ≥ 50,000 · new ≤ 30 days and ≤ 1 order · regular ≥ 3 orders with a
  purchase in the last 90 days · inactive = no purchase in 90 days · occasional =
  everything else. Each rule verified with a dedicated test (including time-travel
  via a backdated order for the inactive case).
* Follow-ups: create, list, overdue detection, complete, and double-completion
  rejection.
* Customer CSV export writes a real file with the segment column.

## 10. Supplier workflow verification

* Supplier registration with automatic `SUP-0001` codes and duplicate-name guard.
* Purchase order creation **does not** change stock (asserted).
* Draft → approved → ordered transitions enforced; receiving against a draft is
  rejected.
* Partial receipt (12 of 20) → `PARTIALLY_RECEIVED`, stock +12, `PURCHASE`
  movement referencing the goods receipt.
* Over-receipt (50 against 8 outstanding) rejected with a specific message.
* Two partial receipts (4 + 6) reach `RECEIVED`; supplier history reports ordered
  value 950.00 and received value 475.00 from real rows.
* Cancellation blocked once goods have been received.

## 11. RBAC verification

New permissions: `finance.export`, `sales.cancel`, `sales.export`,
`customers.deactivate`, `customers.export`, `inventory.adjust`,
`inventory.export`, `suppliers.deactivate`, and the four `purchase_orders.*`
keys (48 permissions total). System roles re-scoped and re-synced at startup.

Verified denials (service level, not just UI):

| Actor | Attempt | Result |
| --- | --- | --- |
| Employee | view finance / sales / customers / inventory / suppliers | `AuthorizationError` ✅ |
| Employee | create an expense | denied ✅ |
| Finance Manager | create a sales order | denied ✅ |
| Finance Manager | adjust stock | denied ✅ |
| Finance Manager | export customers | denied ✅ |
| Inventory Manager | approve a purchase order | denied ✅ |
| Inventory Manager | view finance | denied ✅ |
| Business Admin | receive goods | denied ✅ |
| Business Admin | create products | denied ✅ |
| Custom "Order Viewer" role | cancel an order | denied ✅ |

UI reflects the same rules: hidden navigation, disabled mutating buttons, and a
second permission check inside `MainWindow.navigate_to`.

## 12. Automated test results

Command: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. python -m pytest -q`

```
........................................................................ [ 30%]
........................................................................ [ 61%]
........................................................................ [ 91%]
....................                                                     [100%]
236 passed in 261.64s (0:04:21)
```

| Suite | Tests | Focus |
| --- | --- | --- |
| `tests/unit` | 31 | Money/Decimal exactness, Argon2id, sessions, validation |
| `tests/integration` | 130 | Database, users, inventory, sales, finance, customers, purchasing, events, end-to-end |
| `tests/security` | 48 | Authentication, RBAC, module-level denials |
| `tests/ui` | 27 | Login, wizard, navigation, business pages, empty states |
| **Total** | **236** | **all passed** |

Every test uses its own temporary database (`tests/conftest.py`); the real
workspace is never touched. Real Argon2id parameters are used (no weakened
hashing). The suite was also executed from a freshly extracted copy of the
delivered archive to confirm the package is self-contained.

Additional verification outside pytest: `compileall` over all modules, Alembic
drift check, Phase 1 → Phase 2 upgrade with existing data, real application
launch (clean log, wizard opens), and offscreen screenshots of every page.

## 13. Known issues

1. **Windows `.exe` not produced** — PyInstaller cannot cross-compile and this
   environment is Linux. The spec and build script are complete and
   static-checked (see §15).
2. **No Windows display run** — all UI verification used Qt's offscreen platform;
   fonts/DPI on a real Windows desktop are unverified.
3. **Single branch** — inventory is per (product, branch) but the UI always uses
   the seeded default branch; multi-location selection is not exposed yet.
4. **Document numbering uses max+1 within the transaction** — correct for this
   single-user desktop app; a concurrent multi-user server would need a sequence
   table with row locking.
5. **Event handlers are in-process only.** Delivery is reliable and retryable, but
   nothing external consumes events until the automation phase.
6. **Date filters convert local dates to UTC** at day boundaries; around midnight
   in a non-UTC timezone a record can fall into the neighbouring day.
7. **Supplier "payment information" is derived** from goods-receipt value; there
   is no supplier payment/credit ledger in Phase 2.
8. Charts show a single point when only one month of data exists (correct, but
   visually sparse).

Two bugs found during development were fixed and covered by tests: table sorting
recursed infinitely through `QTableWidgetItem.__lt__`, and newly created invoices
and payments were not linked to their parent objects in memory (so a
freshly-completed order reported no invoice number).

## 14. Incomplete features

| Item | Status |
| --- | --- |
| Automatic purchase orders from low-stock alerts | ⛔ Planned for the automation phase (explicitly excluded from Phase 2 by the brief) |
| Credit notes / refunds as a separate document | ⛔ Cancellation reverses everything; there is no partial credit note |
| Partial order cancellation | ⛔ Cancellation is whole-order |
| Email/SMS follow-ups | ⛔ Local reminders only (Phase 2 must work offline) |
| Cross-module scheduled reports | ⛔ Reports page is Phase 8; per-module exports work now |
| Multi-branch UI, supplier payments ledger | ⛔ Later phases |
| Windows executable | ⛔ Must be built on Windows |

## 15. Application execution instructions

```bash
python -m venv .venv
.venv\Scripts\activate                 # Windows
python -m pip install -r requirements.txt
python main.py
```

First launch shows the setup wizard. Recommended first-run sequence: create a
category and product (Inventory → Products → New product), add opening stock
(Adjust stock), add a customer, then create and complete a sales order. Data is
stored in `%LOCALAPPDATA%\BizPilotAI\bizpilot_ai.db`; exports go to `exports/`
inside the same folder.

Tests: `python -m pytest -q`

Build the executable on Windows:
`deployment\build_windows.bat` → `dist\BizPilotAI\BizPilotAI.exe`

---

## 16. Phase 2 completion checklist

| Criterion | Status |
| --- | --- |
| Finance module works | ✅ |
| Sales module works | ✅ |
| Customer module works | ✅ |
| Inventory module works | ✅ |
| Supplier module works | ✅ |
| Sales and inventory integrated | ✅ (atomic completion + movement ledger) |
| Invoice generation works | ✅ |
| Payment recording works (partial + full) | ✅ |
| Financial reports use actual data | ✅ |
| Stock movements are traceable | ✅ |
| Purchase orders and goods receipts work | ✅ |
| RBAC enforced at service level | ✅ |
| Audit logs work for all Phase 2 actions | ✅ |
| Database migrations succeed | ✅ (`0001 → 0002`, data preserved) |
| All major automated tests pass | ✅ 236/236 |
| Desktop application runs without internet | ✅ (no network calls anywhere) |
| Existing Phase 1 features remain functional | ✅ (Phase 1 tests still green) |
| Windows executable built and tested | ⛔ Pending — no Windows toolchain here |
