"""Qt backend initialization and PyQt6-to-PyQt5 compatibility shim.

Allows the codebase written against PyQt6 APIs to run seamlessly under PyQt5
(including Python 3.8 legacy builds for older Windows versions).
"""

import os
import sys
from typing import Optional, Tuple


class QtBackendError(ImportError):
    """Raised when neither PyQt6 nor PyQt5 can be imported."""

    def __init__(self, pyqt6_error: Optional[Exception], pyqt5_error: Optional[Exception]) -> None:
        self.pyqt6_error = pyqt6_error
        self.pyqt5_error = pyqt5_error
        parts = []
        if pyqt6_error is not None:
            parts.append(f"PyQt6: {pyqt6_error}")
        if pyqt5_error is not None:
            parts.append(f"PyQt5: {pyqt5_error}")
        super().__init__("; ".join(parts) if parts else "No Qt backend available")


def _alias_enum_namespaces(cls: object, attr_names: Tuple[str, ...]) -> None:
    """Expose nested PyQt6-style enum namespaces on a PyQt5 class."""
    for name in attr_names:
        if not hasattr(cls, name):
            setattr(cls, name, cls)


def install_pyqt5_shim() -> None:
    """Import PyQt5, patch PyQt6-compatible enum namespaces/methods, and register sys.modules aliases."""
    import PyQt5
    import PyQt5.QtCore
    import PyQt5.QtGui
    import PyQt5.QtWidgets

    _alias_enum_namespaces(
        PyQt5.QtCore.Qt,
        (
            "AlignmentFlag", "CheckState", "ContextMenuPolicy", "Corner",
            "CursorShape", "ItemDataRole", "ItemFlag", "KeyboardModifier",
            "Orientation", "ScrollBarPolicy", "SortOrder", "TextInteractionFlag",
            "WindowModality", "WindowType", "WidgetAttribute", "AspectRatioMode",
            "TransformationMode", "MouseButton", "Key", "ApplicationAttribute",
            "ConnectionType", "DockWidgetArea", "ToolBarArea", "FillRule",
            "PenStyle", "PenCapStyle", "PenJoinStyle", "BrushStyle",
            "DropAction", "FocusPolicy", "MatchFlag", "ScreenOrientation",
            "GlobalColor",
        ),
    )

    class_enum_aliases = (
        (PyQt5.QtCore.QEvent, ("Type",)),
        (PyQt5.QtCore.QEasingCurve, ("Type",)),
        (PyQt5.QtCore.QSettings, ("Format",)),
        (PyQt5.QtGui.QImage, ("Format",)),
        (PyQt5.QtGui.QPainter, ("RenderHint", "CompositionMode")),
        (PyQt5.QtGui.QFont, ("Weight",)),
        (PyQt5.QtGui.QPalette, ("ColorGroup", "ColorRole")),
        (PyQt5.QtGui.QTextCursor, ("MoveOperation",)),
        (PyQt5.QtWidgets.QAbstractItemView, ("EditTrigger", "SelectionBehavior", "SelectionMode")),
        (PyQt5.QtWidgets.QTabBar, ("ButtonPosition",)),
        (PyQt5.QtWidgets.QHeaderView, ("ResizeMode",)),
        (PyQt5.QtWidgets.QLineEdit, ("EchoMode",)),
        (PyQt5.QtWidgets.QAbstractSpinBox, ("ButtonSymbols",)),
        (PyQt5.QtWidgets.QDialog, ("DialogCode",)),
        (PyQt5.QtWidgets.QMessageBox, ("ButtonRole", "Icon", "StandardButton")),
        (PyQt5.QtWidgets.QSizePolicy, ("Policy",)),
        (PyQt5.QtWidgets.QFrame, ("Shape", "Shadow")),
    )
    for target_cls, attrs in class_enum_aliases:
        _alias_enum_namespaces(target_cls, attrs)

    # QAction / QActionGroup moved from QtWidgets (PyQt5) to QtGui (PyQt6)
    if not hasattr(PyQt5.QtGui, "QAction"):
        PyQt5.QtGui.QAction = PyQt5.QtWidgets.QAction
    if hasattr(PyQt5.QtWidgets, "QActionGroup") and not hasattr(PyQt5.QtGui, "QActionGroup"):
        PyQt5.QtGui.QActionGroup = PyQt5.QtWidgets.QActionGroup

    # QMouseEvent.position() in PyQt6 corresponds to QMouseEvent.localPos() in PyQt5
    if not hasattr(PyQt5.QtGui.QMouseEvent, "position"):
        PyQt5.QtGui.QMouseEvent.position = lambda self: self.localPos()

    # Enable High-DPI scaling before QApplication is constructed
    PyQt5.QtCore.QCoreApplication.setAttribute(
        PyQt5.QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True
    )
    PyQt5.QtCore.QCoreApplication.setAttribute(
        PyQt5.QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True
    )
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    sys.modules["PyQt6"] = PyQt5
    sys.modules["PyQt6.QtCore"] = PyQt5.QtCore
    sys.modules["PyQt6.QtGui"] = PyQt5.QtGui
    sys.modules["PyQt6.QtWidgets"] = PyQt5.QtWidgets


def init_qt_backend() -> str:
    """Initialize PyQt6, or fall back to PyQt5 with compatibility shim.

    Returns:
        'pyqt6' or 'pyqt5' indicating which backend was loaded.

    Raises:
        QtBackendError: If neither PyQt6 nor PyQt5 could be loaded.
    """
    use_pyqt5 = os.environ.get("FORCE_PYQT5") == "1"
    pyqt6_error: Optional[Exception] = None

    if not use_pyqt5:
        try:
            import PyQt6.QtCore  # noqa: F401
            import PyQt6.QtGui  # noqa: F401
            from PyQt6.QtWidgets import QApplication  # noqa: F401
            return "pyqt6"
        except ImportError as exc:
            pyqt6_error = exc
            use_pyqt5 = True

    try:
        install_pyqt5_shim()
        return "pyqt5"
    except ImportError as pyqt5_error:
        raise QtBackendError(pyqt6_error, pyqt5_error) from pyqt5_error

