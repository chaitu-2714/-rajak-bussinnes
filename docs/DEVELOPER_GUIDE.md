# BizPilot AI — Developer Guide

## Architecture

```
main.py → AppController → MainWindow (PySide6)
                    ↘ ApplicationContext (composition root)
                        ├── Database (SQLite + Alembic)
                        ├── Services (finance, sales, inventory, customers, purchasing,
                        │            analytics, knowledge, autonomy, security)
                        ├── AI layer (orchestrator, tool registry, 5 agents,
                        │            collaboration manager, RAG pipeline)
                        └── Security layer (authorization, MFA, governance, audit chain)
```

Everything is wired in `app/core/application.py`. Services take a session factory and
an auth context, and every public method calls `self._authorize(db, "<permission>")`
before touching data. UI pages never query the database directly.

## Folder map

| Path | Contents |
| --- | --- |
| `app/core` | config, database, constants, exceptions, logging |
| `app/database` | models, repositories, base, migration runner |
| `app/services` | business logic and the RBAC boundary |
| `app/security` | authorization, MFA, governance, audit integrity, monitoring, backup |
| `app/ai` | orchestrator, registry (48 tools), agents, collaboration, autonomy |
| `app/analytics` | analytics, forecasting, anomaly, risk, simulation, KPI, reports |
| `app/document_intelligence`, `app/embeddings`, `app/vector_store`, `app/rag` | Phase 8 |
| `app/ui` | pages, components, theme, workers |
| `migrations/versions` | nine Alembic revisions |
| `deployment`, `installer`, `scripts`, `release` | packaging and operations |

## Database

SQLAlchemy 2 models with explicit FKs and indexes. Nine migrations, head
`0009_security`, 92 tables. Never edit a shipped migration: add a new revision.

```bash
python scripts/migrate_database.py --check     # current vs head
python scripts/migrate_database.py --backup    # back up, then migrate
```

## AI architecture

`ModelRouter` (Phase 3) selects a provider; `HybridAIModelRouter` adds policies, task
routing and usage records. `ToolRegistry` exposes 48 permission-checked tools. Agents
receive a `ToolRunner` that enforces both the user's permissions and the agent's own
security policy. `RagPipeline` retrieves, gates evidence, builds context and validates
grounding before answering.

## Workflow engine

`AutonomousWorkflowEngine` plans a task graph, executes waves, pauses at approval
gates, verifies the resulting business record and audits every transition. Business
effects only happen through the allowlisted action registry.

## Testing

```bash
python scripts/run_tests.py                    # every suite in order
python -m pytest tests/unit -q                 # 199 tests
python -m pytest tests/security -q             # 150 tests
python -m pytest tests/integration -q          # 278 tests
python -m pytest tests/ui -q                   # 80 tests
python -m pytest tests/end_to_end -q           # 10 acceptance scenarios
python -m pytest tests/performance -q -s       # benchmarks (real measurements)
```

Fixtures live in `tests/conftest.py`; each test gets a temporary database.

## Packaging

```bash
python deployment/build_windows.py             # tests, PyInstaller, manifest
python deployment/validate_release.py          # release gate
python deployment/clean_build.py               # remove build output
iscc installer\bizpilot_installer.iss          # installer (Windows)
```

PyInstaller cannot cross-compile: build the Windows artifacts on Windows.

## Conventions

* Money is `Decimal` everywhere; never float.
* Timestamps are naive UTC in the database, rendered in local time.
* No business logic in the UI; no SQL outside repositories.
* A new permission must be added to `PERMISSION_KEYS`, a role, and the relevant service.
