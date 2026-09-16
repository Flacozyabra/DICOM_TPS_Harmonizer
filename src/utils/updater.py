import os
import sys
import json
import time
import shutil
import urllib.request
import subprocess

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QApplication, QWidget
)

from src.gui.styles import apply_dialog_theme, set_window_titlebar_theme

DEFAULT_REPO = "Flacozyabra/DICOM_TPS_Harmonizer"
_active_workers = set()


def tr(parent: QWidget, key: str, default_ru: str, default_en: str, *args) -> str:
    """Helper for localized strings with safe fallback."""
    if parent and hasattr(parent, "loc"):
        try:
            val = parent.loc(key, *args)
            if val and val != key:
                return val
        except Exception:
            pass

    lang = "ru"
    if parent and hasattr(parent, "current_lang"):
        lang = parent.current_lang

    text = default_ru if lang == "ru" else default_en
    if args:
        try:
            return text.format(*args)
        except Exception:
            pass
    return text


def cleanup_old_exe() -> None:
    """Removes leftover _old_*.exe binaries and temporary bat scripts from previous seamless update."""
    try:
        current_exe_path = sys.executable
        dest_dir = os.path.dirname(current_exe_path)
        if not os.path.exists(dest_dir):
            return

        for filename in os.listdir(dest_dir):
            if (filename.startswith("_old_") and filename.endswith(".exe")) or filename == "_restart_update.bat":
                old_path = os.path.join(dest_dir, filename)
                try:
                    os.remove(old_path)
                except Exception:
                    pass
    except Exception:
        pass


def check_github_updates(repo_name: str = DEFAULT_REPO) -> tuple:
    """Queries GitHub Releases API for the latest release.
    
    Returns (latest_tag_name, html_url, assets_dict) or (None, None, None).
    """
    import ssl
    url = f"https://api.github.com/repos/{repo_name}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "PyQt-App-Updater"})

    ctx = None
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    except Exception:
        pass

    try:
        open_kwargs = {"context": ctx} if ctx else {}
        with urllib.request.urlopen(req, timeout=10, **open_kwargs) as response:
            data = json.loads(response.read().decode("utf-8"))
            tag_name = data.get("tag_name", "")
            html_url = data.get("html_url", f"https://github.com/{repo_name}/releases")

            assets_dict = {}
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                download_url = asset.get("browser_download_url", "")
                if name and download_url:
                    assets_dict[name] = download_url

            return tag_name, html_url, assets_dict
    except Exception as e:
        print(f"Error checking for updates: {e}", file=sys.stderr)
        return None, None, None


def is_newer_version(current_version: str, latest_version: str) -> bool:
    """Compares two version strings (e.g. 'v2.1.0' and '2.2.0')."""
    if not latest_version:
        return False
    curr = current_version.lower().lstrip("v")
    late = latest_version.lower().lstrip("v")
    try:
        curr_parts = [int(p) for p in curr.split(".")]
        late_parts = [int(p) for p in late.split(".")]
        max_len = max(len(curr_parts), len(late_parts))
        curr_parts += [0] * (max_len - len(curr_parts))
        late_parts += [0] * (max_len - len(late_parts))
        return late_parts > curr_parts
    except ValueError:
        return late > curr


class UpdateCheckWorker(QThread):
    """Background thread to query GitHub releases without blocking the UI."""
    finished = pyqtSignal(str, str, object)

    def __init__(self, repo_name: str = DEFAULT_REPO, parent: QWidget = None):
        super().__init__(parent)
        self.repo_name = repo_name

    def run(self):
        tag, url, assets = check_github_updates(self.repo_name)
        self.finished.emit(tag or "", url or "", assets or {})


def get_clean_env() -> dict:
    """Returns a cleaned environment copy stripped of PyInstaller runtime variables."""
    env = os.environ.copy()
    meipass = getattr(sys, "_MEIPASS", None)

    for key in list(env.keys()):
        key_upper = key.upper()
        if "MEI" in key_upper or "PYI" in key_upper or key_upper in ("PYTHONPATH", "PYTHONHOME"):
            env.pop(key, None)

    if "PATH" in env:
        path_list = env["PATH"].split(os.pathsep)
        cleaned_paths = [
            p for p in path_list
            if "_mei" not in p.lower() and (not meipass or os.path.normpath(p) != os.path.normpath(meipass))
        ]
        env["PATH"] = os.path.sep.join(cleaned_paths)

    return env


