"""Modal confirmation dialogs.

Only the clear-history confirmation lives here today. It defaults to Cancel so
a stray Enter cannot destroy history.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ConfirmDialog(QDialog):
    """A short heading, an explanation, and a cancel/confirm pair."""

    def __init__(
        self,
        parent: QWidget | None,
        heading: str,
        body: str,
        confirm_text: str,
        cancel_text: str = "Cancel",
        destructive: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ClipNest")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setObjectName("ConfirmDialog")

        self.heading_label = QLabel(heading, self)
        self.heading_label.setObjectName("StateTitle")
        self.heading_label.setWordWrap(True)

        self.body_label = QLabel(body, self)
        self.body_label.setObjectName("StateDescription")
        self.body_label.setWordWrap(True)

        self.cancel_button = QPushButton(cancel_text, self)
        self.cancel_button.setObjectName("SecondaryButton")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setDefault(True)
        self.cancel_button.setAutoDefault(True)
        self.cancel_button.clicked.connect(self.reject)

        self.confirm_button = QPushButton(confirm_text, self)
        self.confirm_button.setObjectName(
            "DangerButton" if destructive else "PrimaryButton"
        )
        self.confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.clicked.connect(self.accept)

        buttons = QWidget(self)
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(8)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.confirm_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)
        layout.addWidget(self.heading_label)
        layout.addWidget(self.body_label)
        layout.addSpacing(6)
        layout.addWidget(buttons)


def clear_history_body(unpinned_count: int, pinned_count: int) -> str:
    """Explain exactly what clearing removes and what it keeps."""
    noun = "snippet" if unpinned_count == 1 else "snippets"
    body = (
        f"{unpinned_count} unpinned {noun} will be permanently deleted from "
        "this device. This cannot be undone.\n\n"
        "Pinned snippets are kept in your history."
    )
    if pinned_count:
        pinned_noun = "snippet" if pinned_count == 1 else "snippets"
        body += f" ({pinned_count} pinned {pinned_noun} currently saved.)"
    return body


def create_clear_history_dialog(
    parent: QWidget | None, unpinned_count: int, pinned_count: int
) -> ConfirmDialog:
    """Build (but do not show) the clear-history confirmation."""
    return ConfirmDialog(
        parent=parent,
        heading="Clear clipboard history?",
        body=clear_history_body(unpinned_count, pinned_count),
        confirm_text="Clear history",
        cancel_text="Cancel",
        destructive=True,
    )


def confirm_clear_history(
    parent: QWidget | None, unpinned_count: int, pinned_count: int
) -> bool:
    """Ask before deleting unpinned history. Returns ``True`` when confirmed."""
    dialog = create_clear_history_dialog(parent, unpinned_count, pinned_count)
    return dialog.exec() == QDialog.DialogCode.Accepted
