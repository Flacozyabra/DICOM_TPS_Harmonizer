"""Точка входа в приложение DICOM TPS Harmonizer.

Инициализирует графический интерфейс пользователя на PyQt6 и запускает главный цикл событий.
"""

import sys
from PyQt6.QtWidgets import QApplication
from src.gui.app import DicomSplitterApp

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DicomSplitterApp()
    window.show()
    sys.exit(app.exec())
