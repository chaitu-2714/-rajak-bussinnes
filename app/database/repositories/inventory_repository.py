"""Data access for stock levels and the movement ledger."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database.models.catalog import Product
from app.database.models.inventory import Branch, Inventory, StockMovement
from app.database.types import ZERO, to_money


class InventoryRepository:
    """Stock queries; every write happens through a movement."""

    # -- branches ----------------------------------------------------------
    def get_branch(self, db: Session, branch_id: int) -> Branch | None:
        return db.get(Branch, branch_id)

    def default_branch(self, db: Session) -> Branch | None:
        return db.scalars(
            select(Branch).where(Branch.is_default.is_(True)).order_by(Branch.id)
        ).first() or db.scalars(select(Branch).order_by(Branch.id)).first()

    def add_branch(self, db: Session, branch: Branch) -> Branch:
        db.add(branch)
        db.flush()
        return branch

    # -- stock levels ------------------------------------------------------
    def get_stock(self, db: Session, product_id: int, branch_id: int) -> Inventory | None:
        return db.scalars(
            select(Inventory).where(
                Inventory.product_id == product_id, Inventory.branch_id == branch_id
            )
        ).first()

    def get_or_create_stock(self, db: Session, product_id: int, branch_id: int) -> Inventory:
        stock = self.get_stock(db, product_id, branch_id)
        if stock is None:
            stock = Inventory(
                product_id=product_id,
                branch_id=branch_id,
                available_quantity=0,
                reserved_quantity=0,
            )
            db.add(stock)
            db.flush()
        return stock

    def list_stock(
        self,
        db: Session,
        *,
        search: str | None = None,
        category_id: int | None = None,
        branch_id: int | None = None,
        low_stock_only: bool = False,
        out_of_stock_only: bool = False,
        active_products_only: bool = True,
    ) -> list[Inventory]:
        stmt = (
            select(Inventory)
            .join(Product, Product.id == Inventory.product_id)
            .options(selectinload(Inventory.product).selectinload(Product.category))
        )
        if search:
            pattern = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Product.product_name).like(pattern),
                    func.lower(Product.sku).like(pattern),
                )
            )
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
        if branch_id is not None:
            stmt = stmt.where(Inventory.branch_id == branch_id)
        if active_products_only:
            stmt = stmt.where(Product.is_active.is_(True))
        if out_of_stock_only:
            stmt = stmt.where(Inventory.available_quantity == 0)
        elif low_stock_only:
            stmt = stmt.where(Inventory.available_quantity <= Product.minimum_stock)
        return list(db.scalars(stmt.order_by(Product.product_name)).unique().all())

    def total_quantity(self, db: Session) -> int:
        return int(db.scalar(select(func.coalesce(func.sum(Inventory.available_quantity), 0))) or 0)

    def stock_value(self, db: Session, *, branch_id: int | None = None) -> Decimal:
        """Inventory value at recorded cost (never at selling price)."""
        stmt = select(Inventory.available_quantity, Product.cost_price).join(
            Product, Product.id == Inventory.product_id
        )
        if branch_id is not None:
            stmt = stmt.where(Inventory.branch_id == branch_id)
        total = ZERO
        for quantity, cost_price in db.execute(stmt).all():
            total += to_money(cost_price) * int(quantity or 0)
        return to_money(total)

    # -- movements ---------------------------------------------------------
    def add_movement(self, db: Session, movement: StockMovement) -> StockMovement:
        db.add(movement)
        db.flush()
        return movement

    def list_movements(
        self,
        db: Session,
        *,
        product_id: int | None = None,
        movement_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 200,
    ) -> list[StockMovement]:
        stmt = select(StockMovement).options(selectinload(StockMovement.product))
        if product_id is not None:
            stmt = stmt.where(StockMovement.product_id == product_id)
        if movement_type:
            stmt = stmt.where(StockMovement.movement_type == movement_type)
        if date_from is not None:
            stmt = stmt.where(StockMovement.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(StockMovement.created_at <= date_to)
        stmt = stmt.order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).limit(limit)
        return list(db.scalars(stmt).unique().all())

    def monthly_movement_totals(self, db: Session, months: int = 6) -> list[tuple[str, int]]:
        """Net stock movement per month, newest last (for the dashboard chart)."""
        rows = db.execute(
            select(
                func.strftime("%Y-%m", StockMovement.created_at).label("month"),
                func.sum(StockMovement.new_quantity - StockMovement.previous_quantity),
            )
            .group_by("month")
            .order_by("month")
        ).all()
        return [(str(month), int(total or 0)) for month, total in rows][-months:]
