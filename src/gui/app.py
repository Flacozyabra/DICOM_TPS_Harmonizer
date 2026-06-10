from datetime import datetime
import json
import os
import sys
import platform
import threading
import urllib.request
import re
import math
from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QSize, QPoint, QByteArray, QThread, QPointF, QRect
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QLineEdit, QCheckBox, QProgressBar,
    QTextEdit, QTreeWidget, QTreeWidgetItem, QFileDialog, QDialog,
    QGridLayout, QMessageBox, QApplication, QSplitter, QSizePolicy,
    QSlider, QStackedWidget, QComboBox
)
from PyQt6.QtGui import QIcon, QFont, QTextCursor, QPixmap, QBrush, QColor, QPainter, QPen, QImage

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
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        lbl.setStyleSheet("font-size: 13px; color: #E5E7EB;")
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


class UpdateCheckerThread(QThread):
    """Поток для проверки обновлений с GitHub в фоне, чтобы избежать зависания."""
    update_available = pyqtSignal(str, str) # tag_name, html_url

    def __init__(self, current_version: str) -> None:
        super().__init__()
        self.current_version = current_version

    def run(self) -> None:
        url = "https://github.com/Flacozyabra/DICOM_TPS_Harmonizer/releases/latest"
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as response:
                final_url = response.geturl()
                match = re.search(r'/releases/tag/([^/]+)', final_url)
                if match:
                    tag_name = match.group(1)
                    if self.is_newer(tag_name, self.current_version):
                        self.update_available.emit(tag_name, final_url)
        except Exception:
            pass

    def is_newer(self, latest: str, current: str) -> bool:
        def parse_version(v: str) -> tuple[int, ...]:
            v_clean = re.sub(r'[^\d.]', '', v)
            parts = v_clean.split('.')
            while len(parts) < 3:
                parts.append('0')
            try:
                return tuple(int(x) for x in parts[:3])
            except ValueError:
                return (0, 0, 0)
        return parse_version(latest) > parse_version(current)


