# BizPilot AI — Performance Measurements

Measured: 2026-11-05 04:17 UTC

| Operation | Runs | Median (ms) | Min (ms) | Max (ms) |
| --- | --- | --- | --- | --- |
| ApplicationContext.build | 1 | 565.9 | 565.9 | 565.9 |
| Login (Argon2id verify) | 3 | 373.1 | 328.9 | 391.3 |
| Dashboard summary query | 3 | 22.2 | 17.9 | 100.1 |
| List 100 sales orders | 2 | 91.7 | 28.4 | 155.0 |
| Financial summary (100 records) | 2 | 21.2 | 14.8 | 27.5 |
| List 300 sales orders | 2 | 72.8 | 72.3 | 73.4 |
| Financial summary (300 records) | 2 | 27.2 | 26.5 | 28.0 |
| Inventory stock listing | 2 | 10.7 | 6.7 | 14.7 |
| Analytics bundle (MONTHLY) | 1 | 168.0 | 168.0 | 168.0 |
| KPI calculation | 1 | 99.3 | 99.3 | 99.3 |
| Anomaly detection | 1 | 60.3 | 60.3 | 60.3 |
| Ingest + chunk + embed + index (400 clauses) | 1 | 179.5 | 179.5 | 179.5 |
| Semantic search | 3 | 14.1 | 13.0 | 19.3 |
| Hybrid search | 3 | 24.0 | 18.7 | 28.8 |
| RAG answer (deterministic) | 2 | 485.9 | 218.2 | 753.7 |
| Agent run (inventory) | 1 | 34.1 | 34.1 | 34.1 |
| Collaboration (BUSINESS_HEALTH) | 1 | 31.3 | 31.3 | 31.3 |
| Workflow plan + execute (daily summary) | 1 | 797.6 | 797.6 | 797.6 |
