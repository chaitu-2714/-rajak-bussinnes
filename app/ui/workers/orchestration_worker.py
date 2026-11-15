"""Background workers for the AI Command Center.

Long-running orchestration never runs on the Qt UI thread: a worker thread calls
the service and reports back through signals.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger

logger = get_logger("ui.ai_worker")


class CommandWorker(QThread):
    """Runs one AI command: plan, execute, report."""

    workflow_started = Signal(str, str)  # workflow_id, intent
    progress = Signal(str)
    completed = Signal(object)  # WorkflowResult
    failed = Signal(str)

    def __init__(self, service: Any, conversation_id: int, command: str) -> None:
        super().__init__()
        self._service = service
        self._conversation_id = conversation_id
        self._command = command

    def run(self) -> None:  # noqa: D102
        try:
            self.progress.emit("Classifying the request…")
            preview = self._service.begin_command(self._conversation_id, self._command)
            self.workflow_started.emit(preview.workflow_id, preview.intent.value)

            if preview.clarification_question and not preview.steps:
                from app.ai.schemas.workflow_schema import WorkflowResult
                from app.core.constants import AIWorkflowStatus

                self.completed.emit(
                    WorkflowResult(
                        workflow_id=preview.workflow_id,
                        intent=preview.intent,
                        status=AIWorkflowStatus.COMPLETED,
                        response_text=preview.clarification_question,
                    )
                )
                return

            self.progress.emit(f"Running {len(preview.steps)} step(s)…")
            result = self._service.execute_workflow(preview.workflow_id)
            self.completed.emit(result)
        except BizPilotError as exc:
            logger.warning("AI command rejected: %s", exc.message)
            self.failed.emit(exc.user_message)
        except Exception:  # pragma: no cover - defensive
            logger.exception("AI command failed unexpectedly")
            self.failed.emit("The AI command failed unexpectedly; details were logged.")


class ActionWorker(QThread):
    """Runs any service callable off the UI thread (approve, retry, events)."""

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, action: Callable[[], Any], description: str = "Task") -> None:
        super().__init__()
        self._action = action
        self._description = description

    def run(self) -> None:  # noqa: D102
        try:
            self.finished_ok.emit(self._action())
        except BizPilotError as exc:
            logger.warning("%s rejected: %s", self._description, exc.message)
            self.failed.emit(exc.user_message)
        except Exception:  # pragma: no cover - defensive
            logger.exception("%s failed unexpectedly", self._description)
            self.failed.emit(f"{self._description} failed unexpectedly.")
