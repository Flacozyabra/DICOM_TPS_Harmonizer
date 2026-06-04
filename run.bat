@echo off
:: Переходим в папку, где находится сам батник (на случай запуска из другого места)
cd /d "%~dp0"

:: Проверяем наличие виртуального окружения
if not exist ".venv\Scripts\pythonw.exe" (
    echo [ERROR] Виртуальное окружение .venv не найдено!
    echo Пожалуйста, запустите установку зависимостей, как описано в README.md
    pause
    exit /b
)

:: Запускаем программу без отображения окна консоли (используя pythonw.exe)
start "" ".venv\Scripts\pythonw.exe" main.py

exit
