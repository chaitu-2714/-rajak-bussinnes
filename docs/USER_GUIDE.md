# BizPilot AI — User Guide

## 1. First launch

1. Start **BizPilot AI** from the Start Menu.
2. The setup wizard asks for your business name, owner name, email, currency,
   timezone and financial-year start.
3. Choose a password for the Super Admin account. It must be at least 10 characters
   with upper case, lower case, a digit and a symbol. There are no default accounts.
4. The database is created and migrated automatically. Setup runs once — restarting
   the application takes you to the sign-in screen, not back to the wizard.

## 2. Signing in

Enter your email and password. Five failed attempts lock the account for a period;
the Security Center shows who is locked. If your administrator enabled MFA, you are
asked for the six-digit code from your authenticator app (or a recovery code).

## 3. Daily work

**Dashboard** — revenue, expenses, cash, sales, outstanding payments and stock at a
glance, plus the state of AI agents, workflows, documents and security alerts.

**Finance** — record expenses, review transactions and export reports. An unpaid
invoice is never counted as cash.

**Sales** — create customers and products, raise orders, issue invoices and record
full or partial payments. Stock leaves inventory when an order completes.

**Inventory** — products, categories, opening stock and adjustments. Stock only rises
when goods are received against a purchase order.

**Suppliers** — supplier records, purchase orders and goods receipts.

## 4. Asking the AI

The **AI Command Center** accepts plain questions: "show this month's revenue",
"which products are low on stock", "analyse my complete business performance".
Answers come from registered tools over your real data, not from the model's memory.
If Ollama is not installed, you see that the deterministic engine answered.

## 5. Agents and collaboration

**AI Agents** runs one specialist at a time and shows its findings.
**Collaboration Center** runs several agents together on one objective, shows the
task graph, the messages between agents and the single unified decision.

## 6. Autonomous operations

**Operations Center** lists workflows. A workflow analyses, prepares a recommendation
and then stops at an approval gate when money or stock would change. Approve it in the
same screen; nothing is executed until you do. Rejecting leaves everything untouched.

## 7. Business intelligence

**Business Intelligence** shows KPIs, financial and sales trends, customer segments,
inventory health, supplier performance, detected anomalies, forecasts, risk scores and
what-if simulations. Forecasts state their method and validation error; simulations are
labelled hypothetical and never change a record.

## 8. Documents

**Knowledge Center** accepts PDF, DOCX, XLSX, PPTX, CSV, TXT, Markdown and images.
Upload a contract or policy, then ask questions about it. Answers cite the document and
page. If the documents do not contain the answer, the assistant says so.

## 9. Security and backups

**Security Center** shows failed logins, sessions, MFA status, AI governance, the audit
chain and backups. **Security → Backup** creates a verified backup; a restore is refused
unless the backup passes validation, and a safety copy of current data is taken first.

## 10. Getting help

Logs live in `%LOCALAPPDATA%\BizPilotAI\logs`. When reporting a problem, include the
time, what you were doing and the log file — never your password.
