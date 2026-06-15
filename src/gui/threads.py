import urllib.request
import re
from PyQt6.QtCore import QThread, pyqtSignal

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