class DicomViewerWidget(QWidget):
    """Виджет для отрисовки DICOM-изображения и линейки."""
    slice_scrolled = pyqtSignal(int)  # -1 или 1 для прокрутки колесиком мыши
    window_changed = pyqtSignal(float, float) # новые window_width, window_center

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.current_pixmap = None
        self.current_dataset = None
        self.image_rect = None

        # Сведения о срезах для OSD-оверлея
        self.current_slice = 0
        self.total_slices = 0

        # Параметры окна HU
        self.window_width = 400.0
        self.window_center = 40.0

        # Управление зумом и панорамированием
        self.zoom_factor = 1.0
        self.pan_offset = QPointF(0, 0)
        self.last_mouse_pos = None

        # Режимы работы левой кнопки мыши
        self.ruler_active = False
        self.hu_active = False

        # Состояния рисования линейки
        self.start_pos = None
        self.current_pos = None
        self.drawing_line = False
        self.ruler_close_rect = None

        # Состояние изменения окна
        self.windowing_active = False

        # Состояние панорамирования (Pan)
        self.pan_active = False

        self.setMouseTracking(True)
        self.setStyleSheet("background-color: #000000;")

    def set_dicom_image(self, pixmap: QPixmap, ds) -> None:
        self.current_pixmap = pixmap
        self.current_dataset = ds
        self.update()

    def set_window_params(self, width: float, center: float) -> None:
        self.window_width = width
        self.window_center = center
        self.update()

    def set_slice_info(self, current: int, total: int) -> None:
        self.current_slice = current
        self.total_slices = total
        self.update()

    def clear_viewer(self) -> None:
        self.current_pixmap = None
        self.current_dataset = None
        self.start_pos = None
        self.current_pos = None
        self.drawing_line = False
        self.ruler_close_rect = None
        self.windowing_active = False
        self.pan_active = False
        self.zoom_factor = 1.0
        self.pan_offset = QPointF(0, 0)
        self.current_slice = 0
        self.total_slices = 0
        self.update()

    def mousePressEvent(self, event) -> None:
        if not self.current_pixmap:
            return

        btn = event.button()
        pos = event.position()

        # Проверяем клик по крестику закрытия линейки
        if btn == Qt.MouseButton.LeftButton and self.ruler_active and self.ruler_close_rect and self.ruler_close_rect.contains(pos.toPoint()):
            self.start_pos = None
            self.current_pos = None
            self.drawing_line = False
            self.ruler_close_rect = None
            self.update()
            return

        if btn in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            # Панорамирование (Pan) при зажатии средней или правой кнопки мыши
            self.pan_active = True
            self.last_mouse_pos = event.position()
        elif btn == Qt.MouseButton.LeftButton:
            if self.ruler_active:
                # Рисование линейки
                self.start_pos = event.position()
                self.current_pos = event.position()
                self.drawing_line = True
                self.update()
            elif self.hu_active:
                # Изменение окна HU
                self.windowing_active = True
                self.last_mouse_pos = event.position()

    def mouseMoveEvent(self, event) -> None:
        if self.pan_active and self.last_mouse_pos:
            delta = event.position() - self.last_mouse_pos
            self.pan_offset += delta
            self.last_mouse_pos = event.position()
            self.update()
        elif self.drawing_line:
            self.current_pos = event.position()
            self.update()
        elif self.windowing_active and self.last_mouse_pos:
            delta = event.position() - self.last_mouse_pos
            self.last_mouse_pos = event.position()
            
            # По горизонтали меняем ширину окна (Width), по вертикали - уровень (Center)
            self.window_width = max(1.0, self.window_width + delta.x() * 2.0)
            self.window_center = self.window_center + delta.y() * 2.0
            self.window_changed.emit(self.window_width, self.window_center)

    def mouseReleaseEvent(self, event) -> None:
        btn = event.button()
        if btn in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self.pan_active = False
        elif btn == Qt.MouseButton.LeftButton:
            if self.drawing_line:
                self.current_pos = event.position()
                self.drawing_line = False
                self.update()
            elif self.windowing_active:
                self.windowing_active = False

    def wheelEvent(self, event) -> None:
        modifiers = QApplication.keyboardModifiers()
        if modifiers == Qt.KeyboardModifier.ControlModifier:
            # Масштабирование по Ctrl + колесо мыши
            delta = event.angleDelta().y()
            if delta > 0:
                # Колесо вперед (от себя) -> уменьшение
                self.zoom_factor = max(0.1, self.zoom_factor - 0.1)
            elif delta < 0:
                # Колесо назад (на себя) -> увеличение
                self.zoom_factor = min(10.0, self.zoom_factor + 0.1)
            self.update()
        else:
            # Обычная прокрутка колесиком -> смена срезов
            delta = event.angleDelta().y()
            if delta > 0:
                self.slice_scrolled.emit(-1)
            elif delta < 0:
                self.slice_scrolled.emit(1)

    def to_image_coords(self, pt: QPointF) -> tuple[float, float]:
        if not self.image_rect or not self.current_pixmap:
            return 0.0, 0.0

        x_w = pt.x()
        y_w = pt.y()

        offset_x = self.image_rect.x()
        offset_y = self.image_rect.y()
        view_w = self.image_rect.width()
        view_h = self.image_rect.height()

        pix_w = self.current_pixmap.width()
        pix_h = self.current_pixmap.height()

        x_img = (x_w - offset_x) * (pix_w / view_w)
        y_img = (y_w - offset_y) * (pix_h / view_h)

        x_img = max(0.0, min(float(pix_w), x_img))
        y_img = max(0.0, min(float(pix_h), y_img))

        return x_img, y_img

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))

        if self.current_pixmap:
            pix_w = self.current_pixmap.width()
            pix_h = self.current_pixmap.height()
            w = self.width()
            h = self.height()

            scale = min(w / pix_w, h / pix_h) * self.zoom_factor
            view_w = int(pix_w * scale)
            view_h = int(pix_h * scale)

            # Центр виджета + смещение панорамирования
            offset_x = (w - view_w) // 2 + int(self.pan_offset.x())
            offset_y = (h - view_h) // 2 + int(self.pan_offset.y())

            self.image_rect = QRect(offset_x, offset_y, view_w, view_h)
            painter.drawPixmap(self.image_rect, self.current_pixmap)

            # Отрисовка измерительной линейки
            if self.ruler_active and self.start_pos and self.current_pos:
                pen = QPen(QColor("#10B981"), 2, Qt.PenStyle.SolidLine)
                painter.setPen(pen)
                painter.drawLine(self.start_pos.toPoint(), self.current_pos.toPoint())

                self.draw_tick(painter, self.start_pos, self.current_pos)
                self.draw_tick(painter, self.current_pos, self.start_pos)

                x1, y1 = self.to_image_coords(self.start_pos)
                x2, y2 = self.to_image_coords(self.current_pos)

                row_spacing = 1.0
                col_spacing = 1.0
                if self.current_dataset:
                    pixel_spacing = getattr(self.current_dataset, "PixelSpacing", None)
                    if pixel_spacing and len(pixel_spacing) == 2:
                        row_spacing = float(pixel_spacing[0])
                        col_spacing = float(pixel_spacing[1])
                    else:
                        imager_spacing = getattr(self.current_dataset, "ImagerPixelSpacing", None)
                        if imager_spacing and len(imager_spacing) == 2:
                            row_spacing = float(imager_spacing[0])
                            col_spacing = float(imager_spacing[1])

                dx = (x2 - x1) * col_spacing
                dy = (y2 - y1) * row_spacing
                dist_mm = math.sqrt(dx * dx + dy * dy)

                text_dist = f"{dist_mm:.1f} мм"
                mid_x = (self.start_pos.x() + self.current_pos.x()) / 2
                mid_y = (self.start_pos.y() + self.current_pos.y()) / 2

                font = QFont("Consolas", 10, QFont.Weight.Bold)
                painter.setFont(font)
                metrics = painter.fontMetrics()
                rect_dist = metrics.boundingRect(text_dist)

                padding_x = 4
                padding_y = 2
                cross_width = 12
                space = 6

                total_w = rect_dist.width() + cross_width + space
                total_h = max(rect_dist.height(), cross_width)

                rect_plate = QRect(
                    int(mid_x - total_w / 2 - padding_x),
                    int(mid_y - 15 - total_h / 2 - padding_y),
                    int(total_w + padding_x * 2),
                    int(total_h + padding_y * 2)
                )

                # Рисуем подложку
                painter.fillRect(rect_plate, QColor(0, 0, 0, 180))

                # Рисуем текст
                painter.setPen(QColor("#FFFFFF"))
                text_rect = QRect(
                    rect_plate.x() + padding_x,
                    rect_plate.y() + padding_y,
                    rect_dist.width(),
                    total_h
                )
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text_dist)

                # Рисуем крестик [X]
                cross_rect = QRect(
                    text_rect.x() + text_rect.width() + space,
                    rect_plate.y() + (rect_plate.height() - cross_width) // 2,
                    cross_width,
                    cross_width
                )
                self.ruler_close_rect = cross_rect

                pen_cross = QPen(QColor("#EF4444"), 2, Qt.PenStyle.SolidLine)
                painter.setPen(pen_cross)
                margin = 2
                painter.drawLine(
                    cross_rect.x() + margin, cross_rect.y() + margin,
                    cross_rect.x() + cross_rect.width() - margin, cross_rect.y() + cross_rect.height() - margin
                )
                painter.drawLine(
                    cross_rect.x() + cross_rect.width() - margin, cross_rect.y() + margin,
                    cross_rect.x() + margin, cross_rect.y() + cross_rect.height() - margin
                )
            else:
                self.ruler_close_rect = None

            # Отрисовка метаданных пациента/серии в левом верхнем углу (OSD)
            if self.current_dataset:
                painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
                
                pat_name = str(getattr(self.current_dataset, "PatientName", "Unknown"))
                pat_id = str(getattr(self.current_dataset, "PatientID", "Unknown"))
                
                # Форматируем дату рождения
                dob_raw = getattr(self.current_dataset, "PatientBirthDate", "")
                dob = ""
                if dob_raw and len(dob_raw) == 8:
                    dob = f"{dob_raw[6:8]}-{dob_raw[4:6]}-{dob_raw[0:4]}"
                else:
                    dob = dob_raw
                sex = getattr(self.current_dataset, "PatientSex", "")
                pat_info = f"{dob} {sex}".strip()
                
                study_desc = getattr(self.current_dataset, "StudyDescription", "")
                series_desc = getattr(self.current_dataset, "SeriesDescription", "")
                
                top_lines = [pat_name, pat_id, pat_info, study_desc, series_desc]
                top_lines = [line for line in top_lines if line] # убираем пустые
                
                y_offset = 15
                for line in top_lines:
                    metrics = painter.fontMetrics()
                    rect_line = metrics.boundingRect(line)
                    rect_line.moveTopLeft(QPoint(15, y_offset))
                    painter.fillRect(rect_line.adjusted(-4, -2, 4, 2), QColor(0, 0, 0, 150))
                    painter.setPen(QColor("#E5E7EB"))
                    painter.drawText(rect_line, Qt.AlignmentFlag.AlignLeft, line)
                    y_offset += rect_line.height() + 5

            # Вывод параметров окна HU, Zoom, Modality и Transfer Syntax в левый нижний угол
            painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            
            lines_bottom = []
            lines_bottom.append(f"WL: {int(self.window_center)} WW: {int(self.window_width)} | Zoom: {int(self.zoom_factor * 100)}%")
            
            if self.current_dataset:
                modality = getattr(self.current_dataset, "Modality", "")
                if modality:
                    lines_bottom.append(f"Modality: {modality}")
                
                try:
                    ts_uid = getattr(self.current_dataset, "original_transfer_syntax", None)
                    if not ts_uid:
                        ts_uid = self.current_dataset.file_meta.TransferSyntaxUID
                    ts_name = ts_uid.name
                    if " (" in ts_name:
                        ts_name = ts_name.split(" (")[0]
                    lines_bottom.append(f"TS: {ts_name}")
                except Exception:
                    pass

            metrics_b = painter.fontMetrics()
            y_offset_b = self.height() - 15
            for line in reversed(lines_bottom):
                rect_info = metrics_b.boundingRect(line)
                rect_info.moveBottomLeft(QPoint(15, y_offset_b))
                painter.fillRect(rect_info.adjusted(-4, -2, 4, 2), QColor(0, 0, 0, 150))
                painter.setPen(QColor("#E5E7EB"))
                painter.drawText(rect_info, Qt.AlignmentFlag.AlignLeft, line)
                y_offset_b -= rect_info.height() + 5

            # Отрисовка номера среза в правом нижнем углу
            if self.total_slices > 0:
                painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
                slice_info = ""
                if hasattr(self, "parent") and hasattr(self.parent(), "parent_app"):
                    slice_info = self.parent().parent_app.loc("viewer_slice", self.current_slice, self.total_slices)
                else:
                    slice_info = f"Slice: {self.current_slice} / {self.total_slices}"
                
                metrics_r = painter.fontMetrics()
                rect_slice = metrics_r.boundingRect(slice_info)
                rect_slice.moveBottomRight(QPoint(self.width() - 15, self.height() - 15))
                painter.fillRect(rect_slice.adjusted(-4, -2, 4, 2), QColor(0, 0, 0, 150))
                painter.setPen(QColor("#E5E7EB"))
                painter.drawText(rect_slice, Qt.AlignmentFlag.AlignRight, slice_info)

    def draw_tick(self, painter: QPainter, pt1: QPointF, pt2: QPointF) -> None:
        dx = pt2.x() - pt1.x()
        dy = pt2.y() - pt1.y()
        length = math.sqrt(dx*dx + dy*dy)
        if length < 1.0:
            return
        px = -dy / length
        py = dx / length
        
        tick_len = 8
        p1 = QPoint(int(pt1.x() + px * tick_len), int(pt1.y() + py * tick_len))
        p2 = QPoint(int(pt1.x() - px * tick_len), int(pt1.y() - py * tick_len))
        painter.drawLine(p1, p2)


