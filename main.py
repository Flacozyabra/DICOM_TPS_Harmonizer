"""Точка входа в приложение DICOM TPS Harmonizer.

Инициализирует графический интерфейс пользователя и запускает главный цикл событий.
"""

from src.gui.app import DicomSplitterApp

if __name__ == "__main__":
    app = DicomSplitterApp()
    app.mainloop()
