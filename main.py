import sys
import traceback

# Глобальный перехватчик необработанных исключений
def log_uncaught_exceptions(ex_type, ex_value, ex_traceback):
    tb = "".join(traceback.format_exception(ex_type, ex_value, ex_traceback))
    print("CRITICAL ERROR: Uncaught exception:", tb, file=sys.stderr)
    sys.__excepthook__(ex_type, ex_value, ex_traceback)

sys.excepthook = log_uncaught_exceptions

# Проверяем импорт PyQt6 и зависимостей C++ (MSVC++ Redistributable)
try:
    from PyQt6.QtWidgets import QApplication
    from src.gui.app import DicomSplitterApp
    pyqt_available = True
    import_error_msg = ""
except ImportError as e:
    pyqt_available = False
    import_error_msg = str(e)

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    if not pyqt_available:
        try:
            import ctypes
            title = "Ошибка запуска / Startup Error"
            message = (
                "Не удалось запустить приложение, так как в системе отсутствуют необходимые библиотеки C++.\n\n"
                "Пожалуйста, установите распространяемый пакет Microsoft Visual C++ Redistributable (2015-2022).\n"
                "Его можно бесплатно загрузить с официального сайта Microsoft.\n\n"
                f"Детали ошибки: {import_error_msg}"
            )
            # MB_OK = 0x0, MB_ICONERROR = 0x10
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
        except Exception:
            print("ERROR: Microsoft Visual C++ Redistributable (2015-2022) is required to run this application.", file=sys.stderr)
            print(f"Details: {import_error_msg}", file=sys.stderr)
        sys.exit(1)

    app = QApplication(sys.argv)
    window = DicomSplitterApp()
    window.show()
    sys.exit(app.exec())

