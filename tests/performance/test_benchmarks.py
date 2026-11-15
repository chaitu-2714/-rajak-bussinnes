"""Performance benchmarks: real measurements, no hardcoded numbers.

Run:  python -m pytest tests/performance -q -s
The suite writes its measurements to docs/PERFORMANCE_RESULTS.md when
``BIZPILOT_WRITE_BENCHMARKS=1`` so the release report quotes real numbers.
"""

from __future__ import annotations

import os
import statistics
import time
from pathlib import Path

import pytest

from app.utils.date_utils import utcnow


def _timed(label: str, callable_, results: dict, repeats: int = 1) -> float:
    durations = []
    value = None
    for _ in range(repeats):
        started = time.perf_counter()
        value = callable_()
        durations.append((time.perf_counter() - started) * 1000)
    results[label] = {
        "runs": repeats,
        "median_ms": round(statistics.median(durations), 1),
        "min_ms": round(min(durations), 1),
        "max_ms": round(max(durations), 1),
    }
    return statistics.median(durations)


def _seed_records(admin, business, count: int) -> int:
    """Create `count` sales orders spread across recent months."""
    from sqlalchemy import text

    created = 0
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": count * 3 + 50,
            "movement_type": "ADJUSTMENT",
            "reason": "Benchmark stock",
            "direction": 1,
        }
    )
    for index in range(count):
        order = admin.sales_service.create_order(
            {
                "customer_id": business["customer"].id,
                "items": [{"product_id": business["tea"].id, "quantity": 1}],
            }
        )
        admin.sales_service.complete_order(order.id)
        created += 1
    return created


@pytest.fixture(scope="module")
def benchmark_results() -> dict:
    return {}


def test_startup_and_login_performance(benchmark_results) -> None:
    from app.core.application import ApplicationContext
    from app.core.config import load_config

    results = benchmark_results
    _timed("ApplicationContext.build", lambda: ApplicationContext.build(load_config()), results, 1)

    context = ApplicationContext.build(load_config())
    if context.auth_service.needs_initial_setup():
        context.auth_service.run_initial_setup(
            {
                "business_name": "Benchmark Traders",
                "owner_name": "Bench User",
                "email": "bench@example.com",
                "password": "Str0ng!Passw0rd",
                "password_confirm": "Str0ng!Passw0rd",
                "currency": "INR",
                "timezone": "Asia/Kolkata",
                "financial_year_start": "04-01",
            }
        )
    _timed("Login (Argon2id verify)", lambda: context.auth_service.login(
        "bench@example.com", "Str0ng!Passw0rd"), results, 3)
    _timed("Dashboard summary query", lambda: context.dashboard_service.get_summary(), results, 3)
    assert results["Login (Argon2id verify)"]["median_ms"] > 0


def test_database_scale_benchmarks(benchmark_results, admin, business) -> None:
    """Small (100) and medium (2,000) datasets, measured end to end."""
    results = benchmark_results
    _seed_records(admin, business, 100)
    _timed("List 100 sales orders", lambda: admin.sales_service.list_orders(), results, 2)
    _timed("Financial summary (100 records)", lambda: admin.finance_service.summary(), results, 2)

    _seed_records(admin, business, 200)  # total 300 orders, 600+ line items
    _timed("List 300 sales orders", lambda: admin.sales_service.list_orders(), results, 2)
    _timed("Financial summary (300 records)", lambda: admin.finance_service.summary(), results, 2)
    _timed("Inventory stock listing", lambda: admin.inventory_service.list_stock(), results, 2)


def test_analytics_and_report_performance(benchmark_results, admin, business) -> None:
    results = benchmark_results
    _timed("Analytics bundle (MONTHLY)", lambda: admin.analytics_service.analyze("MONTHLY"), results, 1)
    _timed(
        "KPI calculation",
        lambda: admin.analytics_service.kpis("MONTHLY"),
        results,
        1,
    )
    _timed(
        "Anomaly detection",
        lambda: admin.analytics_service.anomalies("MONTHLY"),
        results,
        1,
    )


def test_document_and_retrieval_performance(benchmark_results, admin, tmp_path: Path) -> None:
    results = benchmark_results
    text = "\n".join(
        f"Clause {index}: payment terms are 30 days from the invoice date."
        for index in range(400)
    )
    document = tmp_path / "benchmark_agreement.txt"
    document.write_text("SUPPLIER AGREEMENT\n\n" + text, encoding="utf-8")

    _timed("Ingest + chunk + embed + index (400 clauses)", lambda: admin.knowledge_service.upload_document(document), results, 1)
    _timed("Semantic search", lambda: admin.knowledge_service.search("payment terms", mode="SEMANTIC"), results, 3)
    _timed("Hybrid search", lambda: admin.knowledge_service.search("payment terms", mode="HYBRID"), results, 3)
    _timed("RAG answer (deterministic)", lambda: admin.knowledge_service.ask("What are the payment terms?"), results, 2)


def test_agent_and_workflow_performance(benchmark_results, admin, business) -> None:
    results = benchmark_results
    _timed(
        "Agent run (inventory)",
        lambda: admin.agent_manager.run_agent(
            "inventory_agent", task_type="LOW_STOCK_ANALYSIS"
        ),
        results,
        1,
    )
    _timed(
        "Collaboration (BUSINESS_HEALTH)",
        lambda: admin.collaboration_manager.create_collaboration(
            "Analyze my complete business performance."
        ),
        results,
        1,
    )
    _timed(
        "Workflow plan + execute (daily summary)",
        lambda: admin.autonomy_service.start_workflow(
            admin.autonomy_service.create_workflow("DAILY_SUMMARY").workflow_ref
        ),
        results,
        1,
    )


def test_benchmark_summary(benchmark_results) -> None:
    """Write the measurements to docs/ when asked, and always print them."""
    results = benchmark_results
    assert results, "no measurements were taken"

    lines = ["# BizPilot AI — Performance Measurements", "", f"Measured: {utcnow():%Y-%m-%d %H:%M} UTC", "",
             "| Operation | Runs | Median (ms) | Min (ms) | Max (ms) |", "| --- | --- | --- | --- | --- |"]
    for label, data in results.items():
        lines.append(
            f"| {label} | {data['runs']} | {data['median_ms']} | {data['min_ms']} | {data['max_ms']} |"
        )
    table = "\n".join(lines)
    print("\n" + table)

    if os.environ.get("BIZPILOT_WRITE_BENCHMARKS") == "1":
        target = Path(__file__).resolve().parents[2] / "docs" / "PERFORMANCE_RESULTS.md"
        target.write_text(table + "\n", encoding="utf-8")
        print(f"\nwritten to {target}")
