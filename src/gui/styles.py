import platform
from PyQt6.QtWidgets import QWidget, QDialog

THEMES = {
    "dark": {
        "MAIN_BG": "#121212",
        "PANEL_BG": "#1A1A1A",
        "TEXT_COLOR": "#D1D5DB",
        "TEXT_LIGHT": "#FFFFFF",
        "TEXT_MUTED": "#A0A0A0",
        "BORDER_COLOR": "#2D2D2D",
        "BORDER_COLOR_ALT": "#374151",
        "BUTTON_BG": "#2A2A2A",
        "BUTTON_HOVER_BG": "#374151",
        "BUTTON_PRESSED_BG": "#1F2937",
        "ACCENT_COLOR": "#3B82F6",
        "ACCENT_COLOR_DARK": "#2563EB",
        "ACCENT_COLOR_DEEP": "#1D4ED8",
        "PROGRESS_BG": "#151515",
        "PROGRESS_BORDER": "#333333",
        "GRADIENT_START": "#3B82F6",
        "GRADIENT_END": "#8B5CF6",
        "ARROW_RIGHT_PATH": "arrow_right.png",
        "SPLITTER_COLOR": "#2D2D2D"
    },
    "light": {
        "MAIN_BG": "#E2E2E2",
        "PANEL_BG": "#F0F0F0",
        "TEXT_COLOR": "#202020",
        "TEXT_LIGHT": "#000000",
        "TEXT_MUTED": "#5E5E5E",
        "BORDER_COLOR": "#CCCCCC",
        "BORDER_COLOR_ALT": "#9E9E9E",
        "BUTTON_BG": "#D5D5D5",
        "BUTTON_HOVER_BG": "#C0C0C0",
        "BUTTON_PRESSED_BG": "#A0A0A0",
        "ACCENT_COLOR": "#757575",
        "ACCENT_COLOR_DARK": "#424242",
        "ACCENT_COLOR_DEEP": "#212121",
        "PROGRESS_BG": "#CCCCCC",
        "PROGRESS_BORDER": "#9E9E9E",
        "GRADIENT_START": "#757575",
        "GRADIENT_END": "#212121",
        "ARROW_RIGHT_PATH": "arrow_right_dark.png",
        "SPLITTER_COLOR": "#CCCCCC"
    },
    "red": {
        "MAIN_BG": "#1C0D11",
        "PANEL_BG": "#2D151B",
        "TEXT_COLOR": "#F9ECED",
        "TEXT_LIGHT": "#FFFFFF",
        "TEXT_MUTED": "#D4A3A9",
        "BORDER_COLOR": "#4E232E",
        "BORDER_COLOR_ALT": "#8A3B4E",
        "BUTTON_BG": "#5E2633",
        "BUTTON_HOVER_BG": "#7B3143",
        "BUTTON_PRESSED_BG": "#3F1922",
        "ACCENT_COLOR": "#E11D48",
        "ACCENT_COLOR_DARK": "#BE123C",
        "ACCENT_COLOR_DEEP": "#9F1239",
        "PROGRESS_BG": "#2D151B",
        "PROGRESS_BORDER": "#4E232E",
        "GRADIENT_START": "#E11D48",
        "GRADIENT_END": "#FDA4AF",
        "ARROW_RIGHT_PATH": "arrow_right.png",
        "SPLITTER_COLOR": "#4E232E"
    },
    "sunset": {
        "MAIN_BG": "#101E2E",
        "PANEL_BG": "#242F49",
        "TEXT_COLOR": "#D1D5DB",
        "TEXT_LIGHT": "#FFA586",
        "TEXT_MUTED": "#8A9BB4",
        "BORDER_COLOR": "#384358",
        "BORDER_COLOR_ALT": "#5871A2",
        "BUTTON_BG": "#3C4E70",
        "BUTTON_HOVER_BG": "#4D638E",
        "BUTTON_PRESSED_BG": "#2A374F",
        "ACCENT_COLOR": "#B51A2B",
        "ACCENT_COLOR_DARK": "#9A1624",
        "ACCENT_COLOR_DEEP": "#541A2E",
        "PROGRESS_BG": "#101E2E",
        "PROGRESS_BORDER": "#384358",
        "GRADIENT_START": "#FFA586",
        "GRADIENT_END": "#B51A2B",
        "ARROW_RIGHT_PATH": "arrow_right.png",
        "SPLITTER_COLOR": "#384358"
    },
    "cyber": {
        "MAIN_BG": "#0F0F0F",
        "PANEL_BG": "#202020",
        "TEXT_COLOR": "#D1D5DB",
        "TEXT_LIGHT": "#F8F8F8",
        "TEXT_MUTED": "#808080",
        "BORDER_COLOR": "#337418",
        "BORDER_COLOR_ALT": "#5DD62C",
        "BUTTON_BG": "#265912",
        "BUTTON_HOVER_BG": "#337418",
        "BUTTON_PRESSED_BG": "#0F0F0F",
        "ACCENT_COLOR": "#5DD62C",
        "ACCENT_COLOR_DARK": "#4CB323",
        "ACCENT_COLOR_DEEP": "#337418",
        "PROGRESS_BG": "#0F0F0F",
        "PROGRESS_BORDER": "#337418",
        "GRADIENT_START": "#5DD62C",
        "GRADIENT_END": "#337418",
        "ARROW_RIGHT_PATH": "arrow_right.png",
        "SPLITTER_COLOR": "#337418"
    }
}


