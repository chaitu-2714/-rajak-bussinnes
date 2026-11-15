"""Data access for product categories and products."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database.models.catalog import Category, Product
from app.database.models.inventory import StockMovement
from app.database.models.purchasing import PurchaseOrderItem
from app.database.models.sales import SalesOrderItem


class CatalogRepository:
    """Queries for the product catalogue."""

    # -- categories --------------------------------------------------------
    def list_categories(self, db: Session, *, search: str | None = None) -> list[Category]:
        stmt = select(Category).options(selectinload(Category.products))
        if search:
            pattern = f"%{search.strip().lower()}%"
            stmt = stmt.where(func.lower(Category.category_name).like(pattern))
        return list(db.scalars(stmt.order_by(Category.category_name)).unique().all())

    def get_category(self, db: Session, category_id: int) -> Category | None:
        return db.scalars(
            select(Category).options(selectinload(Category.products)).where(Category.id == category_id)
        ).first()

    def get_category_by_name(self, db: Session, name: str) -> Category | None:
        return db.scalars(
            select(Category).where(func.lower(Category.category_name) == name.strip().lower())
        ).first()

    def add_category(self, db: Session, category: Category) -> Category:
        db.add(category)
        db.flush()
        return category

    # -- products ----------------------------------------------------------
    def get_product(self, db: Session, product_id: int) -> Product | None:
        return db.scalars(
            select(Product).options(selectinload(Product.category)).where(Product.id == product_id)
        ).first()

    def get_product_by_sku(self, db: Session, sku: str) -> Product | None:
        return db.scalars(
            select(Product).where(func.lower(Product.sku) == sku.strip().lower())
        ).first()

    def list_products(
        self,
        db: Session,
        *,
        search: str | None = None,
        category_id: int | None = None,
        active_only: bool = False,
        limit: int | None = None,
    ) -> list[Product]:
        stmt = select(Product).options(selectinload(Product.category))
        if search:
            pattern = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Product.product_name).like(pattern),
                    func.lower(Product.sku).like(pattern),
                    func.lower(func.coalesce(Product.barcode, "")).like(pattern),
                )
            )
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
        if active_only:
            stmt = stmt.where(Product.is_active.is_(True))
        stmt = stmt.order_by(Product.product_name)
        if limit:
            stmt = stmt.limit(limit)
        return list(db.scalars(stmt).unique().all())

    def count_products(self, db: Session, *, active_only: bool | None = None) -> int:
        stmt = select(func.count(Product.id))
        if active_only is not None:
            stmt = stmt.where(Product.is_active.is_(active_only))
        return int(db.scalar(stmt) or 0)

    def add_product(self, db: Session, product: Product) -> Product:
        db.add(product)
        db.flush()
        return product

    def product_has_history(self, db: Session, product_id: int) -> bool:
        """True when a product already appears in any transaction ledger."""
        checks = (
            select(SalesOrderItem.id).where(SalesOrderItem.product_id == product_id).limit(1),
            select(PurchaseOrderItem.id).where(PurchaseOrderItem.product_id == product_id).limit(1),
            select(StockMovement.id).where(StockMovement.product_id == product_id).limit(1),
        )
        return any(db.scalars(check).first() is not None for check in checks)
