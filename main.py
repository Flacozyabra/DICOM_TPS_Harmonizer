import multiprocessing
import sys
import traceback

# Глобальный перехватчик необработанных исключений
def log_uncaught_exceptions(ex_type, ex_value, ex_traceback):
    tb = "".join(traceback.format_exception(ex_type, ex_value, ex_traceback))
    print("CRITICAL ERROR: Uncaught exception:", tb, file=sys.stderr)
    sys.__excepthook__(ex_type, ex_value, ex_traceback)

sys.excepthook = log_uncaught_exceptions


def _show_startup_error(message: str, stderr_details: str) -> None:
    """Display a modal Windows error box (with stderr fallback) on fatal startup failure."""
    try:
        import ctypes
        title = "Ошибка запуска / Startup Error"
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        print(f"ERROR: {stderr_details}", file=sys.stderr)


if __name__ == "__main__":
    multiprocessing.freeze_support()

    from src.utils.qt_compat import QtBackendError, init_qt_backend

    try:
        init_qt_backend()
    except QtBackendError as e:
        details = str(e)
        msg = (
            "Не удалось запустить приложение, так как в системе отсутствуют необходимые библиотеки C++ "
            "или компоненты Qt несовместимы с текущей версией Windows.\n\n"
            "Пожалуйста, установите Microsoft Visual C++ Redistributable (2015-2022) x64 или "
            "используйте совместимую версию DICOM_TPS_Harmonizer_Legacy.exe.\n\n"
            f"Детали ошибки: {details}"
        )
        _show_startup_error(
            msg,
            f"Microsoft Visual C++ Redistributable (2015-2022) or compatible Qt runtime required. Details: {details}",
        )
        sys.exit(1)

    # Очистка старых версий файлов после бесшовного автообновления
    try:
        from src.utils.updater import cleanup_old_exe
        cleanup_old_exe()
    except Exception:
        pass

    try:
        from PyQt6.QtWidgets import QApplication
        from src.gui.app import DicomSplitterApp
    except ImportError as e:
        _show_startup_error(
            f"Не удалось загрузить модули приложения.\n\nДетали ошибки: {e}",
            f"Failed to import application modules: {e}",
        )
        sys.exit(1)

    app = QApplication(sys.argv)
    window = DicomSplitterApp()
    window.show()
    sys.exit(app.exec())

