@echo off
:: Переходим в папку, где находится сам батник (на случай запуска из другого места)
cd /d "%~dp0"

:: Проверяем наличие виртуального окружения
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Виртуальное окружение .venv не найдено!
    echo Пожалуйста, запустите установку зависимостей, как описано в README.md
    pause
    exit /b
)

:: Предварительная проверка импорта и синтаксиса перед тихим запуском
".venv\Scripts\python.exe" -c "from src.gui.app import DicomSplitterApp" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Ошибка запуска приложения или не все зависимости установлены!
    echo Запуск диагностики и вывод traceback:
    echo ----------------------------------------------------------------------
    ".venv\Scripts\python.exe" main.py
    echo ----------------------------------------------------------------------
    pause
    exit /b
)

:: Запускаем программу без отображения окна консоли (используя pythonw.exe)
start "" ".venv\Scripts\pythonw.exe" main.py

exit
