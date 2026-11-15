"""What-if simulation. Reads real baselines; never writes business records."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.analytics.schemas import (
    CustomerAnalytics,
    FinancialAnalytics,
    InventoryAnalytics,
    SalesAnalytics,
    SimulationLine,
    SimulationOutcome,
    money,
)

ZERO = Decimal("0.00")
HYPOTHETICAL = "HYPOTHETICAL SCENARIO — NOT AN ACTUAL BUSINESS RESULT"

DEFAULT_MONTHLY_SALARY = Decimal("25000.00")


class BusinessSimulationEngine:
    """Simulates a decision against a real baseline and states every assumption."""

    def simulate(
        self,
        scenario: str,
        *,
        parameters: dict | None = None,
        financial: FinancialAnalytics,
        sales: SalesAnalytics,
        inventory: InventoryAnalytics | None = None,
        customers: CustomerAnalytics | None = None,
    ) -> SimulationOutcome:
        scenario = (scenario or "").upper()
        parameters = parameters or {}
        handler = {
            "PRICE_INCREASE": self._price_increase,
            "SALES_DECLINE": self._sales_decline,
            "SUPPLIER_PRICE_INCREASE": self._supplier_price_increase,
            "HIRE_EMPLOYEES": self._hire_employees,
            "PURCHASE_UNITS": self._purchase_units,
        }.get(scenario)
        if handler is None:
            raise ValueError(
                f"Unknown scenario '{scenario}'. Supported: PRICE_INCREASE, SALES_DECLINE, "
                "SUPPLIER_PRICE_INCREASE, HIRE_EMPLOYEES, PURCHASE_UNITS"
            )
        outcome = handler(parameters, financial, sales, inventory)
        outcome.simulation_ref = f"sim-{uuid.uuid4().hex[:12]}"
        outcome.label = HYPOTHETICAL
        return outcome

    # -- scenarios ---------------------------------------------------------
    def _price_increase(self, parameters: dict, financial, sales, inventory) -> SimulationOutcome:
        pct = Decimal(str(parameters.get("percent", 5)))
        revenue = financial.revenue
        new_revenue = money(revenue * (1 + pct / 100))
        # Gross profit change: the same cost base, higher selling prices.
        profit_before = financial.gross_profit
        profit_after = money(new_revenue - financial.cogs)
        return SimulationOutcome(
            scenario_type="PRICE_INCREASE",
            parameters={"percent": str(pct)},
            lines=[
                self._line("Revenue", revenue, new_revenue),
                self._line("Gross profit", profit_before, profit_after),
                self._line("Cash received", financial.cash_received, financial.cash_received),
            ],
            assumptions=[
                f"Selling prices rise by {pct}% across all products.",
                "Demand is assumed to stay constant — this is an assumption, not a forecast. "
                "Higher prices usually reduce volume, so real revenue will likely be lower "
                "than shown.",
                "Cost prices and expenses are unchanged.",
            ],
            limitations=[
                "No price elasticity is modelled: the workspace has no data on how customers "
                "respond to price changes.",
                "Discounts and taxes are held at their current effective rates.",
            ],
            narrative=(
                f"A {pct}% price increase on {revenue:,.2f} of revenue would add "
                f"{money(new_revenue - revenue):,.2f} if every customer still bought the same "
                "quantity."
            ),
        )

    def _sales_decline(self, parameters: dict, financial, sales, inventory) -> SimulationOutcome:
        pct = Decimal(str(parameters.get("percent", 10)))
        revenue = financial.revenue
        new_revenue = money(revenue * (1 - pct / 100))
        gross_before = financial.gross_profit
        margin = (
            (financial.gross_profit / revenue) if revenue > ZERO else ZERO
        )
        gross_after = money(new_revenue * margin)
        net_before = financial.net_profit
        expenses = financial.operating_expenses
        net_after = money(gross_after - expenses) if net_before is not None else None
        lines = [
            self._line("Revenue", revenue, new_revenue),
            self._line("Gross profit", gross_before, gross_after),
            self._line("Cash received", financial.cash_received, money(financial.cash_received * (1 - pct / 100))),
        ]
        if net_after is not None:
            lines.append(self._line("Net profit", net_before, net_after))
        return SimulationOutcome(
            scenario_type="SALES_DECLINE",
            parameters={"percent": str(pct)},
            lines=lines,
            assumptions=[
                f"Sales fall by {pct}% with the same product mix and gross margin.",
                "Operating expenses do not change — most costs are assumed fixed.",
            ],
            limitations=[
                "Variable costs tied to volume are not reduced in this simulation.",
                "Cash impact assumes collections fall in the same proportion as sales.",
            ],
            narrative=(
                f"A {pct}% sales decline would remove {money(revenue - new_revenue):,.2f} of "
                f"revenue and {money(gross_before - gross_after):,.2f} of gross profit"
                + (
                    f", turning net profit into {net_after:,.2f}."
                    if net_after is not None
                    else "."
                )
            ),
        )

    def _supplier_price_increase(self, parameters: dict, financial, sales, inventory) -> SimulationOutcome:
        pct = Decimal(str(parameters.get("percent", 8)))
        cogs = financial.cogs
        new_cogs = money(cogs * (1 + pct / 100))
        gross_before = financial.gross_profit
        gross_after = money(financial.revenue - new_cogs)
        net_before = financial.net_profit
        net_after = (
            money(gross_after - financial.operating_expenses) if net_before is not None else None
        )
        lines = [
            self._line("Cost of goods sold", cogs, new_cogs),
            self._line("Gross profit", gross_before, gross_after),
        ]
        if net_after is not None:
            lines.append(self._line("Net profit", net_before, net_after))
        return SimulationOutcome(
            scenario_type="SUPPLIER_PRICE_INCREASE",
            parameters={"percent": str(pct)},
            lines=lines,
            assumptions=[
                f"Purchase prices rise by {pct}% and are fully reflected in cost of goods sold.",
                "Selling prices are unchanged, so the margin absorbs the increase.",
            ],
            limitations=[
                "Existing stock bought at the old price is not revalued.",
                "Cost of goods sold uses recorded product cost prices.",
            ],
            narrative=(
                f"An {pct}% supplier price increase would raise cost of goods sold by "
                f"{money(new_cogs - cogs):,.2f} and reduce gross profit by "
                f"{money(gross_before - gross_after):,.2f}."
            ),
        )

    def _hire_employees(self, parameters: dict, financial, sales, inventory) -> SimulationOutcome:
        count = int(parameters.get("count", 1))
        salary = Decimal(str(parameters.get("monthly_salary", DEFAULT_MONTHLY_SALARY)))
        added = money(salary * count)
        expenses_before = financial.operating_expenses
        expenses_after = money(expenses_before + added)
        net_before = financial.net_profit
        net_after = (
            money(net_before - added) if net_before is not None else None
        )
        lines = [self._line("Operating expenses", expenses_before, expenses_after)]
        if net_after is not None:
            lines.append(self._line("Net profit", net_before, net_after))
        return SimulationOutcome(
            scenario_type="HIRE_EMPLOYEES",
            parameters={"count": count, "monthly_salary": str(salary)},
            lines=lines,
            assumptions=[
                f"{count} additional employee(s) at {salary:,.2f} per month.",
                "No additional revenue is assumed from the new hires.",
            ],
            limitations=[
                "Employer contributions, benefits and one-off hiring costs are not included.",
                "Productivity gains are not modelled.",
            ],
            narrative=(
                f"Hiring {count} employee(s) would add {added:,.2f} of monthly expense"
                + (f" and reduce net profit to {net_after:,.2f}." if net_after is not None else ".")
            ),
        )

    def _purchase_units(self, parameters: dict, financial, sales, inventory) -> SimulationOutcome:
        units = int(parameters.get("units", 100))
        unit_cost = Decimal(str(parameters.get("unit_cost", 0)))
        if unit_cost <= ZERO and inventory is not None:
            unit_cost = self._average_unit_cost(inventory)
        spend = money(unit_cost * units)
        cash_after = money(financial.cash_received - financial.cash_paid_out - spend)
        stock_value_before = inventory.inventory_value if inventory else ZERO
        stock_value_after = money(stock_value_before + spend)
        lines = [
            SimulationLine(metric="Purchase spend", baseline=ZERO, simulated=spend, delta=spend, unit="₹"),
            SimulationLine(
                metric="Inventory value",
                baseline=stock_value_before,
                simulated=stock_value_after,
                delta=money(stock_value_after - stock_value_before),
                unit="₹",
            ),
            SimulationLine(
                metric="Net cash after purchase",
                baseline=financial.net_cash_flow,
                simulated=cash_after,
                delta=money(cash_after - financial.net_cash_flow),
                unit="₹",
            ),
        ]
        return SimulationOutcome(
            scenario_type="PURCHASE_UNITS",
            parameters={"units": units, "unit_cost": str(unit_cost)},
            lines=lines,
            assumptions=[
                f"{units} unit(s) are bought at {unit_cost:,.2f} each.",
                "The purchase is paid in cash in the same period.",
                "No sales of the new stock are assumed.",
            ],
            limitations=[
                "Storage costs and obsolescence are not modelled.",
                "A purchase is not an expense: it converts cash into inventory.",
            ],
            narrative=(
                f"Buying {units} unit(s) would use {spend:,.2f} of cash and raise inventory "
                f"value to {stock_value_after:,.2f}."
            ),
        )

    # -- helpers -----------------------------------------------------------
    def _line(self, metric: str, baseline: Decimal, simulated: Decimal) -> SimulationLine:
        delta = money(simulated - baseline)
        percent = (
            (delta / baseline * 100).quantize(Decimal("0.01")) if baseline > ZERO else None
        )
        return SimulationLine(
            metric=metric,
            baseline=money(baseline),
            simulated=money(simulated),
            delta=delta,
            delta_percent=percent,
            unit="₹",
        )

    def _average_unit_cost(self, inventory: InventoryAnalytics) -> Decimal:
        if not inventory.demand:
            return ZERO
        return ZERO
