import platform
from PyQt6.QtWidgets import QWidget, QDialog

def set_dark_titlebar(window: QWidget) -> None:
    """Окрашивает верхнюю полосу заголовка окна на Windows. Всплывающие окна всегда темные."""
    if platform.system() == "Windows":
        try:
            import ctypes
            hwnd = int(window.winId())
            
            # Всплывающие диалоги (QDialog) ВСЕГДА должны иметь темный заголовок
            if isinstance(window, QDialog):
                is_dark = 1
            else:
                # Находим тему, обходя родителей
                theme = "dark"
                p = window
                while p:
                    if hasattr(p, "current_theme"):
                        theme = p.current_theme
                        break
                    p = p.parent()
                is_dark = 0 if theme == "light" else 1
            
            # Атрибут DWMWA_USE_IMMERSIVE_DARK_MODE (20 в Win11, 19 в Win10)
            for attr in [20, 19]:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    attr,
                    ctypes.byref(ctypes.c_int(is_dark)),
                    ctypes.sizeof(ctypes.c_int)
                )
        except Exception:
            pass