def hex_to_bgr(hex_color: str) -> int:
    """Converts hex color string (#RRGGBB) to Windows DWM BGR integer."""
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def get_current_theme_palette(parent: QWidget = None) -> tuple[dict, str]:
    """Retrieves current active theme palette and name from widget hierarchy or top-level windows."""
    theme = "dark"
    p = parent
    while p:
        if hasattr(p, "current_theme") and p.current_theme in THEMES:
            theme = p.current_theme
            return THEMES[theme], theme
        if hasattr(p, "parent") and callable(p.parent):
            p = p.parent()
        else:
            break

    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            for widget in app.topLevelWidgets():
                if hasattr(widget, "current_theme") and widget.current_theme in THEMES:
                    theme = widget.current_theme
                    return THEMES[theme], theme
    except Exception:
        pass

    return THEMES[theme], theme


def set_window_titlebar_theme(window: QWidget, palette: dict = None, theme: str = None) -> None:
    """Applies Windows DWM dark/light mode and caption colors matching the theme."""
    if platform.system() == "Windows":
        try:
            import ctypes
            hwnd = int(window.winId())

            if palette is None or theme is None:
                palette, theme = get_current_theme_palette(window)

            is_dark = 0 if theme == "light" else 1

            # DWMWA_USE_IMMERSIVE_DARK_MODE (20 on Win11, 19 on Win10)
            for attr in [20, 19]:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    attr,
                    ctypes.byref(ctypes.c_int(is_dark)),
                    ctypes.sizeof(ctypes.c_int)
                )

            # Windows 11 custom title bar color: DWMWA_CAPTION_COLOR (35) and DWMWA_TEXT_COLOR (36)
            if "PANEL_BG" in palette:
                bg_bgr = hex_to_bgr(palette["PANEL_BG"])
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    35,
                    ctypes.byref(ctypes.c_int(bg_bgr)),
                    ctypes.sizeof(ctypes.c_int)
                )
            if "TEXT_COLOR" in palette:
                text_bgr = hex_to_bgr(palette["TEXT_COLOR"])
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    36,
                    ctypes.byref(ctypes.c_int(text_bgr)),
                    ctypes.sizeof(ctypes.c_int)
                )
        except Exception:
            pass


def set_dark_titlebar(window: QWidget) -> None:
    """Backward-compatible wrapper for setting titlebar theme based on active window theme."""
    palette, theme = get_current_theme_palette(window)
    set_window_titlebar_theme(window, palette, theme)


def get_dialog_stylesheet(palette: dict) -> str:
    """Generates a complete QSS stylesheet for dialog windows according to theme palette."""
    return f"""
        QDialog {{
            background-color: {palette['PANEL_BG']};
            border: 1px solid {palette['BORDER_COLOR']};
            border-radius: 8px;
        }}
        QWidget {{
            color: {palette['TEXT_COLOR']};
            font-family: 'Segoe UI', Arial, sans-serif;
        }}
        QLabel {{
            color: {palette['TEXT_COLOR']};
            font-size: 13px;
            background: transparent;
        }}
        QProgressBar {{
            background-color: {palette['PROGRESS_BG']};
            border: 1px solid {palette['PROGRESS_BORDER']};
            border-radius: 6px;
            text-align: center;
            color: {palette['TEXT_COLOR']};
            font-weight: bold;
            font-size: 11px;
        }}
        QProgressBar::chunk {{
            background-color: qlineargradient(
                spread:pad, x1:0, y1:0, x2:1, y2:0,
                stop:0 {palette['GRADIENT_START']},
                stop:1 {palette['GRADIENT_END']}
            );
            border-radius: 5px;
        }}
        QPushButton {{
            background-color: {palette['BUTTON_BG']};
            color: {palette['TEXT_COLOR']};
            border: 1px solid {palette['BORDER_COLOR_ALT']};
            border-radius: 6px;
            padding: 6px 16px;
            font-size: 12px;
            min-width: 80px;
        }}
        QPushButton:hover {{
            background-color: {palette['BUTTON_HOVER_BG']};
            border-color: {palette['BORDER_COLOR_ALT']};
        }}
        QPushButton:pressed {{
            background-color: {palette['BUTTON_PRESSED_BG']};
        }}
        QPushButton#primaryBtn {{
            background-color: {palette['ACCENT_COLOR_DARK']};
            color: #FFFFFF;
            font-weight: bold;
            border: none;
        }}
        QPushButton#primaryBtn:hover {{
            background-color: {palette['ACCENT_COLOR']};
        }}
        QPushButton#primaryBtn:pressed {{
            background-color: {palette['ACCENT_COLOR_DEEP']};
        }}
    """


def apply_dialog_theme(dialog: QWidget, parent: QWidget = None) -> tuple[dict, str]:
    """Applies theme stylesheet and Windows titlebar styling to a dialog window."""
    palette, theme = get_current_theme_palette(parent or dialog.parent())
    dialog.setStyleSheet(get_dialog_stylesheet(palette))
    set_window_titlebar_theme(dialog, palette, theme)
    return palette, theme
