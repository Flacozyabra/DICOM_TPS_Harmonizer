from datetime import datetime
import json
import os
import sys
import platform
import threading
from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QSize, QPoint, QByteArray
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QLineEdit, QCheckBox, QProgressBar,
    QTextEdit, QTreeWidget, QTreeWidgetItem, QFileDialog, QDialog,
    QGridLayout, QMessageBox, QApplication, QSplitter, QSizePolicy
)
from PyQt6.QtGui import QIcon, QFont, QTextCursor, QPixmap, QBrush, QColor

from src.core.config import ProcessingConfig
from src.core.processor import DicomProcessor
from src.utils.logger import BaseLogger

def set_dark_titlebar(window: QWidget) -> None:
    """Окрашивает верхнюю полосу заголовка окна в темный цвет на Windows."""
    if platform.system() == "Windows":
        try:
            import ctypes
            hwnd = int(window.winId())
            # Атрибут DWMWA_USE_IMMERSIVE_DARK_MODE (20 в Win11, 19 в Win10)
            for attr in [20, 19]:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    attr,
                    ctypes.byref(ctypes.c_int(1)),
                    ctypes.sizeof(ctypes.c_int)
                )
        except Exception:
            pass

# Сигнальный мост для безопасной передачи сообщений из фоновых потоков в GUI
class QtSignalBridge(QObject):
    log_signal = pyqtSignal(str, str)          # text, tag
    progress_signal = pyqtSignal(int, int)      # current, total
    scan_progress_signal = pyqtSignal(int, int) # current, total
    finished_signal = pyqtSignal()
    tree_scanned_signal = pyqtSignal(dict)


# Адаптер логгера для отправки сообщений через сигналы Qt
class QtLogger(BaseLogger):
    def __init__(self, bridge: QtSignalBridge) -> None:
        self.bridge = bridge

    def log(self, text: str, tag: str = "info") -> None:
        self.bridge.log_signal.emit(text, tag)

    def update_progress(self, current: int, total: int) -> None:
        self.bridge.progress_signal.emit(current, total)

    def update_scan_progress(self, current: int, total: int) -> None:
        self.bridge.scan_progress_signal.emit(current, total)


class LanguageSwitch(QFrame):
    """Кастомный горизонтальный переключатель языков с флагами."""

    def __init__(self, parent: QWidget, command=None, current_lang: str = "ru", resources_dir: Path = None) -> None:
        super().__init__(parent)
        self.command = command
        self.lang = current_lang
        
        self.setFixedSize(76, 30)
        self.setStyleSheet("""
            QFrame {
                background-color: #2D2D2D;
                border: 1px solid #4B5563;
                border-radius: 15px;
            }
        """)

        # Загружаем картинки флагов
        self.px_ru = QPixmap(str(resources_dir / "ru_flag.png"))
        self.px_gb = QPixmap(str(resources_dir / "gb_flag.png"))

        # Метка RU флага (слева)
        self.lbl_ru = QLabel(self)
        self.lbl_ru.setPixmap(self.px_ru)
        self.lbl_ru.setScaledContents(True)
        self.lbl_ru.setFixedSize(24, 16)
        self.lbl_ru.move(9, 7)
        self.lbl_ru.setStyleSheet("background: transparent; border: none;")

        # Метка GB флага (справа)
        self.lbl_gb = QLabel(self)
        self.lbl_gb.setPixmap(self.px_gb)
        self.lbl_gb.setScaledContents(True)
        self.lbl_gb.setFixedSize(24, 16)
        self.lbl_gb.move(43, 7)
        self.lbl_gb.setStyleSheet("background: transparent; border: none;")

        # Ползунок (slider)
        self.slider = QFrame(self)
        self.slider.setFixedSize(36, 24)
        self.slider.setStyleSheet("""
            QFrame {
                background-color: #4B5563;
                border: none;
                border-radius: 12px;
            }
        """)

        self.slider_img = QLabel(self.slider)
        self.slider_img.setScaledContents(True)
        self.slider_img.setFixedSize(24, 16)
        self.slider_img.move(6, 4)
        self.slider_img.setStyleSheet("background: transparent; border: none;")

        self.update_slider_position()

    def update_slider_position(self) -> None:
        if self.lang == "ru":
            self.slider.move(3, 3)
            self.slider_img.setPixmap(self.px_ru)
        else:
            self.slider.move(37, 3)
            self.slider_img.setPixmap(self.px_gb)

    def mousePressEvent(self, event) -> None:
        if self.lang == "ru":
            self.lang = "en"
        else:
            self.lang = "ru"
        self.update_slider_position()
        if self.command:
            self.command(self.lang)


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
        lbl.setStyleSheet("font-size: 13px; color: #E5E7EB;")
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
        lbl_msg.setStyleSheet("font-size: 12px; color: #E5E7EB;")
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
        self.lbl_status.setStyleSheet("font-size: 13px; color: #E5E7EB;")
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
                self.parent.loc("dialog_scan_progress", current, total, pct)
            )

    def on_cancel(self) -> None:
        self.stop_event.set()
        self.reject()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        set_dark_titlebar(self)


