"""Modal dialogs."""

from app.ui.dialogs.catalog_dialogs import (
    CategoryDialog,
    ProductDialog,
    StockAdjustmentDialog,
)
from app.ui.dialogs.crm_dialogs import CustomerDialog, FollowUpDialog
from app.ui.dialogs.finance_dialogs import ExpenseDialog
from app.ui.dialogs.password_dialog import PasswordChangeDialog, PasswordResetDialog
from app.ui.dialogs.profile_dialog import ProfileDialog
from app.ui.dialogs.role_dialog import RoleDialog
from app.ui.dialogs.sales_dialogs import (
    InvoiceDialog,
    PaymentDialog,
    ReasonDialog,
    SalesOrderDialog,
)
from app.ui.dialogs.supply_dialogs import (
    GoodsReceiptDialog,
    PurchaseOrderDialog,
    SupplierDialog,
)
from app.ui.dialogs.user_dialog import UserDialog

__all__ = [
    "CategoryDialog",
    "CustomerDialog",
    "ExpenseDialog",
    "FollowUpDialog",
    "GoodsReceiptDialog",
    "InvoiceDialog",
    "PasswordChangeDialog",
    "PasswordResetDialog",
    "PaymentDialog",
    "ProductDialog",
    "ProfileDialog",
    "PurchaseOrderDialog",
    "ReasonDialog",
    "RoleDialog",
    "SalesOrderDialog",
    "StockAdjustmentDialog",
    "SupplierDialog",
    "UserDialog",
]