class DicomViewerPanel(QWidget):
    """Панель управления просмотром DICOM серий."""
    close_requested = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.parent_app = parent
        self.sorted_files = []
        self.current_index = -1
        self.is_loading = False

        # Параметры окна по умолчанию
        self.window_width = 400.0
        self.window_center = 40.0
        self.default_wc = 40.0
        self.default_ww = 400.0

        self.setup_ui()

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 0)
        layout.setSpacing(6)

        # 1.  Верхняя панель (Информация о серии, Кнопка линейки, Кнопка HU, Выбор пресетов, Кнопка закрыть)
        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)
        
        self.lbl_info = QLabel(self)
        self.lbl_info.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")
        self.lbl_info.hide() # Скрываем, так как информация теперь выводится на оверлее вьюера
        top_layout.addWidget(self.lbl_info)

        top_layout.addStretch()

        # Выпадающий список пресетов HU
        self.cb_presets = QComboBox(self)
        self.cb_presets.setFixedWidth(200)
        self.cb_presets.setStyleSheet("""
            QComboBox {
                background-color: #2A2A2A;
                border: 1px solid #374151;
                border-radius: 4px;
                color: #FFFFFF;
                padding: 4px 8px;
                font-size: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #1A1A1A;
                border: 1px solid #374151;
                color: #FFFFFF;
                selection-background-color: #3B82F6;
            }
        """)
        top_layout.addWidget(self.cb_presets)

        # Создаем программные иконки
        self.img_ruler = self.create_ruler_icon()
        self.img_hu = self.create_hu_icon()

        # Кнопка линейки
        self.btn_ruler = QPushButton(self)
        self.btn_ruler.setIcon(self.img_ruler)
        self.btn_ruler.setIconSize(QSize(20, 20))
        self.btn_ruler.setToolTip(self.parent_app.loc("tooltip_ruler") if hasattr(self.parent_app, "loc") else "Линейка")
        self.btn_ruler.clicked.connect(self.toggle_ruler)
        top_layout.addWidget(self.btn_ruler)

        # Кнопка настройки HU
        self.btn_hu = QPushButton(self)
        self.btn_hu.setIcon(self.img_hu)
        self.btn_hu.setIconSize(QSize(20, 20))
        self.btn_hu.setToolTip(self.parent_app.loc("tooltip_hu") if hasattr(self.parent_app, "loc") else "Настройка окна HU")
        self.btn_hu.clicked.connect(self.toggle_hu)
        top_layout.addWidget(self.btn_hu)

        # Кнопка закрытия
        self.btn_close = QPushButton(self.parent_app.loc("viewer_close"), self)
        self.btn_close.clicked.connect(self.close_requested.emit)
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: #374151;
                border: 1px solid #4B5563;
                color: #FFFFFF;
                padding: 5px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4B5563;
            }
        """)
        top_layout.addWidget(self.btn_close)
        
        layout.addLayout(top_layout)

        # 2.  Центральная область (Изображение и шкала HU справа)
        main_layout = QHBoxLayout()
        main_layout.setSpacing(15)

        self.viewer = DicomViewerWidget(self)
        self.viewer.slice_scrolled.connect(self.on_slice_scrolled)
        self.viewer.window_changed.connect(self.on_window_changed)
        main_layout.addWidget(self.viewer, stretch=1)

        # Создаем и добавляем шкалу HU справа
        self.setup_hu_panel()
        main_layout.addWidget(self.hu_panel)

        layout.addLayout(main_layout)

        # 2.5 Горизонтальный слайдер срезов снизу
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.valueChanged.connect(self.on_slider_changed)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #1F2937;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #3B82F6;
                width: 30px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #60A5FA;
            }
        """)
        layout.addWidget(self.slider)

        # Инициализируем локализованные пресеты
        self.update_buttons_style()
        self.retranslate_ui()
        self.cb_presets.currentIndexChanged.connect(self.apply_preset)

    def setup_hu_panel(self) -> None:
        self.hu_panel = QFrame(self)
        self.hu_panel.setFixedWidth(200)
        self.hu_panel.setStyleSheet("""
            QFrame {
                background-color: #1F2937;
                border: 1px solid #374151;
                border-radius: 6px;
            }
            QLabel {
                border: none;
                background: transparent;
                color: #E5E7EB;
            }
            QSlider::groove:horizontal {
                background: #111827;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #10B981;
                width: 16px;
                margin-top: -6px;
                margin-bottom: -6px;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #34D399;
            }
        """)
        panel_layout = QVBoxLayout(self.hu_panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(12)

        # Заголовок
        self.lbl_hu_title = QLabel("Параметры HU", self.hu_panel)
        self.lbl_hu_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #FFFFFF;")
        panel_layout.addWidget(self.lbl_hu_title)

        # Window Center (Level)
        panel_layout.addSpacing(5)
        self.lbl_wc_val = QLabel("Level: 40", self.hu_panel)
        self.lbl_wc_val.setStyleSheet("font-size: 12px; font-weight: bold;")
        panel_layout.addWidget(self.lbl_wc_val)

        self.slider_wc = QSlider(Qt.Orientation.Horizontal, self.hu_panel)
        self.slider_wc.setRange(-1000, 3000)
        self.slider_wc.setValue(40)
        self.slider_wc.valueChanged.connect(self.on_panel_wc_changed)
        panel_layout.addWidget(self.slider_wc)

        # Window Width
        panel_layout.addSpacing(5)
        self.lbl_ww_val = QLabel("Width: 400", self.hu_panel)
        self.lbl_ww_val.setStyleSheet("font-size: 12px; font-weight: bold;")
        panel_layout.addWidget(self.lbl_ww_val)

        self.slider_ww = QSlider(Qt.Orientation.Horizontal, self.hu_panel)
        self.slider_ww.setRange(1, 4000)
        self.slider_ww.setValue(400)
        self.slider_ww.valueChanged.connect(self.on_panel_ww_changed)
        panel_layout.addWidget(self.slider_ww)

        panel_layout.addStretch()
        self.hu_panel.hide()

    def on_panel_wc_changed(self, value: int) -> None:
        self.window_center = float(value)
        self.lbl_wc_val.setText(self.parent_app.loc("hu_level", value) if hasattr(self.parent_app, "loc") else f"Level: {value}")
        self.update_current_slice_pixels()

    def on_panel_ww_changed(self, value: int) -> None:
        self.window_width = float(value)
        self.lbl_ww_val.setText(self.parent_app.loc("hu_width", value) if hasattr(self.parent_app, "loc") else f"Width: {value}")
        self.update_current_slice_pixels()

    def retranslate_ui(self) -> None:
        self.cb_presets.blockSignals(True)
        self.cb_presets.clear()
        self.cb_presets.addItem(self.parent_app.loc("preset_dicom"), "dicom")
        self.cb_presets.addItem(self.parent_app.loc("preset_soft"), "soft")
        self.cb_presets.addItem(self.parent_app.loc("preset_bone"), "bone")
        self.cb_presets.addItem(self.parent_app.loc("preset_lung"), "lung")
        self.cb_presets.addItem(self.parent_app.loc("preset_brain"), "brain")
        self.cb_presets.blockSignals(False)

        self.btn_ruler.setToolTip(self.parent_app.loc("tooltip_ruler") if hasattr(self.parent_app, "loc") else "Линейка")
        self.btn_hu.setToolTip(self.parent_app.loc("tooltip_hu") if hasattr(self.parent_app, "loc") else "Настройка окна HU")

        if hasattr(self, "hu_panel"):
            self.lbl_hu_title.setText(self.parent_app.loc("hu_panel_title") if hasattr(self.parent_app, "loc") else "Параметры HU")
            self.lbl_wc_val.setText(self.parent_app.loc("hu_level", int(self.slider_wc.value())) if hasattr(self.parent_app, "loc") else f"Level: {int(self.slider_wc.value())}")
            self.lbl_ww_val.setText(self.parent_app.loc("hu_width", int(self.slider_ww.value())) if hasattr(self.parent_app, "loc") else f"Width: {int(self.slider_ww.value())}")

    def create_ruler_icon(self) -> QIcon:
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        pen = QPen(QColor("#FFFFFF"), 2)
        painter.setPen(pen)
        painter.drawLine(3, 21, 21, 3)
        
        painter.drawLine(1, 19, 5, 23)
        painter.drawLine(19, 1, 23, 5)
        
        pen_ticks = QPen(QColor("#3B82F6"), 1.5)
        painter.setPen(pen_ticks)
        painter.drawLine(6, 18, 9, 21)
        painter.drawLine(12, 12, 15, 15)
        painter.drawLine(18, 6, 21, 9)
        
        painter.end()
        return QIcon(pixmap)

    def create_hu_icon(self) -> QIcon:
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.drawChord(2, 2, 20, 20, -90 * 16, 180 * 16)
        
        painter.setBrush(QBrush(Qt.GlobalColor.transparent))
        painter.drawChord(2, 2, 20, 20, 90 * 16, 180 * 16)
        
        painter.end()
        return QIcon(pixmap)

    def update_buttons_style(self) -> None:
        style_ruler_active = """
            QPushButton {
                background-color: #3B82F6;
                border: 1px solid #60A5FA;
                border-radius: 4px;
                min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
            }
        """
        style_ruler_inactive = """
            QPushButton {
                background-color: #374151;
                border: 1px solid #4B5563;
                border-radius: 4px;
                min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
            }
            QPushButton:hover { background-color: #4B5563; }
        """
        style_hu_active = """
            QPushButton {
                background-color: #10B981;
                border: 1px solid #34D399;
                border-radius: 4px;
                min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
            }
        """
        style_hu_inactive = """
            QPushButton {
                background-color: #374151;
                border: 1px solid #4B5563;
                border-radius: 4px;
                min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
            }
            QPushButton:hover { background-color: #4B5563; }
        """

        self.btn_ruler.setStyleSheet(style_ruler_active if self.viewer.ruler_active else style_ruler_inactive)
        self.btn_hu.setStyleSheet(style_hu_active if self.viewer.hu_active else style_hu_inactive)

    def toggle_ruler(self) -> None:
        active = not self.viewer.ruler_active
        self.viewer.ruler_active = active
        if active:
            self.viewer.hu_active = False
            if hasattr(self, "hu_panel"):
                self.hu_panel.hide()
        self.update_buttons_style()

    def toggle_hu(self) -> None:
        active = not self.viewer.hu_active
        self.viewer.hu_active = active
        if active:
            self.viewer.ruler_active = False
            if hasattr(self, "hu_panel"):
                self.hu_panel.show()
        else:
            if hasattr(self, "hu_panel"):
                self.hu_panel.hide()
        self.update_buttons_style()

    def load_series(self, files: list[str]) -> None:
        import pydicom
        self.is_loading = True
        self.sorted_files = []
        self.current_index = -1
        self.viewer.clear_viewer()

        # По умолчанию сбрасываем пресеты в "dicom"
        self.cb_presets.blockSignals(True)
        self.cb_presets.setCurrentIndex(0)
        self.cb_presets.blockSignals(False)

        slices = []
        for f in files:
            try:
                # Быстрое сканирование тегов для сортировки
                ds = pydicom.dcmread(f, stop_before_pixels=True)
                
                ipp = getattr(ds, "ImagePositionPatient", None)
                z_coord = float(ipp[2]) if ipp and len(ipp) >= 3 else 0.0
                instance_number = int(getattr(ds, "InstanceNumber", 0))
                slices.append((f, z_coord, instance_number))
            except Exception:
                pass

        if not slices:
            self.lbl_info.setText("Серия не содержит корректных DICOM файлов.")
            self.viewer.set_slice_info(0, 0)
            self.is_loading = False
            return

        # Сортируем срезы по Z-координате
        slices.sort(key=lambda x: (x[1], x[2]))
        self.sorted_files = [x[0] for x in slices]

        self.slider.setRange(0, len(self.sorted_files) - 1)
        self.is_loading = False
        
        self.set_current_slice(0)

    def read_truncated_dicom(self, filepath: str):
        import pydicom
        import io
        import numpy as np
        
        # Сначала читаем метаданные с stop_before_pixels=True, чтобы узнать Transfer Syntax и размер
        ds_meta = pydicom.dcmread(filepath, stop_before_pixels=True)
        transfer_syntax = ds_meta.file_meta.TransferSyntaxUID
        
        with open(filepath, "rb") as f:
            file_bytes = bytearray(f.read())
            
        # Определяем, сжатый ли формат пикселей
        is_compressed = transfer_syntax.startswith("1.2.840.10008.1.2.4.") or "rle" in getattr(ds_meta.file_meta, "TransferSyntaxUID_name", "").lower()
        
        if is_compressed:
            # Ищем маркер конца JPEG (FF D9) в конце файла
            has_eoi = file_bytes.endswith(b"\xff\xd9") or b"\xff\xd9" in file_bytes[-20:]
            if not has_eoi:
                file_bytes.extend(b"\xff\xd9")
                
            # Добавим Sequence Delimiter (FE FF DD E0 00 00 00 00), если его нет в конце
            has_delim = b"\xfe\xff\xdd\xe0" in file_bytes[-20:]
            if not has_delim:
                file_bytes.extend(b"\xfe\xff\xdd\xe0\x00\x00\x00\x00")
        else:
            # Несжатые пиксели - дополняем нулями до ожидаемого размера
            rows = getattr(ds_meta, "Rows", 512)
            cols = getattr(ds_meta, "Columns", 512)
            bits = getattr(ds_meta, "BitsAllocated", 16)
            expected_pixels = rows * cols * (bits // 8)
            if len(file_bytes) < expected_pixels:
                file_bytes.extend(b"\x00" * (expected_pixels * 2))
                
        # Читаем из BytesIO
        bio = io.BytesIO(file_bytes)
        ds = pydicom.dcmread(bio)
        
        # Чтобы убедиться, что при обращении к pixel_array не упадет, пробуем прочесть его.
        # Если упадет (например, JPEG данные повреждены внутри), подкладываем черный кадр.
        try:
            _ = ds.pixel_array
        except Exception:
            rows = getattr(ds, "Rows", 512)
            cols = getattr(ds, "Columns", 512)
            bits = getattr(ds, "BitsAllocated", 16)
            pixel_repr = getattr(ds, "PixelRepresentation", 0)
            if bits == 16:
                dtype = np.int16 if pixel_repr == 1 else np.uint16
            else:
                dtype = np.int8 if pixel_repr == 1 else np.uint8
            arr = np.zeros((rows, cols), dtype=dtype)
            
            # Динамически переопределяем класс для этого конкретного экземпляра
            class TruncatedDataset(type(ds)):
                @property
                def pixel_array(self):
                    return getattr(self, "_pixel_array", None)
            
            ds._pixel_array = arr
            ds.__class__ = TruncatedDataset
            
        return ds



    def set_current_slice(self, index: int) -> None:
        if index < 0 or index >= len(self.sorted_files):
            return

        self.current_index = index
        self.slider.setValue(index)

        filepath = self.sorted_files[index]
        import pydicom
        try:
            # Читаем файл. Сначала пробуем обычное чтение.
            try:
                ds = pydicom.dcmread(filepath)
                if not hasattr(ds, "pixel_array") or len(ds) == 0:
                    raise ValueError("Empty dataset or missing pixel array")
            except Exception:
                # Если обычное чтение упало, пробуем восстановить частично поврежденный файл
                ds = self.read_truncated_dicom(filepath)

            # Извлекаем параметры окна по умолчанию при первой загрузке серии
            if self.current_index == 0:
                self.default_wc = 40.0
                self.default_ww = 400.0
                wc = getattr(ds, "WindowCenter", None)
                ww = getattr(ds, "WindowWidth", None)
                if wc is not None and ww is not None:
                    try:
                        c_val = wc[0] if hasattr(wc, "__iter__") else wc
                        w_val = ww[0] if hasattr(ww, "__iter__") else ww
                        self.default_wc = float(c_val)
                        self.default_ww = float(w_val)
                    except Exception:
                        pass
                
                # При первом запуске серии используем DICOM пресет
                preset_data = self.cb_presets.currentData()
                if preset_data == "dicom":
                    self.window_center = self.default_wc
                    self.window_width = self.default_ww

            pat_name = getattr(ds, "PatientName", "Unknown")
            pat_id = getattr(ds, "PatientID", "Unknown")
            study_desc = getattr(ds, "StudyDescription", "")
            series_desc = getattr(ds, "SeriesDescription", "")
            
            info_text = f"{pat_name} [{pat_id}] | {study_desc} | {series_desc}"
            self.lbl_info.setText(info_text)
            self.viewer.set_slice_info(index + 1, len(self.sorted_files))

            pixmap = self.dicom_to_pixmap(ds, self.window_width, self.window_center)
            if pixmap:
                self.viewer.set_dicom_image(pixmap, ds)
                self.viewer.set_window_params(self.window_width, self.window_center)
            else:
                raise ValueError("Failed to decode pixel array to pixmap")
                
        except Exception as e:
            # Автоматическая защита от битых файлов: выбрасываем его из списка и пробуем открыть тот же индекс
            print(f"[Viewer] Skipping corrupted file {filepath}: {str(e)}")
            self.sorted_files.pop(index)
            if not self.sorted_files:
                self.lbl_info.setText("Нет доступных изображений в серии.")
                self.viewer.set_slice_info(0, 0)
                self.viewer.clear_viewer()
                return

            self.slider.setRange(0, len(self.sorted_files) - 1)
            new_index = min(index, len(self.sorted_files) - 1)
            self.set_current_slice(new_index)

    def on_slider_changed(self, value: int) -> None:
        if not self.is_loading and value != self.current_index:
            self.set_current_slice(value)

    def on_slice_scrolled(self, step: int) -> None:
        new_index = self.current_index + step
        if 0 <= new_index < len(self.sorted_files):
            self.set_current_slice(new_index)

    def on_window_changed(self, width: float, center: float) -> None:
        self.window_width = width
        self.window_center = center
        if hasattr(self, "hu_panel"):
            self.slider_wc.blockSignals(True)
            self.slider_ww.blockSignals(True)
            
            wc_val = max(-1000, min(int(center), 3000))
            ww_val = max(1, min(int(width), 4000))
            
            self.slider_wc.setValue(wc_val)
            self.slider_ww.setValue(ww_val)
            
            self.lbl_wc_val.setText(self.parent_app.loc("hu_level", wc_val) if hasattr(self.parent_app, "loc") else f"Level: {wc_val}")
            self.lbl_ww_val.setText(self.parent_app.loc("hu_width", ww_val) if hasattr(self.parent_app, "loc") else f"Width: {ww_val}")
            
            self.slider_wc.blockSignals(False)
            self.slider_ww.blockSignals(False)
        self.update_current_slice_pixels()

    def update_current_slice_pixels(self) -> None:
        if self.current_index < 0 or self.current_index >= len(self.sorted_files):
            return
        filepath = self.sorted_files[self.current_index]
        import pydicom
        try:
            ds = pydicom.dcmread(filepath)
            pixmap = self.dicom_to_pixmap(ds, self.window_width, self.window_center)
            if pixmap:
                self.viewer.set_dicom_image(pixmap, ds)
                self.viewer.set_window_params(self.window_width, self.window_center)
        except Exception:
            pass

    def apply_preset(self, index: int) -> None:
        preset_type = self.cb_presets.itemData(index)
        
        if preset_type == "dicom":
            self.window_width = self.default_ww
            self.window_center = self.default_wc
        elif preset_type == "soft":
            self.window_width = 400.0
            self.window_center = 40.0
        elif preset_type == "bone":
            self.window_width = 1500.0
            self.window_center = 300.0
        elif preset_type == "lung":
            self.window_width = 1500.0
            self.window_center = -600.0
        elif preset_type == "brain":
            self.window_width = 80.0
            self.window_center = 40.0

        self.on_window_changed(self.window_width, self.window_center)

    def dicom_to_pixmap(self, ds, window_width: float, window_center: float) -> QPixmap | None:
        try:
            import numpy as np
            if not hasattr(ds, "pixel_array"):
                return None

            original_ts = getattr(ds.file_meta, "TransferSyntaxUID", None)
            if original_ts and not hasattr(ds, "original_transfer_syntax"):
                ds.original_transfer_syntax = original_ts

            try:
                ds.decompress()
            except Exception:
                pass

            arr = ds.pixel_array.astype(float)
            slope = float(getattr(ds, "RescaleSlope", 1.0))
            intercept = float(getattr(ds, "RescaleIntercept", 0.0))
            arr = arr * slope + intercept

            min_val = window_center - window_width / 2.0
            max_val = window_center + window_width / 2.0

            arr = np.clip(arr, min_val, max_val)
            arr = ((arr - min_val) / (max_val - min_val) * 255.0).astype(np.uint8)

            height, width = arr.shape
            bytes_per_line = width

            self._temp_arr = np.ascontiguousarray(arr)
            qimg = QImage(self._temp_arr.data, width, height, bytes_per_line, QImage.Format.Format_Grayscale8)
            return QPixmap.fromImage(qimg)
        except Exception:
            return None


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
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
                self.parent.loc("dialog_scan_progress", current, total)
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

        # Состояние вьюера
        self.viewer_active = False
        self.current_view_series_uid = None
        self.current_view_seg_idx = None

        # Создание интерфейса
        self.create_widgets()
        self.apply_styles()
        self.update_locale_texts()
        self.center_on_screen()
        self.restore_window_state()

        self.VERSION = "1.1.0"
        self.check_updates()

    def check_updates(self) -> None:
        """Запускает фоновый поток для проверки обновлений с GitHub."""
        config_file = self.get_config_path()
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("skip_update_check", False):
                        return
            except Exception:
                pass

        self.update_thread = UpdateCheckerThread(self.VERSION)
        self.update_thread.update_available.connect(self.on_update_available)
        self.update_thread.start()

    def on_update_available(self, new_version: str, release_url: str) -> None:
        """Показывает диалог предложения обновить программу при обнаружении новой версии."""
        dialog = UpdateDialog(self, new_version)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.result_value
            if result == "yes":
                import webbrowser
                try:
                    webbrowser.open(release_url)
                except Exception:
                    pass
            elif result == "skip":
                self.save_skip_update_check()

    def save_skip_update_check(self) -> None:
        """Сохраняет флаг отключения проверки обновлений в config.json."""
        config_file = self.get_config_path()
        config_data = {}
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
            except Exception:
                pass
        config_data["skip_update_check"] = True
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

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
        self.sidebar_frame.setMaximumWidth(450) # Ограничивает максимальную ширину дерева при ресайзе
        
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
        self.tree_widget.itemClicked.connect(self.on_item_clicked)
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

        # Оборачиваем правую часть в QStackedWidget для переключения вьюера
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self.content_frame) # Страница 0
        
        self.viewer_panel = DicomViewerPanel(self)
        self.viewer_panel.close_requested.connect(self.close_viewer)
        self.right_stack.addWidget(self.viewer_panel) # Страница 1
        
        self.splitter.addWidget(self.right_stack)
        main_layout.addWidget(self.splitter)

        # Настройки сплиттеров
        self.splitter.setCollapsible(0, True)   # Дерево может быть скрыто полностью
        self.splitter.setCollapsible(1, False)  # Главную панель скрывать нельзя
        self.splitter.setSizes([365, 735])      # Пропорции по умолчанию (365px ширина дерева)
        self.splitter.setStretchFactor(0, 1)    # Дерево проводника растягивается при увеличении окна
        self.splitter.setStretchFactor(1, 0)    # Правая область сохраняет свой размер

        self.right_splitter.setCollapsible(0, True)  # Папки можно скрыть
        self.right_splitter.setCollapsible(1, True)  # Настройки можно скрыть
        self.right_splitter.setCollapsible(2, True)  # Лог можно скрыть
        
        # Настройка растяжения: папки и настройки не растягиваются, лог растягивается
        self.right_splitter.setStretchFactor(0, 0)
        self.right_splitter.setStretchFactor(1, 0)
        self.right_splitter.setStretchFactor(2, 1)

        self.right_splitter.setSizes([90, 135, 245])     # Размеры по умолчанию

    def apply_styles(self) -> None:
        arrow_right = (self.project_root / "themes" / "arrow_right.png").as_posix()
        arrow_down = (self.project_root / "themes" / "arrow_down.png").as_posix()
        chk_checked = (self.project_root / "themes" / "checkbox_checked.png").as_posix()

        qss = """
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
            QTreeView::branch,
            QTreeWidget::branch {
                background-color: transparent;
                border-image: none;
                image: none;
            }
            QTreeView::branch:has-children:closed,
            QTreeView::branch:has-children:closed:has-siblings,
            QTreeWidget::branch:has-children:closed,
            QTreeWidget::branch:has-children:closed:has-siblings {
                border-image: none;
                image: url(PATH_ARROW_RIGHT);
            }
            QTreeView::branch:has-children:open,
            QTreeView::branch:has-children:open:has-siblings,
            QTreeWidget::branch:has-children:open,
            QTreeWidget::branch:has-children:open:has-siblings {
                border-image: none;
                image: url(PATH_ARROW_DOWN);
            }
            QTreeWidget::indicator, QTreeView::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #4B5563;
                border-radius: 3px;
                background-color: #121212;
            }
            QTreeWidget::indicator:hover, QTreeView::indicator:hover {
                border-color: #3B82F6;
            }
            QTreeWidget::indicator:checked, QTreeView::indicator:checked {
                background-color: #2563EB;
                border-color: #2563EB;
                image: url(PATH_CHECKBOX_CHECKED);
            }
            QTreeWidget::indicator:unchecked, QTreeView::indicator:unchecked {
                background-color: #121212;
                border-color: #4B5563;
            }
            QScrollBar:vertical {
                border: none;
                background: #121212;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #374151;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4B5563;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                border: none;
                background: #121212;
                height: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:horizontal {
                background: #374151;
                min-width: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #4B5563;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                border: none;
                background: none;
                width: 0px;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
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
        """.replace("PATH_ARROW_RIGHT", arrow_right)\
           .replace("PATH_ARROW_DOWN", arrow_down)\
           .replace("PATH_CHECKBOX_CHECKED", chk_checked)

        QApplication.instance().setStyleSheet(qss)

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
        self.tree_widget.resizeColumnToContents(0)
        needed_width = self.tree_widget.columnWidth(0) + 60
        needed_width = max(220, min(needed_width, 600))
        sizes = self.splitter.sizes()
        if len(sizes) >= 2:
            total = sum(sizes)
            sizes[0] = needed_width
            sizes[1] = total - needed_width
            self.splitter.setSizes(sizes)
        self._is_updating_tree = False

    def on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Обрабатывает клик на элемент дерева. Если кликнули на серию - открывает/закрывает вьюер."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or not isinstance(data, tuple):
            return
            
        if data[0] == "series":
            s_uid = data[1]
            seg_idx = data[2]
            files = data[3]
            
            # Если вьюер уже открыт для этой же серии, закрываем его
            if self.viewer_active and self.current_view_series_uid == s_uid and self.current_view_seg_idx == seg_idx:
                self.close_viewer()
            else:
                self.open_viewer(s_uid, seg_idx, files)

    def open_viewer(self, s_uid: str, seg_idx: int, files: list[str]) -> None:
        """Переключает правую панель на вьюер и загружает серию."""
        self.viewer_active = True
        self.current_view_series_uid = s_uid
        self.current_view_seg_idx = seg_idx
        
        self.viewer_panel.load_series(files)
        self.right_stack.setCurrentIndex(1) # Переключаем на страницу вьюера

    def close_viewer(self) -> None:
        """Сворачивает вьюер и возвращает исходный интерфейс."""
        self.viewer_active = False
        self.current_view_series_uid = None
        self.current_view_seg_idx = None
        
        # Сбрасываем инструменты вьюера и скрываем hu_panel
        self.viewer_panel.viewer.ruler_active = False
        self.viewer_panel.viewer.hu_active = False
        if hasattr(self.viewer_panel, "hu_panel"):
            self.viewer_panel.hu_panel.hide()
        self.viewer_panel.update_buttons_style()
        
        self.right_stack.setCurrentIndex(0) # Переключаем на исходный интерфейс
        self.tree_widget.clearSelection()   # Снимаем выделение в дереве

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