class DicomSplitterApp(QMainWindow):
    """Главный класс графического интерфейса приложения DICOM TPS Harmonizer на PyQt6."""

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("DICOM TPS Harmonizer")

        # Определение путей к ресурсам относительно корня проекта с поддержкой PyInstaller
        if getattr(sys, "frozen", False):
            self.project_root = Path(sys._MEIPASS)
        else:
            self.project_root = Path(__file__).resolve().parents[2]
        
        icon_path = self.project_root / "themes" / "app_icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setMinimumSize(1000, 640)
        self.resize(1100, 720)

        # Инициализация моста сигналов
        self.bridge = QtSignalBridge()
        self.bridge.log_signal.connect(self.add_log)
        self.bridge.progress_signal.connect(self.update_progress)
        self.bridge.scan_progress_signal.connect(self.update_scan_progress)
        self.bridge.tree_scanned_signal.connect(self.on_tree_scanned)
        self.bridge.finished_signal.connect(self.on_processing_finished)

        # Загрузка путей и языка
        saved_input, saved_output, saved_lang = self.load_last_paths()
        self.current_lang = saved_lang
        
        self.translations: dict[str, str] = {}
        self.load_locale(self.current_lang)

        # Переводим плейсхолдеры
        if self.current_lang == "en":
            if saved_input == "Введите путь для папки Dicom_input":
                saved_input = self.loc("placeholder_input")
            if saved_output == "Введите путь для папки Dicom_output":
                saved_output = self.loc("placeholder_output")

        self.saved_input_path = saved_input
        self.saved_output_path = saved_output

        self.is_processing = False
        self.stop_event = threading.Event()
        self._is_updating_tree = False
        self.scan_dialog = None

        # Создание интерфейса
        self.create_widgets()
        self.apply_styles()
        self.update_locale_texts()
        self.center_on_screen()
        self.restore_window_state()

    def get_config_path(self) -> Path:
        """Возвращает путь к файлу конфигурации в AppData пользователя."""
        appdata = os.getenv("APPDATA")
        if appdata:
            config_dir = Path(appdata) / "DicomTpsHarmonizer"
        else:
            config_dir = Path.home() / ".dicom_tps_harmonizer"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "config.json"

    def load_last_paths(self) -> tuple[str, str, str]:
        config_file = self.get_config_path()
        inp = "Введите путь для папки Dicom_input"
        out = "Введите путь для папки Dicom_output"
        lang = "ru"
        
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    inp_val = data.get("input_dir", "")
                    out_val = data.get("output_dir", "")
                    lang_val = data.get("language", "ru")
                    if inp_val:
                        inp = inp_val
                    if out_val:
                        out = out_val
                    if lang_val:
                        lang = lang_val
            except Exception:
                pass
        return inp, out, lang

    def save_last_paths(self) -> None:
        inp = self.input_entry.text()
        out = self.output_entry.text()
        lang = self.current_lang
        
        config_data = {}
        config_file = self.get_config_path()
        
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
            except Exception:
                pass
                
        if "Введите путь" not in inp and "Enter path" not in inp:
            config_data["input_dir"] = inp
        if "Введите путь" not in out and "Enter path" not in out:
            config_data["output_dir"] = out
            
        config_data["language"] = lang
        
        # Сохраняем геометрию главного окна и состояние сплиттеров
        config_data["window_geometry"] = self.saveGeometry().toHex().data().decode('utf-8')
        if hasattr(self, "splitter"):
            config_data["splitter_state"] = self.splitter.saveState().toHex().data().decode('utf-8')
        if hasattr(self, "right_splitter"):
            config_data["right_splitter_state"] = self.right_splitter.saveState().toHex().data().decode('utf-8')
        
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def restore_window_state(self) -> None:
        config_file = self.get_config_path()
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                    # Восстановление геометрии главного окна
                    geom_hex = data.get("window_geometry", "")
                    if geom_hex:
                        self.restoreGeometry(QByteArray.fromHex(geom_hex.encode('utf-8')))
                        
                    # Восстановление состояния сплиттера
                    state_hex = data.get("splitter_state", "")
                    if state_hex and hasattr(self, "splitter"):
                        self.splitter.restoreState(QByteArray.fromHex(state_hex.encode('utf-8')))

                    # Восстановление состояния вертикального сплиттера
                    right_state_hex = data.get("right_splitter_state", "")
                    if right_state_hex and hasattr(self, "right_splitter"):
                        self.right_splitter.restoreState(QByteArray.fromHex(right_state_hex.encode('utf-8')))
            except Exception:
                pass

    def center_on_screen(self) -> None:
        """Центрирует окно приложения на первичном экране."""
        screen = QApplication.primaryScreen().geometry()
        width = 1100
        height = 720
        x = (screen.width() - width) // 2
        y = (screen.height() - height) // 2
        self.setGeometry(x, y, width, height)

    def load_locale(self, lang: str) -> None:
        if getattr(sys, "frozen", False):
            locales_dir = Path(sys._MEIPASS) / "locales"
        else:
            locales_dir = Path(__file__).resolve().parents[2] / "locales"
            
        locale_file = locales_dir / f"{lang}.json"
        if locale_file.exists():
            try:
                with open(locale_file, "r", encoding="utf-8") as f:
                    self.translations = json.load(f)
            except Exception:
                self.translations = {}
        else:
            self.translations = {}

    def loc(self, key: str, *args) -> str:
        val = self.translations.get(key, key)
        if args:
            try:
                return val.format(*args)
            except Exception:
                pass
        return val

    def change_language(self, lang: str) -> None:
        self.current_lang = lang
        self.load_locale(lang)
        
        inp = self.input_entry.text()
        out = self.output_entry.text()
        
        if inp in ["Введите путь для папки Dicom_input", "Enter path for Dicom_input folder"]:
            self.input_entry.setText(self.loc("placeholder_input"))
        if out in ["Введите путь для папки Dicom_output", "Enter path for Dicom_output folder"]:
            self.output_entry.setText(self.loc("placeholder_output"))
            
        self.update_locale_texts()
        self.save_last_paths()
        
        # Синхронизируем положение переключателя
        if hasattr(self, "lang_switch"):
            self.lang_switch.lang = lang
            self.lang_switch.update_slider_position()

    def update_locale_texts(self) -> None:
        self.setWindowTitle(self.loc("title"))
        self.title_label.setText(self.loc("title"))
        self.input_label.setText(self.loc("input_folder"))
        self.output_label.setText(self.loc("output_folder"))
        self.btn_browse_in.setText(self.loc("browse"))
        self.btn_browse_out.setText(self.loc("browse"))
        self.settings_title.setText(self.loc("optimization_params"))
        
        self.cb_new_uids.setText(self.loc("generate_uids"))
        self.cb_split_mf.setText(self.loc("split_multiframe"))
        self.cb_clean_tags.setText(self.loc("clean_tags"))
        self.cb_default_tags.setText(self.loc("fill_mandatory"))
        self.cb_explicit_vr.setText(self.loc("write_explicit"))
        self.cb_exclude_reports.setText(self.loc("exclude_reports"))
        self.cb_split_series.setText(self.loc("split_series"))
        
        self.sidebar_title.setText(self.loc("patient_explorer"))
        self.scan_btn.setText(self.loc("scan_input"))
        self.log_title.setText(self.loc("log_title"))
        
        # Tooltips
        self.btn_create_in.setToolTip(self.loc("tooltip_create_input"))
        self.btn_create_out.setToolTip(self.loc("tooltip_create_output"))
        self.btn_open_in.setToolTip(self.loc("tooltip_open_input"))
        self.btn_open_out.setToolTip(self.loc("tooltip_open_output"))

        self.update_selection_label()

        if self.is_processing:
            if self.stop_event.is_set():
                self.start_btn.setText(self.loc("status_stopping"))
            else:
                self.start_btn.setText(self.loc("stop_optimization"))
        else:
            self.start_btn.setText(self.loc("run_optimization"))

    def set_dark_titlebar(self) -> None:
        """Окрашивает верхнюю полосу заголовка окна в темный цвет на Windows."""
        if platform.system() == "Windows":
            try:
                import ctypes
                hwnd = int(self.winId())
                # Атрибут DWMWA_USE_IMMERSIVE_DARK_MODE (20 в Win11, 19 в Win10)
                for attr in [20, 19]:
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd,
                        attr,
                        ctypes.byref(ctypes.c_int(1)),
                        ctypes.sizeof(ctypes.c_int)
                    )
            except Exception:
                pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.set_dark_titlebar()

    def closeEvent(self, event) -> None:
        self.save_last_paths()
        super().closeEvent(event)

    def create_widgets(self) -> None:
        # Главный контейнер
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Создаем разделитель (splitter)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # ----------------------------------------------------
        # 1. Левая боковая панель (Проводник пациентов)
        # ----------------------------------------------------
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setObjectName("sidebar")
        self.sidebar_frame.setMinimumWidth(0) # Позволяет сжимать до 0
        
        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(15, 15, 15, 15)
        sidebar_layout.setSpacing(10)

        # Заголовок боковой панели и кнопка "Сканировать"
        title_layout = QHBoxLayout()
        self.sidebar_title = QLabel()
        self.sidebar_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF;")
        title_layout.addWidget(self.sidebar_title)

        self.scan_btn = QPushButton()
        self.scan_btn.clicked.connect(self.run_input_scan)
        self.scan_btn.setStyleSheet("font-weight: bold; min-width: 90px;")
        title_layout.addWidget(self.scan_btn)
        
        sidebar_layout.addLayout(title_layout)

        # Дерево QTreeWidget
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.itemChanged.connect(self.on_item_changed)
        sidebar_layout.addWidget(self.tree_widget)

        # Метка статуса выбора
        self.selection_label = QLabel()
        self.selection_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #A0A0A0;")
        sidebar_layout.addWidget(self.selection_label)

        self.splitter.addWidget(self.sidebar_frame)

        # ----------------------------------------------------
        # 2. Правая основная панель
        # ----------------------------------------------------
        self.content_frame = QFrame()
        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(20, 15, 20, 15)
        content_layout.setSpacing(12)

        # Верхняя панель (Заголовок и Языковой переключатель)
        top_layout = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #FFFFFF;")
        top_layout.addWidget(self.title_label)

        # Слайдер переключения языков
        resources_dir = self.project_root / "themes"
        self.lang_switch = LanguageSwitch(self.content_frame, self.change_language, self.current_lang, resources_dir)
        top_layout.addWidget(self.lang_switch)
        
        content_layout.addLayout(top_layout)

        # Создаем вертикальный разделитель для правой панели
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)

        # Группа 1: Выбор папок
        folder_frame = QFrame()
        folder_frame.setObjectName("groupFrame")
        folder_layout = QGridLayout(folder_frame)
        folder_layout.setContentsMargins(15, 15, 15, 15)
        folder_layout.setSpacing(10)

        # Иконки кнопок папок
        self.img_create = QIcon(str(resources_dir / "create_folder.png"))
        self.img_open_in = QIcon(str(resources_dir / "open_folder_input.png"))
        self.img_open_out = QIcon(str(resources_dir / "open_folder_output.png"))

        # Папка ввода
        self.btn_create_in = QPushButton()
        self.btn_create_in.setIcon(self.img_create)
        self.btn_create_in.setFixedSize(30, 30)
        self.btn_create_in.clicked.connect(lambda: self.ask_and_create_folder("input"))
        folder_layout.addWidget(self.btn_create_in, 0, 0)

        self.input_label = QLabel()
        self.input_label.setStyleSheet("font-weight: bold; color: #FFFFFF;")
        folder_layout.addWidget(self.input_label, 0, 1)

        self.input_entry = QLineEdit()
        self.input_entry.setText(self.saved_input_path)
        folder_layout.addWidget(self.input_entry, 0, 2)

        self.btn_open_in = QPushButton()
        self.btn_open_in.setIcon(self.img_open_in)
        self.btn_open_in.setFixedSize(30, 30)
        self.btn_open_in.clicked.connect(self.open_input_dir)
        folder_layout.addWidget(self.btn_open_in, 0, 3)

        self.btn_browse_in = QPushButton()
        self.btn_browse_in.clicked.connect(self.browse_input)
        self.btn_browse_in.setFixedWidth(100)
        folder_layout.addWidget(self.btn_browse_in, 0, 4)

        # Папка вывода
        self.btn_create_out = QPushButton()
        self.btn_create_out.setIcon(self.img_create)
        self.btn_create_out.setFixedSize(30, 30)
        self.btn_create_out.clicked.connect(lambda: self.ask_and_create_folder("output"))
        folder_layout.addWidget(self.btn_create_out, 1, 0)

        self.output_label = QLabel()
        self.output_label.setStyleSheet("font-weight: bold; color: #FFFFFF;")
        folder_layout.addWidget(self.output_label, 1, 1)

        self.output_entry = QLineEdit()
        self.output_entry.setText(self.saved_output_path)
        folder_layout.addWidget(self.output_entry, 1, 2)

        self.btn_open_out = QPushButton()
        self.btn_open_out.setIcon(self.img_open_out)
        self.btn_open_out.setFixedSize(30, 30)
        self.btn_open_out.clicked.connect(self.open_output_dir)
        folder_layout.addWidget(self.btn_open_out, 1, 3)

        self.btn_browse_out = QPushButton()
        self.btn_browse_out.clicked.connect(self.browse_output)
        self.btn_browse_out.setFixedWidth(100)
        folder_layout.addWidget(self.btn_browse_out, 1, 4)



        # Группа 2: Настройки оптимизации
        settings_frame = QFrame()
        settings_frame.setObjectName("groupFrame")
        settings_layout = QGridLayout(settings_frame)
        settings_layout.setContentsMargins(15, 15, 15, 15)
        settings_layout.setSpacing(10)

        self.settings_title = QLabel()
        self.settings_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")
        settings_layout.addWidget(self.settings_title, 0, 0, 1, 2)

        self.cb_new_uids = QCheckBox()
        self.cb_new_uids.setChecked(True)
        settings_layout.addWidget(self.cb_new_uids, 1, 0)

        self.cb_split_mf = QCheckBox()
        self.cb_split_mf.setChecked(True)
        settings_layout.addWidget(self.cb_split_mf, 1, 1)

        self.cb_clean_tags = QCheckBox()
        self.cb_clean_tags.setChecked(True)
        settings_layout.addWidget(self.cb_clean_tags, 2, 0)

        self.cb_default_tags = QCheckBox()
        self.cb_default_tags.setChecked(True)
        settings_layout.addWidget(self.cb_default_tags, 2, 1)

        self.cb_explicit_vr = QCheckBox()
        self.cb_explicit_vr.setChecked(True)
        settings_layout.addWidget(self.cb_explicit_vr, 3, 0)

        self.cb_exclude_reports = QCheckBox()
        self.cb_exclude_reports.setChecked(True)
        settings_layout.addWidget(self.cb_exclude_reports, 3, 1)

        self.cb_split_series = QCheckBox()
        self.cb_split_series.setChecked(True)
        settings_layout.addWidget(self.cb_split_series, 4, 0)



        # Группа 3: Лог выполнения
        log_frame = QFrame()
        log_frame.setObjectName("groupFrame")
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(15, 15, 15, 15)
        log_layout.setSpacing(8)

        self.log_title = QLabel()
        self.log_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")
        log_layout.addWidget(self.log_title)

        self.log_textbox = QTextEdit()
        self.log_textbox.setReadOnly(True)
        self.log_textbox.setFont(QFont("Consolas", 10))
        log_layout.addWidget(self.log_textbox)

        # Добавляем элементы в вертикальный разделитель по очереди
        self.right_splitter.addWidget(folder_frame)
        self.right_splitter.addWidget(settings_frame)
        self.right_splitter.addWidget(log_frame)

        content_layout.addWidget(self.right_splitter)

        # Группа 4: Прогресс и Кнопка пуска
        control_frame = QFrame()
        control_layout = QVBoxLayout(control_frame)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(24)
        control_layout.addWidget(self.progress_bar)

        self.start_btn = QPushButton()
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setFixedHeight(40)
        self.start_btn.clicked.connect(self.start_processing)
        control_layout.addWidget(self.start_btn)

        content_layout.addWidget(control_frame)

        self.splitter.addWidget(self.content_frame)
        main_layout.addWidget(self.splitter)

        # Настройки сплиттеров
        self.splitter.setCollapsible(0, True)   # Дерево может быть скрыто полностью
        self.splitter.setCollapsible(1, False)  # Главную панель скрывать нельзя
        self.splitter.setSizes([220, 880])      # Пропорции по умолчанию (220px ширина дерева)

        self.right_splitter.setCollapsible(0, True)  # Папки можно скрыть
        self.right_splitter.setCollapsible(1, True)  # Настройки можно скрыть
        self.right_splitter.setCollapsible(2, True)  # Лог можно скрыть
        
        # Настройка растяжения: папки и настройки не растягиваются, лог растягивается
        self.right_splitter.setStretchFactor(0, 0)
        self.right_splitter.setStretchFactor(1, 0)
        self.right_splitter.setStretchFactor(2, 1)

        self.right_splitter.setSizes([90, 135, 245])     # Размеры по умолчанию

    def apply_styles(self) -> None:
        QApplication.instance().setStyleSheet("""
            QMainWindow {
                background-color: #121212;
            }
            QDialog {
                background-color: #1A1A1A;
                border: 1px solid #2D2D2D;
            }
            QWidget {
                color: #D1D5DB;
                font-family: "Segoe UI", Arial, sans-serif;
            }
            #sidebar {
                background-color: #1A1A1A;
                border-right: 1px solid #2D2D2D;
            }
            #groupFrame {
                background-color: #1A1A1A;
                border: 1px solid #2D2D2D;
                border-radius: 8px;
            }
            QTreeWidget {
                background-color: #121212;
                border: 1px solid #2D2D2D;
                border-radius: 6px;
                padding: 5px;
            }
            QTreeWidget::item {
                padding: 6px 4px;
                color: #E5E7EB;
            }
            QTreeWidget::item:hover {
                background-color: #2A2A2A;
                border-radius: 4px;
            }
            QTreeWidget::item:selected {
                background-color: #3B82F6;
                color: #FFFFFF;
                border-radius: 4px;
            }
            QPushButton {
                background-color: #2A2A2A;
                border: 1px solid #374151;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                color: #E5E7EB;
            }
            QPushButton:hover {
                background-color: #374151;
                border-color: #4B5563;
            }
            QPushButton:pressed {
                background-color: #1F2937;
            }
            QPushButton#startBtn {
                background-color: #2563EB;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: bold;
                border: none;
            }
            QPushButton#startBtn:hover {
                background-color: #3B82F6;
            }
            QPushButton#startBtn:pressed {
                background-color: #1D4ED8;
            }
            QPushButton#stopBtn {
                background-color: #EF4444;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: bold;
                border: none;
            }
            QPushButton#stopBtn:hover {
                background-color: #F87171;
            }
            QPushButton#stopBtn:pressed {
                background-color: #B91C1C;
            }
            QLineEdit {
                background-color: #121212;
                border: 1px solid #2D2D2D;
                border-radius: 6px;
                padding: 6px 10px;
                color: #F3F4F6;
            }
            QLineEdit:focus {
                border-color: #3B82F6;
            }
            QTextEdit {
                background-color: #121212;
                border: 1px solid #2D2D2D;
                border-radius: 6px;
                color: #E5E7EB;
            }
            QProgressBar {
                background-color: #151515;
                border: 1px solid #333333;
                border-radius: 6px;
                text-align: center;
                color: #E5E7EB;
                font-weight: bold;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #3B82F6, stop:1 #8B5CF6);
                border-radius: 5px;
            }
            QCheckBox {
                spacing: 8px;
                color: #D1D5DB;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #4B5563;
                border-radius: 4px;
                background-color: #121212;
            }
            QCheckBox::indicator:hover {
                border-color: #3B82F6;
            }
            QCheckBox::indicator:checked {
                background-color: #2563EB;
                border-color: #2563EB;
            }
            QSplitter::handle {
                background-color: #2D2D2D;
            }
            QSplitter::handle:horizontal {
                width: 4px;
            }
            QSplitter::handle:vertical {
                height: 4px;
            }
            QSplitter::handle:hover {
                background-color: #3B82F6;
            }
            QToolTip {
                background-color: #1A1A1A;
                color: #E5E7EB;
                border: 1px solid #374151;
                border-radius: 4px;
                padding: 4px;
            }
        """)

    # Методы обзора и открытия папок
    def browse_input(self) -> None:
        initial = self.input_entry.text()
        if "Введите путь" in initial or "Enter path" in initial:
            initial = ""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Input Directory", initial)
        if dir_path:
            self.input_entry.setText(str(Path(dir_path).resolve()))
            self.save_last_paths()

    def browse_output(self) -> None:
        initial = self.output_entry.text()
        if "Введите путь" in initial or "Enter path" in initial:
            initial = ""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory", initial)
        if dir_path:
            self.output_entry.setText(str(Path(dir_path).resolve()))
            self.save_last_paths()

    def open_input_dir(self) -> None:
        inp_dir = self.input_entry.text()
        if "Введите путь" in inp_dir or "Enter path" in inp_dir:
            self.bridge.log_signal.emit(self.loc("error_input_path_not_set"), "error")
            return
            
        path = Path(inp_dir)
        if path.exists():
            import os
            os.startfile(path)
        else:
            self.bridge.log_signal.emit(self.loc("error_input_not_exist_warning", path), "warning")

    def open_output_dir(self) -> None:
        out_dir = self.output_entry.text()
        if "Введите путь" in out_dir or "Enter path" in out_dir:
            self.bridge.log_signal.emit(self.loc("error_output_path_not_set"), "error")
            return
            
        path = Path(out_dir)
        if path.exists():
            import os
            os.startfile(path)
        else:
            self.bridge.log_signal.emit(self.loc("error_output_not_exist", path), "warning")

    def ask_and_create_folder(self, dir_type: str) -> None:
        folder_name = "Dicom_input" if dir_type == "input" else "Dicom_output"
        message = self.loc("ask_create_folder", folder_name)
        
        dialog = CustomQuestionDialog(self, self.loc("dialog_title"), message)
        dialog.exec()
        result = dialog.result_value
        
        if not result or result == "no":
            return
            
        if getattr(sys, "frozen", False):
            app_dir = Path(sys.executable).parent
        else:
            app_dir = Path(__file__).resolve().parents[2]
            
        input_path = app_dir / "Dicom_input"
        output_path = app_dir / "Dicom_output"
        
        if result == "yes":
            target_path = input_path if dir_type == "input" else output_path
            try:
                target_path.mkdir(parents=True, exist_ok=True)
                if dir_type == "input":
                    self.input_entry.setText(str(target_path.resolve()))
                else:
                    self.output_entry.setText(str(target_path.resolve()))
                self.bridge.log_signal.emit(self.loc("folder_created", target_path.resolve()), "success")
            except Exception as e:
                self.bridge.log_signal.emit(self.loc("error_create_folder", e), "error")
                
        elif result == "both":
            try:
                input_path.mkdir(parents=True, exist_ok=True)
                output_path.mkdir(parents=True, exist_ok=True)
                self.input_entry.setText(str(input_path.resolve()))
                self.output_entry.setText(str(output_path.resolve()))
                self.bridge.log_signal.emit(self.loc("folders_created_both", input_path.resolve(), output_path.resolve()), "success")
            except Exception as e:
                self.bridge.log_signal.emit(self.loc("error_create_folders_both", e), "error")
                
        self.save_last_paths()

    # Методы обработки сигналов от процессора
    def add_log(self, text: str, tag: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = "white"
        if tag == "warning":
            color = "#ffb347"
        elif tag == "error":
            color = "#ff6961"
        elif tag == "success":
            color = "#77dd77"
        formatted_text = f"<span style='color:#a0a0a0;'>[{timestamp}]</span> <span style='color:{color};'>{text}</span>"
        self.log_textbox.append(formatted_text)

    def update_progress(self, current: int, total: int) -> None:
        if total > 0:
            prog = current / total
            pct = int(prog * 100)
            self.progress_bar.setValue(pct)

    def update_scan_progress(self, current: int, total: int) -> None:
        if self.scan_dialog:
            self.scan_dialog.update_progress(current, total)

    def on_processing_finished(self) -> None:
        self.is_processing = False
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setText(self.loc("run_optimization"))
        self.start_btn.setEnabled(True)
        self.apply_styles() # Обновит стиль (вернет синий цвет кнопки)
        self.set_gui_enabled(True)

    def on_tree_scanned(self, tree_data: dict) -> None:
        self.populate_tree(tree_data)
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText(self.loc("scan_input"))
        self.update_selection_label()
        if self.scan_dialog:
            self.scan_dialog.accept()
            self.scan_dialog = None

    def set_gui_enabled(self, enabled: bool) -> None:
        self.start_btn.setEnabled(enabled)

    # Работа с QTreeWidget
    def populate_tree(self, tree_data: dict) -> None:
        self._is_updating_tree = True
        self.tree_widget.clear()
        
        for (pat_name, pat_id), studies in sorted(tree_data.items(), key=lambda x: str(x[0])):
            # Пациент
            pat_label = f"{pat_name} [{pat_id}]"
            pat_item = QTreeWidgetItem(self.tree_widget)
            pat_item.setText(0, pat_label)
            pat_item.setCheckState(0, Qt.CheckState.Checked)
            pat_item.setData(0, Qt.ItemDataRole.UserRole, ("patient", pat_name, pat_id))
            
            for (study_date, study_desc, study_uid), series_dict in sorted(studies.items(), key=lambda x: str(x[0])):
                # Исследование
                study_label = f"{study_date} - {study_desc}" if study_date else study_desc
                study_item = QTreeWidgetItem(pat_item)
                study_item.setText(0, study_label)
                study_item.setCheckState(0, Qt.CheckState.Checked)
                study_item.setData(0, Qt.ItemDataRole.UserRole, ("study", study_uid))
                
                for (series_label, s_uid, seg_idx), files in sorted(series_dict.items(), key=lambda x: str(x[0])):
                    # Серия
                    series_item = QTreeWidgetItem(study_item)
                    series_item.setText(0, series_label)
                    series_item.setCheckState(0, Qt.CheckState.Checked)
                    # Сохраняем информацию о файлах серии
                    series_item.setData(0, Qt.ItemDataRole.UserRole, ("series", s_uid, seg_idx, files))

        self.tree_widget.expandAll()
        self._is_updating_tree = False

    def on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._is_updating_tree:
            return
        
        self._is_updating_tree = True
        try:
            state = item.checkState(0)
            self._set_children_state(item, state)
            self._update_parent_states(item)
        finally:
            self._is_updating_tree = False
        
        self.update_selection_label()

    def _set_children_state(self, item: QTreeWidgetItem, state: Qt.CheckState) -> None:
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            self._set_children_state(child, state)

    def _update_parent_states(self, item: QTreeWidgetItem) -> None:
        parent = item.parent()
        if not parent:
            return
            
        checked_count = 0
        unchecked_count = 0
        
        for i in range(parent.childCount()):
            child = parent.child(i)
            c_state = child.checkState(0)
            if c_state == Qt.CheckState.Checked:
                checked_count += 1
            elif c_state == Qt.CheckState.Unchecked:
                unchecked_count += 1
                
        if checked_count == parent.childCount():
            parent.setCheckState(0, Qt.CheckState.Checked)
        elif unchecked_count == parent.childCount():
            parent.setCheckState(0, Qt.CheckState.Unchecked)
        else:
            parent.setCheckState(0, Qt.CheckState.PartiallyChecked)
            
        self._update_parent_states(parent)

    def get_selected_files(self) -> list:
        selected_files = []
        for i in range(self.tree_widget.topLevelItemCount()):
            pat_item = self.tree_widget.topLevelItem(i)
            for j in range(pat_item.childCount()):
                study_item = pat_item.child(j)
                for k in range(study_item.childCount()):
                    series_item = study_item.child(k)
                    if series_item.checkState(0) == Qt.CheckState.Checked:
                        data = series_item.data(0, Qt.ItemDataRole.UserRole)
                        if data and data[0] == "series":
                            selected_files.extend(data[3])
        return selected_files

    def get_patient_nodes_data(self) -> list:
        nodes = []
        for i in range(self.tree_widget.topLevelItemCount()):
            pat_item = self.tree_widget.topLevelItem(i)
            data = pat_item.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "patient":
                nodes.append((pat_item, data[1], data[2])) # item, name, id
        return nodes

    def update_selection_label(self) -> None:
        selected_files = self.get_selected_files()
        
        total_patients = self.tree_widget.topLevelItemCount()
        total_studies = 0
        total_series = 0
        total_files_count = 0
        
        for i in range(total_patients):
            pat_item = self.tree_widget.topLevelItem(i)
            total_studies += pat_item.childCount()
            for j in range(pat_item.childCount()):
                study_item = pat_item.child(j)
                total_series += study_item.childCount()
                for k in range(study_item.childCount()):
                    series_item = study_item.child(k)
                    data = series_item.data(0, Qt.ItemDataRole.UserRole)
                    if data and data[0] == "series":
                        total_files_count += len(data[3])
                        
        text = self.loc("selected_status", len(selected_files), total_files_count, total_patients, total_studies, total_series)
        self.selection_label.setText(text)

    # Запуск сканирования входной папки
    def run_input_scan(self) -> None:
        input_path = self.input_entry.text()
        if not input_path or "Введите путь" in input_path or "Enter path" in input_path:
            return

        path = Path(input_path)
        if not path.exists():
            return

        self.scan_btn.setEnabled(False)
        self.scan_btn.setText(self.loc("tree_loading"))
        self.selection_label.setText(self.loc("tree_loading"))
        
        self.scan_stop_event = threading.Event()
        self.scan_dialog = ScanProgressDialog(self, self.scan_stop_event)
        
        threading.Thread(target=self._scan_thread, args=(path, self.scan_stop_event), daemon=True).start()
        self.scan_dialog.exec()

    def _scan_thread(self, path: Path, stop_event: threading.Event) -> None:
        temp_config = ProcessingConfig(
            new_uids=False, split_multiframe=False, clean_tags=False,
            default_tags=False, explicit_vr=False, exclude_reports=False,
            split_series=self.cb_split_series.isChecked()
        )
        logger = QtLogger(self.bridge)
        processor = DicomProcessor(path, self.output_entry.text(), temp_config, logger, stop_event, lang=self.current_lang)
        
        try:
            tree_data = processor.scan_input_directory()
            self.bridge.tree_scanned_signal.emit(tree_data)
        except Exception as e:
            self.bridge.log_signal.emit(f"Error scanning directory: {e}", "error")
            self.bridge.tree_scanned_signal.emit({})

    def get_selected_files_or_autoscan(self) -> list:
        selected_files = self.get_selected_files()
        if not selected_files and self.tree_widget.topLevelItemCount() == 0:
            input_path = self.input_entry.text()
            if not input_path or "Введите путь" in input_path or "Enter path" in input_path:
                return []
            path = Path(input_path)
            if not path.exists():
                return []
            
            temp_config = ProcessingConfig(
                new_uids=False, split_multiframe=False, clean_tags=False,
                default_tags=False, explicit_vr=False, exclude_reports=False,
                split_series=self.cb_split_series.isChecked()
            )
            logger = QtLogger(self.bridge)
            processor = DicomProcessor(path, self.output_entry.text(), temp_config, logger, threading.Event(), lang=self.current_lang)
            try:
                tree_data = processor.scan_input_directory()
                self.populate_tree(tree_data)
                selected_files = self.get_selected_files()
            except Exception:
                pass
        return selected_files

    # Главный поток обработки
    def start_processing(self) -> None:
        if self.is_processing:
            self.stop_event.set()
            self.start_btn.setText(self.loc("status_stopping"))
            self.start_btn.setEnabled(False)
            return

        input_raw = self.input_entry.text()
        output_raw = self.output_entry.text()

        if ("Введите путь" in input_raw or "Enter path" in input_raw or 
            "Введите путь" in output_raw or "Enter path" in output_raw):
            self.add_log(self.loc('error_paths_not_set'), "error")
            return

        input_dir = Path(input_raw)
        output_dir = Path(output_raw)

        if not input_dir.exists():
            self.add_log(self.loc('error_input_not_exist', input_dir), "error")
            return

        selected_files = self.get_selected_files_or_autoscan()
        if not selected_files:
            self.add_log(self.loc('tree_empty'), "error")
            return

        # Интерактивная валидация данных пациента
        patient_overrides = {}
        patient_nodes = self.get_patient_nodes_data()
        for p_item, pat_name, pat_id in patient_nodes:
            any_selected = False
            for j in range(p_item.childCount()):
                study_item = p_item.child(j)
                for k in range(study_item.childCount()):
                    series_item = study_item.child(k)
                    if series_item.checkState(0) == Qt.CheckState.Checked:
                        any_selected = True
                        break
            if not any_selected:
                continue

            is_valid = True
            if not pat_name or pat_name.strip() == "" or pat_name.upper() == "UNKNOWN":
                is_valid = False
            if not pat_id or pat_id.strip() == "" or pat_id.upper() == "UNKNOWN":
                is_valid = False
            if len(pat_name) > 64 or len(pat_id) > 64:
                is_valid = False

            if not is_valid:
                dialog = PatientEditDialog(self, pat_name, pat_id)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    new_name = dialog.new_name.strip()
                    new_id = dialog.new_id.strip()
                    if new_name and new_id:
                        patient_overrides[(pat_name, pat_id)] = (new_name, new_id)

        self.is_processing = True
        self.stop_event.clear()
        
        self.start_btn.setObjectName("stopBtn")
        self.start_btn.setText(self.loc("stop_optimization"))
        self.apply_styles() # Обновит стиль (сделает кнопку красной)
        
        self.progress_bar.setValue(0)
        self.log_textbox.clear()

        config = ProcessingConfig(
            new_uids=self.cb_new_uids.isChecked(),
            split_multiframe=self.cb_split_mf.isChecked(),
            clean_tags=self.cb_clean_tags.isChecked(),
            default_tags=self.cb_default_tags.isChecked(),
            explicit_vr=self.cb_explicit_vr.isChecked(),
            exclude_reports=self.cb_exclude_reports.isChecked(),
            split_series=self.cb_split_series.isChecked()
        )

        logger = QtLogger(self.bridge)
        processor = DicomProcessor(
            input_dir, output_dir, config, logger, self.stop_event, 
            lang=self.current_lang, selected_files=selected_files,
            patient_overrides=patient_overrides
        )

        threading.Thread(
            target=self._run_processor, 
            args=(processor,), 
            daemon=True
        ).start()

    def _run_processor(self, processor: DicomProcessor) -> None:
        try:
            processor.process()
        finally:
            self.bridge.finished_signal.emit()
