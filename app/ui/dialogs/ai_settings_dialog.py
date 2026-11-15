"""AI provider settings dialog (Super Admin / agents.configure)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.exceptions import BizPilotError
from app.ui.ui_utils import (
    field_label,
    muted_label,
    primary_button,
    secondary_button,
    show_error,
)


class AISettingsDialog(QDialog):
    """Configure providers, cloud sharing and API keys."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self.setWindowTitle("AI settings")
        self.setMinimumWidth(520)
        self._inputs: dict[str, dict[str, QWidget]] = {}
        self._build()
        self._load()

    # -- UI ----------------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("AI providers")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        layout.addWidget(
            muted_label(
                "Ollama runs locally and works offline. Gemini is a cloud provider and is "
                "only used when you enable cloud sharing below."
            )
        )

        for provider, label in (("ollama", "Ollama (local)"), ("gemini", "Gemini (cloud)")):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            enabled = QCheckBox(label)
            model = QLineEdit()
            model.setPlaceholderText("model name")
            priority = QSpinBox()
            priority.setRange(1, 999)
            row_layout.addWidget(enabled, 2)
            row_layout.addWidget(model, 2)
            row_layout.addWidget(QLabel("priority"))
            row_layout.addWidget(priority)
            layout.addWidget(row)
            self._inputs[provider] = {"enabled": enabled, "model": model, "priority": priority}

        self._credential_label = muted_label("")
        layout.addWidget(self._credential_label)

        key_row = QWidget()
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.Password)
        self._api_key.setPlaceholderText("Paste a Gemini API key to store it securely")
        self._save_key_button = secondary_button("Save key")
        self._clear_key_button = secondary_button("Clear")
        self._save_key_button.clicked.connect(self._save_api_key)
        self._clear_key_button.clicked.connect(self._clear_api_key)
        key_layout.addWidget(self._api_key, 1)
        key_layout.addWidget(self._save_key_button)
        key_layout.addWidget(self._clear_key_button)
        layout.addWidget(key_row)
        layout.addWidget(
            muted_label(
                "Keys are stored in the operating system credential store, never in the database."
            )
        )

        form = QFormLayout()
        self._cloud = QCheckBox("Allow sending aggregated figures to the cloud provider")
        form.addRow(field_label("Cloud data sharing"), self._cloud)
        self._preferred = QComboBox()
        self._preferred.addItem("Automatic (priority order)", "auto")
        self._preferred.addItem("Prefer Ollama", "ollama")
        self._preferred.addItem("Prefer Gemini", "gemini")
        form.addRow(field_label("Preference"), self._preferred)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = secondary_button("Cancel")
        cancel.clicked.connect(self.reject)
        save = primary_button("Save settings")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    # -- data --------------------------------------------------------------
    def _load(self) -> None:
        try:
            settings = self._context.ai_service.get_settings()
        except BizPilotError as exc:
            show_error(self, exc)
            return
        for entry in settings.providers:
            widgets = self._inputs.get(entry["provider"])
            if not widgets:
                continue
            widgets["enabled"].setChecked(bool(entry["is_enabled"]))
            widgets["model"].setText(entry["model_name"])
            widgets["priority"].setValue(int(entry["priority"]))
        self._cloud.setChecked(settings.cloud_sharing_enabled)
        index = self._preferred.findData(settings.preferred_provider)
        self._preferred.setCurrentIndex(max(0, index))
        self._credential_label.setText(
            "Gemini: " + settings.credentials.get("gemini", "unknown")
        )

    def _save(self) -> None:
        providers = [
            {
                "provider": provider,
                "model_name": widgets["model"].text().strip() or "unknown",
                "is_enabled": widgets["enabled"].isChecked(),
                "priority": widgets["priority"].value(),
            }
            for provider, widgets in self._inputs.items()
        ]
        try:
            self._context.ai_service.update_settings(
                providers=providers,
                cloud_sharing_enabled=self._cloud.isChecked(),
                preferred_provider=self._preferred.currentData(),
            )
        except BizPilotError as exc:
            show_error(self, exc)
            return
        self.accept()

    def _save_api_key(self) -> None:
        key = self._api_key.text().strip()
        if not key:
            show_error(self, BizPilotError("Enter an API key first"))
            return
        try:
            description = self._context.ai_service.set_api_key("gemini", key)
        except BizPilotError as exc:
            show_error(self, exc)
            return
        self._api_key.clear()
        self._credential_label.setText("Gemini: " + description)

    def _clear_api_key(self) -> None:
        try:
            self._context.ai_service.clear_api_key("gemini")
        except BizPilotError as exc:
            show_error(self, exc)
            return
        self._credential_label.setText("Gemini: no API key configured")
