# Changelog

All notable changes to BizPilot AI. Release versions follow semantic versioning;
the phase numbers in the development reports describe build history, not versions.

## [1.0.0] — 2026-11-05

First stable release. Database schema `0009_security`.

### Added
* Business modules: finance, sales, customers, inventory, suppliers, purchase orders.
* Central AI orchestrator with a 48-tool registry, intent classification and plans.
* Five specialised agents (finance, sales, customer, inventory, business intelligence).
* Multi-agent collaboration with dependency graphs, conflict resolution and unified decisions.
* Autonomous workflow engine with six workflows, approval gates and an audit trail.
* Business intelligence: analytics, KPIs, anomaly detection, forecasts, risk, simulation.
* Hybrid AI and RAG: document ingestion, embeddings, local vector search, grounded answers.
* Enterprise security: TOTP MFA, centralised authorization, AI governance, audit hash chain.
* Release engineering: PyInstaller spec, build and validation scripts, Inno Setup installer,
  performance benchmarks and ten end-to-end acceptance tests.

### Fixed during release hardening
* Knowledge chunks dropped their section heading, so questions phrased around a document
  title ("the supplier's payment conditions") returned no evidence.
* Validating a knowledge backup tried to open the zip archive as a database.
* The audit and reports navigation entries were placeholders.

### Known limitations
See `docs/RELEASE_NOTES.md` and `docs/SECURITY_GUIDE.md`.
