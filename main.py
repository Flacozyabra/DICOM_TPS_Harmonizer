import sys
import traceback
from PyQt6.QtWidgets import QApplication
from src.gui.app import DicomSplitterApp

def log_uncaught_exceptions(ex_type, ex_value, ex_traceback):
    tb = "".join(traceback.format_exception(ex_type, ex_value, ex_traceback))
    print("CRITICAL ERROR: Uncaught exception:", tb, file=sys.stderr)
    sys.__excepthook__(ex_type, ex_value, ex_traceback)

sys.excepthook = log_uncaught_exceptions

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DicomSplitterApp()
    window.show()
    sys.exit(app.exec())

