# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [2.2.0] - 2026-09-16
### Added
- **Seamless GitHub Auto-Update (`src/utils/updater.py`)**:
  - Implemented GitHub Releases API query to fetch the latest tag, release notes URL, and asset binaries.
  - Implemented background thread `UpdateCheckWorker` and chunked downloader `FileDownloadWorker` with download speed, downloaded/total size tracking, and retry mechanism.
  - Implemented seamless executable replacement on Windows: atomic renaming of running executable to `_old_<name>.exe` and moving downloaded update into place.
  - Implemented detached restart script `_restart_update.bat` that strips PyInstaller runtime environment variables (`get_clean_env`), waits for application exit, removes `_old_*.exe`, and launches the updated binary.
  - Added startup binary cleanup `cleanup_old_exe()` in `main.py`.
  - Added themed progress dialog `DownloadProgressDialog` and message dialogs `ThemedMessageDialog` in `src/utils/updater.py`.
- **Dynamic Dialog Theme Styling (`src/gui/styles.py`)**:
  - Centralized theme definitions (`THEMES`) in `styles.py`.
  - Added `apply_dialog_theme()` and `set_window_titlebar_theme()` to dynamically style all dialogs and their Windows DWM title bars to match the selected theme (Dark, Light, Red, Sunset, Cyber).
  - Updated `UpdateDialog` in `src/gui/dialogs.py` with full theme styling and accent colors.
- **Localization (`locales/ru.json`, `locales/en.json`)**:
  - Added Russian and English strings for update confirmation, download progress, download speed, and update error notifications.
### Changed
- Standardized release executable filename to `DICOM_TPS_Harmonizer.exe` (removed version suffix from binary name) to ensure persistent shortcuts and clean auto-updates.
