import threading
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QProgressBar, QGridLayout
)
from src.gui.styles import set_dark_titlebar

class CustomQuestionDialog(QDialog):
    """Кастомный диалог с вопросом о создании папок и тремя кнопками выбора."""

    def __init__(self, parent: QWidget, title: str, message: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(400, 150)
        self.setModal(True)
        self.result_value = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        lbl = QLabel(message, self)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size: 13px;")
        layout.addWidget(lbl)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        # Тексты кнопок
        text_yes = parent.loc("yes")
        text_no = parent.loc("no")
        text_both = parent.loc("create_both")

        btn_yes = QPushButton(text_yes, self)
        btn_yes.clicked.connect(lambda: self.finish("yes"))
        btn_layout.addWidget(btn_yes)

        btn_no = QPushButton(text_no, self)
        btn_no.clicked.connect(lambda: self.finish("no"))
        btn_layout.addWidget(btn_no)

        btn_both = QPushButton(text_both, self)
        btn_both.clicked.connect(lambda: self.finish("both"))
        btn_layout.addWidget(btn_both)

        layout.addLayout(btn_layout)

    def finish(self, val: str) -> None:
        self.result_value = val
        self.accept()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        set_dark_titlebar(self)


class UpdateDialog(QDialog):
    """Кастомный диалог с вопросом об обновлении версии."""

    def __init__(self, parent: QWidget, new_version: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(parent.loc("update_title"))
        self.setFixedSize(420, 160)
        self.setModal(True)
        self.result_value = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # Форматируем сообщение с версией
        message = parent.loc("update_message").format(new_version)
        lbl = QLabel(message, self)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size: 13px;")
        layout.addWidget(lbl)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        # Тексты кнопок
        text_yes = parent.loc("yes")
        text_no = parent.loc("no")
        text_skip = parent.loc("dont_show_again")

        btn_yes = QPushButton(text_yes, self)
        btn_yes.clicked.connect(lambda: self.finish("yes"))
        btn_layout.addWidget(btn_yes)

        btn_no = QPushButton(text_no, self)
        btn_no.clicked.connect(lambda: self.finish("no"))
        btn_layout.addWidget(btn_no)

        btn_skip = QPushButton(text_skip, self)
        btn_skip.clicked.connect(lambda: self.finish("skip"))
        btn_layout.addWidget(btn_skip)

        layout.addLayout(btn_layout)

    def finish(self, val: str) -> None:
        self.result_value = val
        self.accept()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        set_dark_titlebar(self)


class PatientEditDialog(QDialog):
    """Диалог для интерактивной коррекции имени и ID пациента."""

    def __init__(self, parent: QWidget, current_name: str, current_id: str) -> None:
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle(parent.loc("dialog_patient_info"))
        self.setFixedSize(420, 260)
        self.setModal(True)

        self.new_name = current_name
        self.new_id = current_id
        self.cancelled = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        lbl_msg = QLabel(parent.loc("dialog_patient_message"), self)
        lbl_msg.setWordWrap(True)
        lbl_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_msg.setStyleSheet("font-size: 12px;")
        layout.addWidget(lbl_msg)

        form_layout = QGridLayout()
        form_layout.setSpacing(10)

        lbl_name = QLabel(parent.loc("dialog_pat_name"), self)
        form_layout.addWidget(lbl_name, 0, 0)
        self.ent_name = QLineEdit(self)
        self.ent_name.setText(current_name)
        form_layout.addWidget(self.ent_name, 0, 1)

        lbl_id = QLabel(parent.loc("dialog_pat_id"), self)
        form_layout.addWidget(lbl_id, 1, 0)
        self.ent_id = QLineEdit(self)
        self.ent_id.setText(current_id)
        form_layout.addWidget(self.ent_id, 1, 1)

        layout.addLayout(form_layout)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)

        btn_save = QPushButton(parent.loc("dialog_save"), self)
        btn_save.clicked.connect(self.on_save)
        btn_save.setStyleSheet("background-color: #2563EB; color: white; font-weight: bold;")
        btn_layout.addWidget(btn_save)

        btn_skip = QPushButton(parent.loc("no"), self)
        btn_skip.clicked.connect(self.on_skip)
        btn_skip.setStyleSheet("background-color: #4B5563; color: white;")
        btn_layout.addWidget(btn_skip)

        layout.addLayout(btn_layout)

    def on_save(self) -> None:
        self.new_name = self.ent_name.text().strip()
        self.new_id = self.ent_id.text().strip()
        self.accept()

    def on_skip(self) -> None:
        self.cancelled = True
        self.reject()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        set_dark_titlebar(self)


class ScanProgressDialog(QDialog):
    """Модальный диалог, отображающий прогресс сканирования директории."""

    def __init__(self, parent: QWidget, stop_event: threading.Event) -> None:
        super().__init__(parent)
        self.parent = parent
        self.stop_event = stop_event
        self.setWindowTitle(parent.loc("dialog_scan_title"))
        self.setFixedSize(380, 150)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        self.lbl_status = QLabel(parent.loc("dialog_scan_finding"), self)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet("font-size: 13px;")
        layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(16)
        layout.addWidget(self.progress_bar)

        self.btn_cancel = QPushButton(parent.loc("dialog_scan_cancel"), self)
        self.btn_cancel.clicked.connect(self.on_cancel)
        self.btn_cancel.setStyleSheet("background-color: #4B5563; color: white; min-width: 100px;")
        layout.addWidget(self.btn_cancel, alignment=Qt.AlignmentFlag.AlignCenter)

    def update_progress(self, current: int, total: int) -> None:
        if total > 0:
            prog = current / total
            pct = int(prog * 100)
            self.progress_bar.setValue(pct)
            self.lbl_status.setText(
                self.parent.loc("dialog_scan_progress", current, total)
            )

    def on_cancel(self) -> None:
        self.stop_event.set()
        self.reject()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        set_dark_titlebar(self)