def get_build_type() -> str:
    """Determines whether running as frozen PyInstaller executable or from source."""
    if not hasattr(sys, "frozen"):
        return "source"
    return "exe"


def find_matching_asset(assets: dict, build_type: str = "exe", latest_version: str = "") -> tuple:
    """Finds the matching executable asset from GitHub release assets dictionary."""
    if not assets:
        return None, None

    # First check for matches with harmonizer or dicom in name
    for name, url in assets.items():
        name_lower = name.lower()
        if name_lower.endswith(".exe") and any(k in name_lower for k in ("harmonizer", "dicom_tps")):
            return name, url

    # Fallback to any .exe asset
    for name, url in assets.items():
        if name.lower().endswith(".exe"):
            return name, url

    return None, None


class DownloadProgressDialog(QDialog):
    """Modal download progress dialog matching the active application theme."""
    canceled = pyqtSignal()

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.parent_widget = parent
        title = tr(parent, "update_download_title", "Обновление программы", "Software Update")
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)

        # Apply program theme and styling
        apply_dialog_theme(self, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        init_status = tr(parent, "update_downloading", "Скачивание обновления...", "Downloading update...")
        self.label = QLabel(init_status)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(20)
        layout.addWidget(self.progress)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_text = tr(parent, "dialog_scan_cancel", "Отмена", "Cancel")
        self.cancel_btn = QPushButton(cancel_text)
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)

    def on_cancel_clicked(self):
        self.canceled.emit()
        self.reject()

    def set_progress(self, percent: int, label_text: str):
        self.progress.setValue(percent)
        self.label.setText(label_text)

    def showEvent(self, event):
        super().showEvent(event)
        set_window_titlebar_theme(self)


