"""Phase 2: core business management tables

Revision ID: 0002_core_business
Revises: 0001_initial
Create Date: 2026-11-04 02:13:01.653818

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0002_core_business'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('branches',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('branch_name', sa.String(length=120), nullable=False),
    sa.Column('is_default', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_branches')),
    sa.UniqueConstraint('branch_name', name=op.f('uq_branches_branch_name'))
    )
    op.create_table('business_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('event_type', sa.String(length=60), nullable=False),
    sa.Column('aggregate_type', sa.String(length=60), nullable=True),
    sa.Column('aggregate_id', sa.String(length=60), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('dispatched_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_business_events'))
    )
    with op.batch_alter_table('business_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_business_events_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_business_events_event_type'), ['event_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_business_events_status'), ['status'], unique=False)

    op.create_table('categories',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('category_name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('length(trim(category_name)) > 0', name=op.f('ck_categories_category_name_not_blank')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories'))
    )
    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_categories_category_name'), ['category_name'], unique=True)

    op.create_table('customers',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('customer_code', sa.String(length=30), nullable=False),
    sa.Column('full_name', sa.String(length=160), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('city', sa.String(length=80), nullable=True),
    sa.Column('customer_type', sa.String(length=20), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customers'))
    )
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_customers_city'), ['city'], unique=False)
        batch_op.create_index(batch_op.f('ix_customers_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_customers_customer_code'), ['customer_code'], unique=True)
        batch_op.create_index(batch_op.f('ix_customers_email'), ['email'], unique=False)
        batch_op.create_index(batch_op.f('ix_customers_full_name'), ['full_name'], unique=False)
        batch_op.create_index(batch_op.f('ix_customers_phone'), ['phone'], unique=False)

    op.create_table('suppliers',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('supplier_code', sa.String(length=30), nullable=False),
    sa.Column('supplier_name', sa.String(length=160), nullable=False),
    sa.Column('contact_person', sa.String(length=120), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('tax_identifier', sa.String(length=40), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_suppliers'))
    )
    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_suppliers_email'), ['email'], unique=False)
        batch_op.create_index(batch_op.f('ix_suppliers_supplier_code'), ['supplier_code'], unique=True)
        batch_op.create_index(batch_op.f('ix_suppliers_supplier_name'), ['supplier_name'], unique=False)

    op.create_table('customer_follow_ups',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('customer_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('due_date', sa.DateTime(), nullable=False),
    sa.Column('assigned_to', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], name=op.f('fk_customer_follow_ups_assigned_to_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_customer_follow_ups_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_customer_follow_ups_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_follow_ups'))
    )
    with op.batch_alter_table('customer_follow_ups', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_customer_follow_ups_assigned_to'), ['assigned_to'], unique=False)
        batch_op.create_index(batch_op.f('ix_customer_follow_ups_customer_id'), ['customer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_customer_follow_ups_due_date'), ['due_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_customer_follow_ups_status'), ['status'], unique=False)

    op.create_table('expenses',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('expense_number', sa.String(length=30), nullable=False),
    sa.Column('expense_category', sa.String(length=30), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('vendor_name', sa.String(length=160), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('payment_method', sa.String(length=20), nullable=False),
    sa.Column('expense_date', sa.DateTime(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('amount > 0', name=op.f('ck_expenses_expense_amount_positive')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_expenses_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_expenses'))
    )
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_expenses_expense_category'), ['expense_category'], unique=False)
        batch_op.create_index(batch_op.f('ix_expenses_expense_date'), ['expense_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_expenses_expense_number'), ['expense_number'], unique=True)
        batch_op.create_index(batch_op.f('ix_expenses_status'), ['status'], unique=False)

    op.create_table('financial_transactions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('transaction_number', sa.String(length=30), nullable=False),
    sa.Column('transaction_type', sa.String(length=20), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('reference_type', sa.String(length=40), nullable=False),
    sa.Column('reference_id', sa.String(length=40), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('transaction_date', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_financial_transactions_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_financial_transactions')),
    sa.UniqueConstraint('reference_type', 'reference_id', 'category', name='uq_financial_transactions_reference_category')
    )
    with op.batch_alter_table('financial_transactions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_financial_transactions_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_transactions_reference_id'), ['reference_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_transactions_reference_type'), ['reference_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_transactions_transaction_date'), ['transaction_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_financial_transactions_transaction_number'), ['transaction_number'], unique=True)
        batch_op.create_index(batch_op.f('ix_financial_transactions_transaction_type'), ['transaction_type'], unique=False)

    op.create_table('products',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('sku', sa.String(length=40), nullable=False),
    sa.Column('product_name', sa.String(length=160), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('unit', sa.String(length=16), nullable=False),
    sa.Column('cost_price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('selling_price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('minimum_stock', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('barcode', sa.String(length=64), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('cost_price >= 0', name=op.f('ck_products_cost_price_non_negative')),
    sa.CheckConstraint('minimum_stock >= 0', name=op.f('ck_products_minimum_stock_non_negative')),
    sa.CheckConstraint('selling_price >= 0', name=op.f('ck_products_selling_price_non_negative')),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_products_category_id_categories'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_products'))
    )
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_products_barcode'), ['barcode'], unique=False)
        batch_op.create_index(batch_op.f('ix_products_category_id'), ['category_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_products_product_name'), ['product_name'], unique=False)
        batch_op.create_index(batch_op.f('ix_products_sku'), ['sku'], unique=True)

    op.create_table('purchase_orders',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('purchase_order_number', sa.String(length=30), nullable=False),
    sa.Column('supplier_id', sa.Integer(), nullable=False),
    sa.Column('subtotal', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('tax_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('total_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('expected_delivery_date', sa.DateTime(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('total_amount >= 0', name=op.f('ck_purchase_orders_po_total_non_negative')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_purchase_orders_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], name=op.f('fk_purchase_orders_supplier_id_suppliers'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_purchase_orders'))
    )
    with op.batch_alter_table('purchase_orders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_purchase_orders_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_purchase_orders_purchase_order_number'), ['purchase_order_number'], unique=True)
        batch_op.create_index(batch_op.f('ix_purchase_orders_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_purchase_orders_supplier_id'), ['supplier_id'], unique=False)

    op.create_table('sales_orders',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('order_number', sa.String(length=30), nullable=False),
    sa.Column('customer_id', sa.Integer(), nullable=False),
    sa.Column('subtotal', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('discount_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('tax_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('total_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('paid_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('payment_status', sa.String(length=20), nullable=False),
    sa.Column('order_status', sa.String(length=20), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('paid_amount >= 0', name=op.f('ck_sales_orders_paid_amount_non_negative')),
    sa.CheckConstraint('total_amount >= 0', name=op.f('ck_sales_orders_total_amount_non_negative')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_sales_orders_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_sales_orders_customer_id_customers'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sales_orders'))
    )
    with op.batch_alter_table('sales_orders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sales_orders_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_sales_orders_customer_id'), ['customer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_sales_orders_order_number'), ['order_number'], unique=True)
        batch_op.create_index(batch_op.f('ix_sales_orders_order_status'), ['order_status'], unique=False)
        batch_op.create_index(batch_op.f('ix_sales_orders_payment_status'), ['payment_status'], unique=False)

    op.create_table('goods_receipts',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('receipt_number', sa.String(length=30), nullable=False),
    sa.Column('purchase_order_id', sa.Integer(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('received_by', sa.Integer(), nullable=True),
    sa.Column('received_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['purchase_order_id'], ['purchase_orders.id'], name=op.f('fk_goods_receipts_purchase_order_id_purchase_orders'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['received_by'], ['users.id'], name=op.f('fk_goods_receipts_received_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_goods_receipts'))
    )
    with op.batch_alter_table('goods_receipts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_goods_receipts_purchase_order_id'), ['purchase_order_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_goods_receipts_receipt_number'), ['receipt_number'], unique=True)
        batch_op.create_index(batch_op.f('ix_goods_receipts_received_at'), ['received_at'], unique=False)

    op.create_table('inventory',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('branch_id', sa.Integer(), nullable=False),
    sa.Column('available_quantity', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('reserved_quantity', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('available_quantity >= 0', name=op.f('ck_inventory_available_quantity_non_negative')),
    sa.CheckConstraint('reserved_quantity >= 0', name=op.f('ck_inventory_reserved_quantity_non_negative')),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], name=op.f('fk_inventory_branch_id_branches'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_inventory_product_id_products'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory')),
    sa.UniqueConstraint('product_id', 'branch_id', name='uq_inventory_product_id_branch_id')
    )
    with op.batch_alter_table('inventory', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_inventory_branch_id'), ['branch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_inventory_product_id'), ['product_id'], unique=False)

    op.create_table('invoices',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('invoice_number', sa.String(length=30), nullable=False),
    sa.Column('sales_order_id', sa.Integer(), nullable=False),
    sa.Column('customer_id', sa.Integer(), nullable=False),
    sa.Column('invoice_date', sa.DateTime(), nullable=False),
    sa.Column('due_date', sa.DateTime(), nullable=True),
    sa.Column('subtotal', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('discount_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('tax_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('total_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('total_amount >= 0', name=op.f('ck_invoices_invoice_total_non_negative')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_invoices_customer_id_customers'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], name=op.f('fk_invoices_sales_order_id_sales_orders'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invoices')),
    sa.UniqueConstraint('sales_order_id', name=op.f('uq_invoices_sales_order_id'))
    )
    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_invoices_customer_id'), ['customer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_invoices_invoice_number'), ['invoice_number'], unique=True)
        batch_op.create_index(batch_op.f('ix_invoices_status'), ['status'], unique=False)

    op.create_table('purchase_order_items',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('purchase_order_id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('ordered_quantity', sa.Integer(), nullable=False),
    sa.Column('received_quantity', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('unit_cost', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('line_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.CheckConstraint('ordered_quantity > 0', name=op.f('ck_purchase_order_items_po_item_quantity_positive')),
    sa.CheckConstraint('received_quantity <= ordered_quantity', name=op.f('ck_purchase_order_items_po_item_received_within_ordered')),
    sa.CheckConstraint('received_quantity >= 0', name=op.f('ck_purchase_order_items_po_item_received_non_negative')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_purchase_order_items_product_id_products'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['purchase_order_id'], ['purchase_orders.id'], name=op.f('fk_purchase_order_items_purchase_order_id_purchase_orders'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_purchase_order_items'))
    )
    with op.batch_alter_table('purchase_order_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_purchase_order_items_product_id'), ['product_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_purchase_order_items_purchase_order_id'), ['purchase_order_id'], unique=False)

    op.create_table('sales_order_items',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('sales_order_id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('cost_price_snapshot', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('discount_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('tax_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('line_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.CheckConstraint('line_total >= 0', name=op.f('ck_sales_order_items_line_total_non_negative')),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_sales_order_items_quantity_positive')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_sales_order_items_product_id_products'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], name=op.f('fk_sales_order_items_sales_order_id_sales_orders'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sales_order_items'))
    )
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sales_order_items_product_id'), ['product_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_sales_order_items_sales_order_id'), ['sales_order_id'], unique=False)

    op.create_table('stock_movements',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('branch_id', sa.Integer(), nullable=False),
    sa.Column('movement_type', sa.String(length=20), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('previous_quantity', sa.Integer(), nullable=False),
    sa.Column('new_quantity', sa.Integer(), nullable=False),
    sa.Column('reference_type', sa.String(length=40), nullable=True),
    sa.Column('reference_id', sa.String(length=40), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], name=op.f('fk_stock_movements_branch_id_branches'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_stock_movements_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_stock_movements_product_id_products'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stock_movements'))
    )
    with op.batch_alter_table('stock_movements', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stock_movements_branch_id'), ['branch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_stock_movements_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_stock_movements_movement_type'), ['movement_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_stock_movements_product_id'), ['product_id'], unique=False)

    op.create_table('goods_receipt_items',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('goods_receipt_id', sa.Integer(), nullable=False),
    sa.Column('purchase_order_item_id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_goods_receipt_items_receipt_quantity_positive')),
    sa.ForeignKeyConstraint(['goods_receipt_id'], ['goods_receipts.id'], name=op.f('fk_goods_receipt_items_goods_receipt_id_goods_receipts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_goods_receipt_items_product_id_products'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['purchase_order_item_id'], ['purchase_order_items.id'], name=op.f('fk_goods_receipt_items_purchase_order_item_id_purchase_order_items'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_goods_receipt_items'))
    )
    with op.batch_alter_table('goods_receipt_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_goods_receipt_items_goods_receipt_id'), ['goods_receipt_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_goods_receipt_items_product_id'), ['product_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_goods_receipt_items_purchase_order_item_id'), ['purchase_order_item_id'], unique=False)

    op.create_table('payments',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('invoice_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('payment_method', sa.String(length=20), nullable=False),
    sa.Column('payment_reference', sa.String(length=80), nullable=True),
    sa.Column('payment_date', sa.DateTime(), nullable=False),
    sa.Column('payment_status', sa.String(length=20), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('amount > 0', name=op.f('ck_payments_payment_amount_positive')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_payments_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_payments_invoice_id_invoices'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payments'))
    )
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_payments_invoice_id'), ['invoice_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_payments_payment_date'), ['payment_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_payments_payment_status'), ['payment_status'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payments_payment_status'))
        batch_op.drop_index(batch_op.f('ix_payments_payment_date'))
        batch_op.drop_index(batch_op.f('ix_payments_invoice_id'))

    op.drop_table('payments')
    with op.batch_alter_table('goods_receipt_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_goods_receipt_items_purchase_order_item_id'))
        batch_op.drop_index(batch_op.f('ix_goods_receipt_items_product_id'))
        batch_op.drop_index(batch_op.f('ix_goods_receipt_items_goods_receipt_id'))

    op.drop_table('goods_receipt_items')
    with op.batch_alter_table('stock_movements', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stock_movements_product_id'))
        batch_op.drop_index(batch_op.f('ix_stock_movements_movement_type'))
        batch_op.drop_index(batch_op.f('ix_stock_movements_created_at'))
        batch_op.drop_index(batch_op.f('ix_stock_movements_branch_id'))

    op.drop_table('stock_movements')
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sales_order_items_sales_order_id'))
        batch_op.drop_index(batch_op.f('ix_sales_order_items_product_id'))

    op.drop_table('sales_order_items')
    with op.batch_alter_table('purchase_order_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_purchase_order_items_purchase_order_id'))
        batch_op.drop_index(batch_op.f('ix_purchase_order_items_product_id'))

    op.drop_table('purchase_order_items')
    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_invoices_status'))
        batch_op.drop_index(batch_op.f('ix_invoices_invoice_number'))
        batch_op.drop_index(batch_op.f('ix_invoices_customer_id'))

    op.drop_table('invoices')
    with op.batch_alter_table('inventory', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_inventory_product_id'))
        batch_op.drop_index(batch_op.f('ix_inventory_branch_id'))

    op.drop_table('inventory')
    with op.batch_alter_table('goods_receipts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_goods_receipts_received_at'))
        batch_op.drop_index(batch_op.f('ix_goods_receipts_receipt_number'))
        batch_op.drop_index(batch_op.f('ix_goods_receipts_purchase_order_id'))

    op.drop_table('goods_receipts')
    with op.batch_alter_table('sales_orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sales_orders_payment_status'))
        batch_op.drop_index(batch_op.f('ix_sales_orders_order_status'))
        batch_op.drop_index(batch_op.f('ix_sales_orders_order_number'))
        batch_op.drop_index(batch_op.f('ix_sales_orders_customer_id'))
        batch_op.drop_index(batch_op.f('ix_sales_orders_created_at'))

    op.drop_table('sales_orders')
    with op.batch_alter_table('purchase_orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_purchase_orders_supplier_id'))
        batch_op.drop_index(batch_op.f('ix_purchase_orders_status'))
        batch_op.drop_index(batch_op.f('ix_purchase_orders_purchase_order_number'))
        batch_op.drop_index(batch_op.f('ix_purchase_orders_created_at'))

    op.drop_table('purchase_orders')
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_products_sku'))
        batch_op.drop_index(batch_op.f('ix_products_product_name'))
        batch_op.drop_index(batch_op.f('ix_products_category_id'))
        batch_op.drop_index(batch_op.f('ix_products_barcode'))

    op.drop_table('products')
    with op.batch_alter_table('financial_transactions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_financial_transactions_transaction_type'))
        batch_op.drop_index(batch_op.f('ix_financial_transactions_transaction_number'))
        batch_op.drop_index(batch_op.f('ix_financial_transactions_transaction_date'))
        batch_op.drop_index(batch_op.f('ix_financial_transactions_reference_type'))
        batch_op.drop_index(batch_op.f('ix_financial_transactions_reference_id'))
        batch_op.drop_index(batch_op.f('ix_financial_transactions_category'))

    op.drop_table('financial_transactions')
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_expenses_status'))
        batch_op.drop_index(batch_op.f('ix_expenses_expense_number'))
        batch_op.drop_index(batch_op.f('ix_expenses_expense_date'))
        batch_op.drop_index(batch_op.f('ix_expenses_expense_category'))

    op.drop_table('expenses')
    with op.batch_alter_table('customer_follow_ups', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_customer_follow_ups_status'))
        batch_op.drop_index(batch_op.f('ix_customer_follow_ups_due_date'))
        batch_op.drop_index(batch_op.f('ix_customer_follow_ups_customer_id'))
        batch_op.drop_index(batch_op.f('ix_customer_follow_ups_assigned_to'))

    op.drop_table('customer_follow_ups')
    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_suppliers_supplier_name'))
        batch_op.drop_index(batch_op.f('ix_suppliers_supplier_code'))
        batch_op.drop_index(batch_op.f('ix_suppliers_email'))

    op.drop_table('suppliers')
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_customers_phone'))
        batch_op.drop_index(batch_op.f('ix_customers_full_name'))
        batch_op.drop_index(batch_op.f('ix_customers_email'))
        batch_op.drop_index(batch_op.f('ix_customers_customer_code'))
        batch_op.drop_index(batch_op.f('ix_customers_created_at'))
        batch_op.drop_index(batch_op.f('ix_customers_city'))

    op.drop_table('customers')
    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_categories_category_name'))

    op.drop_table('categories')
    with op.batch_alter_table('business_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_business_events_status'))
        batch_op.drop_index(batch_op.f('ix_business_events_event_type'))
        batch_op.drop_index(batch_op.f('ix_business_events_created_at'))

    op.drop_table('business_events')
    op.drop_table('branches')
