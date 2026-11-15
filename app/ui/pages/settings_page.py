"""Settings page: business profile, account, application info, backups."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.config import APP_VERSION
from app.core.constants import CURRENCIES, TIMEZONES
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.services.backup_service import BackupFile
from app.ui.components.confirmation_dialog import confirm
from app.ui.dialogs.password_dialog import PasswordChangeDialog
from app.ui.ui_utils import (
    danger_button,
    field_label,
    muted_label,
    primary_button,
    secondary_button,
    show_info,
)
from app.utils.date_utils import format_datetime

logger = get_logger("ui.settings")


class SettingsPage(QWidget):
    """Workspace, account, application and backup settings."""

    session_invalidated = Signal()

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._backups: list[BackupFile] = []
        self._can_update = bool(
            context.auth_context.principal
            and context.auth_context.principal.has("settings.update")
        )
        self.setObjectName("PageSurface")
        self._build()
        self.refresh()

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._business_tab(), "Business")
        self.tabs.addTab(self._account_tab(), "Account")
        self.tabs.addTab(self._application_tab(), "Application")
        self.tabs.addTab(self._backup_tab(), "Backup and restore")
        layout.addWidget(self.tabs, 1)

        self._error = QLabel("")
        self._error.setObjectName("ErrorText")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        layout.addWidget(self._error)

    def _scrollable(self, inner: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        return scroll

    # -- business ----------------------------------------------------------
    def _business_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        layout.addWidget(
            muted_label(
                "These details appear on the dashboard and in reports. "
                "Changes are written to the audit log."
            )
        )

        form = QFormLayout()
        form.setSpacing(9)

        self.business_name_input = QLineEdit()
        form.addRow("Business name *", self.business_name_input)

        self.owner_name_input = QLineEdit()
        form.addRow("Owner name *", self.owner_name_input)

        self.business_email_input = QLineEdit()
        form.addRow("Contact email *", self.business_email_input)

        self.business_phone_input = QLineEdit()
        form.addRow("Phone", self.business_phone_input)

        self.address_input = QPlainTextEdit()
        self.address_input.setMaximumHeight(70)
        form.addRow("Address", self.address_input)

        self.currency_combo = QComboBox()
        self.currency_combo.addItems(CURRENCIES)
        form.addRow("Currency", self.currency_combo)

        self.timezone_combo = QComboBox()
        self.timezone_combo.addItems(TIMEZONES)
        form.addRow("Timezone", self.timezone_combo)

        self.financial_year_input = QLineEdit()
        self.financial_year_input.setPlaceholderText("MM-DD")
        form.addRow("Financial year starts", self.financial_year_input)

        layout.addLayout(form)

        row = QHBoxLayout()
        row.addStretch(1)
        self.save_business_button = primary_button("Save business details")
        self.save_business_button.setEnabled(self._can_update)
        self.save_business_button.clicked.connect(self._save_business)
        row.addWidget(self.save_business_button)
        layout.addLayout(row)

        if not self._can_update:
            note = QLabel(
                "Read-only: your role does not include the settings.update permission."
            )
            note.setObjectName("Hint")
            layout.addWidget(note)
            for widget in (
                self.business_name_input,
                self.owner_name_input,
                self.business_email_input,
                self.business_phone_input,
                self.address_input,
                self.currency_combo,
                self.timezone_combo,
                self.financial_year_input,
            ):
                widget.setEnabled(False)

        layout.addStretch(1)
        return self._scrollable(page)

    # -- account -----------------------------------------------------------
    def _account_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        layout.addWidget(field_label("Signed-in account"))
        self.account_email_input = QLineEdit()
        self.account_email_input.setReadOnly(True)
        layout.addWidget(self.account_email_input)

        self.account_roles_input = QLineEdit()
        self.account_roles_input.setReadOnly(True)
        layout.addWidget(self.account_roles_input)

        layout.addWidget(field_label("Full name *"))
        self.profile_name_input = QLineEdit()
        layout.addWidget(self.profile_name_input)

        layout.addWidget(field_label("Phone"))
        self.profile_phone_input = QLineEdit()
        layout.addWidget(self.profile_phone_input)

        row = QHBoxLayout()
        row.addStretch(1)
        self.change_password_button = secondary_button("Change password")
        self.change_password_button.clicked.connect(self._change_password)
        row.addWidget(self.change_password_button)
        save_profile = primary_button("Save profile")
        save_profile.clicked.connect(self._save_profile)
        row.addWidget(save_profile)
        layout.addLayout(row)

        line = QFrame()
        line.setObjectName("Divider")
        line.setFixedHeight(1)
        layout.addWidget(line)

        layout.addWidget(field_label("Current session"))
        self.session_label = QLabel("—")
        self.session_label.setObjectName("Muted")
        self.session_label.setWordWrap(True)
        layout.addWidget(self.session_label)

        layout.addStretch(1)
        return self._scrollable(page)

    # -- application -------------------------------------------------------
    def _application_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        layout.addWidget(
            muted_label(
                "BizPilot AI runs entirely on this computer. Data stays in the local "
                "SQLite database below — nothing is sent to a server."
            )
        )

        form = QFormLayout()
        form.setSpacing(9)

        theme = QLineEdit("Light (default)")
        theme.setReadOnly(True)
        form.addRow("Theme", theme)

        version = QLineEdit(APP_VERSION)
        version.setReadOnly(True)
        form.addRow("Application version", version)

        self.db_path_input = QLineEdit()
        self.db_path_input.setReadOnly(True)
        form.addRow("Database location", self.db_path_input)

        self.log_path_input = QLineEdit()
        self.log_path_input.setReadOnly(True)
        form.addRow("Log location", self.log_path_input)

        self.backup_path_input = QLineEdit()
        self.backup_path_input.setReadOnly(True)
        form.addRow("Backup folder", self.backup_path_input)

        layout.addLayout(form)

        note = QLabel(
            "This Phase 1 build supports multiple local accounts on one computer. "
            "It is not a shared multi-computer database."
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return self._scrollable(page)

    # -- backup ------------------------------------------------------------
    def _backup_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        layout.addWidget(
            muted_label(
                "Backups use SQLite's online backup API, so a running transaction cannot "
                "produce a corrupt copy. A safety copy is taken before every restore."
            )
        )

        self.backup_table = QTableWidget(0, 3)
        self.backup_table.setHorizontalHeaderLabels(["File", "Size", "Created"])
        self.backup_table.verticalHeader().setVisible(False)
        self.backup_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.backup_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.backup_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.backup_table.setShowGrid(False)
        self.backup_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.backup_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.backup_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(self.backup_table, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        refresh_button = secondary_button("Refresh list")
        refresh_button.clicked.connect(self._load_backups)
        row.addWidget(refresh_button)
        row.addStretch(1)

        self.backup_button = primary_button("Create backup")
        self.backup_button.setEnabled(self._can_update)
        self.backup_button.clicked.connect(lambda: self._create_backup(None))
        row.addWidget(self.backup_button)

        self.backup_as_button = secondary_button("Save backup as…")
        self.backup_as_button.setEnabled(self._can_update)
        self.backup_as_button.clicked.connect(self._create_backup_as)
        row.addWidget(self.backup_as_button)

        self.restore_button = danger_button("Restore selected")
        self.restore_button.setEnabled(self._can_update)
        self.restore_button.clicked.connect(self._restore_selected)
        row.addWidget(self.restore_button)
        layout.addLayout(row)

        self._backup_status = QLabel("")
        self._backup_status.setObjectName("Hint")
        self._backup_status.setWordWrap(True)
        layout.addWidget(self._backup_status)
        return page

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        self._error.setVisible(False)
        self._load_business()
        self._load_account()
        self._load_application()
        self._load_backups()

    def _load_business(self) -> None:
        try:
            business = self._context.business_service.get_business()
        except BizPilotError as exc:
            self._error.setText(exc.user_message)
            self._error.setVisible(True)
            return
        self.business_name_input.setText(business.business_name)
        self.owner_name_input.setText(business.owner_name)
        self.business_email_input.setText(business.email)
        self.business_phone_input.setText(business.phone or "")
        self.address_input.setPlainText(business.address or "")
        index = self.currency_combo.findText(business.currency)
        if index >= 0:
            self.currency_combo.setCurrentIndex(index)
        index = self.timezone_combo.findText(business.timezone)
        if index >= 0:
            self.timezone_combo.setCurrentIndex(index)
        self.financial_year_input.setText(business.financial_year_start)

    def _load_account(self) -> None:
        principal = self._context.auth_context.principal
        if principal is None:
            return
        self.account_email_input.setText(principal.email)
        self.account_roles_input.setText(", ".join(principal.roles) or "No role")
        self.profile_name_input.setText(principal.full_name)

        try:
            user = self._context.user_service.get_user(principal.user_id)
            self.profile_phone_input.setText(user.phone or "")
        except BizPilotError:
            self.profile_phone_input.setText("")

        snapshot = self._context.auth_service.session_snapshot()
        if snapshot is None:
            self.session_label.setText("No active session recorded.")
        else:
            self.session_label.setText(
                f"Session #{snapshot.session_id} · started {format_datetime(snapshot.created_at)} · "
                f"expires {format_datetime(snapshot.expires_at)} · "
                f"last activity {format_datetime(snapshot.last_activity_at)}"
            )

    def _load_application(self) -> None:
        config = self._context.config
        self.db_path_input.setText(str(config.db_path))
        self.log_path_input.setText(str(config.log_dir))
        self.backup_path_input.setText(str(config.backup_dir))

    def _load_backups(self) -> None:
        try:
            backups = self._context.backup_service.list_backups()
        except BizPilotError as exc:
            self._backup_status.setText(exc.user_message)
            return
        self._backups = backups
        self.backup_table.setRowCount(0)
        for row, backup in enumerate(backups):
            self.backup_table.insertRow(row)
            values = (
                backup.name,
                backup.size_label,
                format_datetime(backup.created_at),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.backup_table.setItem(row, column, item)
        if not backups:
            self._backup_status.setText("No backups yet. Create one before major changes.")
        else:
            self._backup_status.setText(f"{len(backups)} backup file(s) in {self._context.config.backup_dir}")

    # -- actions -----------------------------------------------------------
    def _save_business(self) -> None:
        payload = {
            "business_name": self.business_name_input.text().strip(),
            "owner_name": self.owner_name_input.text().strip(),
            "email": self.business_email_input.text().strip(),
            "phone": self.business_phone_input.text().strip() or None,
            "address": self.address_input.toPlainText().strip() or None,
            "currency": self.currency_combo.currentText(),
            "timezone": self.timezone_combo.currentText(),
            "financial_year_start": self.financial_year_input.text().strip(),
        }
        try:
            self._context.business_service.update_business(payload)
        except BizPilotError as exc:
            self._error.setText(exc.user_message)
            self._error.setVisible(True)
            return
        self._error.setVisible(False)
        show_info(self, "Business details were updated.", "Settings saved")

    def _save_profile(self) -> None:
        try:
            self._context.user_service.update_own_profile(
                {
                    "full_name": self.profile_name_input.text().strip(),
                    "phone": self.profile_phone_input.text().strip() or None,
                }
            )
        except BizPilotError as exc:
            self._error.setText(exc.user_message)
            self._error.setVisible(True)
            return
        show_info(self, "Your profile was updated.", "Profile saved")

    def _change_password(self) -> None:
        dialog = PasswordChangeDialog(self._context, self)
        if dialog.exec():
            show_info(
                self,
                "Your password was changed. Other sessions on this computer were signed out.",
                "Password updated",
            )

    def _create_backup(self, destination: Path | None) -> None:
        try:
            backup = self._context.backup_service.create_backup(destination)
        except BizPilotError as exc:
            self._error.setText(exc.user_message)
            self._error.setVisible(True)
            return
        self._load_backups()
        show_info(
            self,
            f"Backup created:\n{backup.path}\n({backup.size_label})",
            "Backup complete",
        )

    def _create_backup_as(self) -> None:
        default = self._context.config.backup_dir / "bizpilot_backup.db"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save backup as", str(default), "SQLite database (*.db)"
        )
        if path:
            self._create_backup(Path(path))

    def _restore_selected(self) -> None:
        row = self.backup_table.currentRow()
        if row < 0 or row >= len(self._backups):
            self._backup_status.setText("Select a backup file to restore first.")
            return
        backup = self._backups[row]
        if not confirm(
            self,
            title="Restore database",
            message=(
                f"Restoring '{backup.name}' replaces the current database. A safety copy "
                "of the current data is taken first, then you will be signed out so the "
                "restored sessions are not trusted."
            ),
            confirm_text="Restore database",
            destructive=True,
            challenge="RESTORE",
        ):
            return
        try:
            safety = self._context.backup_service.restore_backup(backup.path)
        except BizPilotError as exc:
            self._error.setText(exc.user_message)
            self._error.setVisible(True)
            return

        detail = f"Safety copy: {safety.path.name}" if safety else "No safety copy was kept."
        show_info(
            self,
            f"The database was restored from {backup.name}.\n{detail}\n\n"
            "You will now be signed out.",
            "Restore complete",
        )
        self.session_invalidated.emit()