class ThemedMessageDialog(QDialog):
    """Themed message dialog replacing default QMessageBox to maintain consistent theme appearance."""
    def __init__(self, parent: QWidget, title: str, message: str, is_question: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.setModal(True)
        self.result_value = False

        apply_dialog_theme(self, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        lbl = QLabel(message)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size: 13px; line-height: 1.4;")
        layout.addWidget(lbl)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        if is_question:
            yes_text = tr(parent, "yes", "Да", "Yes")
            no_text = tr(parent, "no", "Нет", "No")

            btn_yes = QPushButton(yes_text)
            btn_yes.setObjectName("primaryBtn")
            btn_yes.clicked.connect(self.on_yes)
            btn_layout.addWidget(btn_yes)

            btn_no = QPushButton(no_text)
            btn_no.clicked.connect(self.on_no)
            btn_layout.addWidget(btn_no)
        else:
            ok_text = tr(parent, "ok", "OK", "OK")
            btn_ok = QPushButton(ok_text)
            btn_ok.setObjectName("primaryBtn")
            btn_ok.clicked.connect(self.accept)
            btn_layout.addWidget(btn_ok)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def on_yes(self):
        self.result_value = True
        self.accept()

    def on_no(self):
        self.result_value = False
        self.reject()

    def showEvent(self, event):
        super().showEvent(event)
        set_window_titlebar_theme(self)


def show_themed_message(parent: QWidget, title: str, message: str) -> None:
    """Shows an informational modal dialog styled according to active theme."""
    dlg = ThemedMessageDialog(parent, title, message, is_question=False)
    dlg.exec()


def ask_themed_question(parent: QWidget, title: str, message: str) -> bool:
    """Shows a confirmation modal dialog styled according to active theme. Returns True if confirmed."""
    dlg = ThemedMessageDialog(parent, title, message, is_question=True)
    return dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_value


class FileDownloadWorker(QThread):
    """Background download worker with progress calculation and automatic retry."""
    progress = pyqtSignal(int, str, int, int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, url: str, dest_path: str, parent: QWidget = None):
        super().__init__(parent)
        self.url = url
        self.dest_path = dest_path
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        import ssl
        max_retries = 3
        retry_delay = 2

        ctx = None
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        except Exception:
            pass

        for attempt in range(max_retries):
            if self.is_cancelled:
                return
            try:
                req = urllib.request.Request(self.url, headers={"User-Agent": "PyQt-App-Updater"})
                open_kwargs = {"context": ctx} if ctx else {}
                with urllib.request.urlopen(req, timeout=30, **open_kwargs) as response:
                    total_size = int(response.info().get("Content-Length", 0))
                    bytes_downloaded = 0
                    block_size = 1024 * 16

                    start_time = time.time()
                    last_time = start_time
                    last_bytes = 0
                    speed_str = "..."

                    with open(self.dest_path, "wb") as f:
                        while True:
                            if self.is_cancelled:
                                f.close()
                                try:
                                    if os.path.exists(self.dest_path):
                                        os.remove(self.dest_path)
                                except Exception:
                                    pass
                                return

                            buffer = response.read(block_size)
                            if not buffer:
                                break
                            bytes_downloaded += len(buffer)
                            f.write(buffer)

                            current_time = time.time()
                            if current_time - last_time >= 0.5:
                                duration = current_time - last_time
                                bytes_diff = bytes_downloaded - last_bytes
                                speed_bytes_sec = bytes_diff / duration if duration > 0 else 0

                                if speed_bytes_sec < 1024:
                                    speed_str = f"{speed_bytes_sec:.1f} B/s"
                                elif speed_bytes_sec < 1024 * 1024:
                                    speed_str = f"{speed_bytes_sec / 1024:.1f} KB/s"
                                else:
                                    speed_str = f"{speed_bytes_sec / (1024 * 1024):.1f} MB/s"

                                last_time = current_time
                                last_bytes = bytes_downloaded

                            percent = int((bytes_downloaded / total_size) * 100) if total_size > 0 else 0
                            self.progress.emit(percent, speed_str, bytes_downloaded, total_size)

                if not self.is_cancelled:
                    self.progress.emit(100, speed_str, bytes_downloaded, total_size)
                    self.finished.emit(self.dest_path)
                return
            except Exception as e:
                if self.is_cancelled:
                    return
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    self.error.emit(str(e))
                    self.finished.emit("")


def run_auto_update(parent: QWidget, latest_version: str, assets: dict) -> None:
    """Orchestrates update download, seamless binary swap, batch restart, and app exit."""
    build_type = get_build_type()

    if build_type == "source":
        show_themed_message(
            parent,
            tr(parent, "update_title", "Доступно обновление", "Update Available"),
            tr(
                parent,
                "update_running_from_source",
                "Доступна новая версия: {}.\n\nВы запустили приложение из исходного кода. Пожалуйста, обновите репозиторий вручную с помощью git pull.",
                "Version {} is available.\n\nYou are running the application from source code. Please update the repository manually via git pull.",
                latest_version
            )
        )
        return

    asset_name, download_url = find_matching_asset(assets, build_type, latest_version)
    if not download_url:
        show_themed_message(
            parent,
            tr(parent, "update_error_title", "Ошибка обновления", "Update Error"),
            tr(
                parent,
                "update_asset_not_found",
                "Доступна новая версия {}, но не удалось найти подходящий исполняемый файл (.exe) среди ассетов релиза.\n\nПожалуйста, обновите программу вручную на GitHub.",
                "Version {} is available, but no matching executable file (.exe) was found in the release assets.\n\nPlease download the update manually from GitHub.",
                latest_version
            )
        )
        return

    current_exe_path = sys.executable
    dest_dir = os.path.dirname(current_exe_path)
    temp_exe_path = os.path.join(dest_dir, "update_new.tmp")

    progress_dialog = DownloadProgressDialog(parent)
    progress_dialog.show()

    worker = FileDownloadWorker(download_url, temp_exe_path, parent)
    _active_workers.add(worker)

    def on_progress(percent: int, speed: str, downloaded: int, total: int):
        downloaded_mb = downloaded / (1024 * 1024)
        if total > 0:
            total_mb = total / (1024 * 1024)
            label_text = tr(
                parent,
                "update_download_progress_full",
                "Скачивание обновления...\nЗагружено: {:.1f} МБ из {:.1f} МБ\nСкорость: {}",
                "Downloading update...\nDownloaded: {:.1f} MB of {:.1f} MB\nSpeed: {}",
                downloaded_mb, total_mb, speed
            )
        else:
            label_text = tr(
                parent,
                "update_download_progress_bytes",
                "Скачивание обновления...\nЗагружено: {:.1f} МБ\nСкорость: {}",
                "Downloading update...\nDownloaded: {:.1f} MB\nSpeed: {}",
                downloaded_mb, speed
            )
        progress_dialog.set_progress(percent, label_text)

    worker.progress.connect(on_progress)

    def on_finished(path: str):
        progress_dialog.close()
        _active_workers.discard(worker)
        if not path or not os.path.exists(path):
            return

        exe_basename = os.path.basename(current_exe_path)
        old_exe_path = os.path.join(dest_dir, f"_old_{exe_basename}")

        try:
            if os.path.exists(old_exe_path):
                os.remove(old_exe_path)
        except Exception:
            pass

        try:
            # Rename the running exe (allowed by Windows even when running)
            os.rename(current_exe_path, old_exe_path)
        except Exception as e:
            show_themed_message(
                parent,
                tr(parent, "update_error_title", "Ошибка обновления", "Update Error"),
                tr(
                    parent,
                    "update_rename_error",
                    "Не удалось подготовить файл к обновлению (ошибка переименования):\n{}",
                    "Failed to prepare file for update (rename error):\n{}",
                    str(e)
                )
            )
            try:
                os.remove(path)
            except Exception:
                pass
            return

        try:
            # Move downloaded file to replace the original executable
            shutil.move(path, current_exe_path)
        except Exception as e:
            # Rollback old executable
            try:
                os.rename(old_exe_path, current_exe_path)
            except Exception:
                pass
            try:
                os.remove(path)
            except Exception:
                pass
            show_themed_message(
                parent,
                tr(parent, "update_error_title", "Ошибка обновления", "Update Error"),
                tr(
                    parent,
                    "update_replace_error",
                    "Не удалось применить новую версию:\n{}",
                    "Failed to apply new version:\n{}",
                    str(e)
                )
            )
            return

        try:
            clean_env = get_clean_env()

            if sys.platform == "win32":
                bat_path = os.path.join(dest_dir, "_restart_update.bat")
                with open(bat_path, "w", encoding="utf-8", errors="ignore") as f:
                    f.write("@echo off\n")
                    f.write('set "_MEIPASS="\n')
                    f.write('set "_MEIPASS2="\n')
                    f.write('set "_PYI_ARCHIVE_FILE="\n')
                    f.write('set "_PYI_SPLASH_IPC="\n')
                    f.write('set "PYINSTALLER_STRICT_UNPACK_MODE="\n')
                    f.write('set "PYTHONPATH="\n')
                    f.write('set "PYTHONHOME="\n')
                    f.write("timeout /t 3 /nobreak > nul\n")
                    f.write(f'if exist "{old_exe_path}" del /f /q "{old_exe_path}" > nul 2>&1\n')
                    f.write(f'start "" "{current_exe_path}"\n')
                    f.write('(goto) 2>nul & del "%~f0"\n')

                subprocess.Popen(
                    ["cmd.exe", "/c", bat_path],
                    env=clean_env,
                    cwd=dest_dir,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                subprocess.Popen([current_exe_path], env=clean_env, cwd=dest_dir)

            QApplication.quit()
        except Exception as e:
            show_themed_message(
                parent,
                tr(parent, "update_error_title", "Ошибка запуска", "Launch Error"),
                tr(
                    parent,
                    "update_restart_error",
                    "Обновление успешно применилось, но не удалось автоматически перезапустить программу:\n{}\nПожалуйста, запустите её вручную.",
                    "Update applied successfully, but failed to restart application automatically:\n{}\nPlease launch it manually.",
                    str(e)
                )
            )
            QApplication.quit()

    def on_error(err_msg: str):
        _active_workers.discard(worker)
        show_themed_message(
            parent,
            tr(parent, "update_error_title", "Ошибка скачивания", "Download Error"),
            tr(
                parent,
                "update_download_error",
                "Произошла ошибка при загрузке обновления:\n{}",
                "An error occurred while downloading the update:\n{}",
                err_msg
            )
        )

    def on_cancel():
        worker.cancel()
        _active_workers.discard(worker)

    worker.finished.connect(on_finished)
    worker.error.connect(on_error)
    progress_dialog.canceled.connect(on_cancel)

    worker.start()
