# План реализации схемы автообновления из DICOM WatchDog

## Обзор задачи
Перенести проверенную схему бесшовного автообновления исполняемого файла (`.exe`) через GitHub Releases из проекта `DICOM WatchDog` в проект `DICOM TPS Harmonizer` с обязательной адаптацией внешнего вида всех диалоговых окон под текущую выбранную тему программы (dark, light, red, sunset, cyber).

---

## 1. Анализ реализации в DICOM WatchDog
В проекте `DICOM WatchDog` (`ui/updater.py` и `main.py`) схема состоит из следующих компонентов:
1. **`cleanup_old_exe()`**:
   - Вызывается при запуске в `main.py`.
   - Находит и удаляет остаточные файлы `_old_*.exe` и скрипты `_restart_update.bat` в папке исполняемого файла, оставшиеся после предыдущего обновления.
2. **`check_github_updates(repo_name)` и `UpdateCheckWorker(QThread)`**:
   - Делает запрос к GitHub API `https://api.github.com/repos/{repo_name}/releases/latest`.
   - Извлекает имя тега (`tag_name`), URL релиза (`html_url`) и словарь доступных ассетов (`assets_dict = {name: download_url}`).
   - Использует безопасный fallback по SSL (`ssl.CERT_NONE` при необходимости) и заголовок `User-Agent`.
3. **`is_newer_version(current, latest)`**:
   - Надежное сравнение версий по компонентам (с отсечением префикса `v` и дополнением нулями).
4. **`find_matching_asset(assets, build_type, latest)`**:
   - Находит соответствующий `.exe` файл в релизе (для Windows).
5. **`DownloadProgressDialog(QDialog)` и `FileDownloadWorker(QThread)`**:
   - Стилизованный диалог скачивания с отображением прогресс-бара, размера (скачано МБ / всего МБ), скорости загрузки и кнопкой «Отмена».
   - До 3 повторных попыток скачивания при сетевых сбоях.
6. **`get_clean_env()`**:
   - Очищает переменные окружения PyInstaller (`_MEIPASS`, `_MEIPASS2`, `_PYI_*`, `PYTHONPATH`, `PYTHONHOME`, пути `_mei` из `PATH`) перед запуском нового процесса, предотвращая сбои распаковщика.
7. **`run_auto_update(...)` (Бесшовная подмена и перезапуск)**:
   - Проверяет режим запуска: если запуск из исходного кода (`source`), выводит сообщение с рекомендацией сделать `git pull`.
   - Скачивает новый бинарник во временный файл `update_new.tmp`.
   - Переименовывает работающий exe-файл в `_old_<имя>.exe` (Windows разрешает переименование открытого/запущенного exe).
   - Перемещает скачанный файл на место основного exe-файла.
   - Создает и запускает скрытый батч-скрипт `_restart_update.bat`, который ждет завершения текущего процесса, удаляет старый exe и запускает обновленный exe.
   - Завершает текущий процесс приложения (`QApplication.quit()`).

---

## 2. Шаги реализации в DICOM TPS Harmonizer

### Шаг 1: Централизация палитр тем и стилизации окон (`src/gui/styles.py`)
- Вынести палитры тем (`THEMES`) в `src/gui/styles.py`, сделав их доступными для всех окон и диалогов.
- Добавить функцию `apply_dialog_theme(dialog, parent=None)`, которая:
  - Определяет текущую выбранную тему программы (dark, light, red, sunset, cyber).
  - Применяет QSS-стили диалога, согласованные с цветами темы:
    - Фон диалога: `PANEL_BG`, рамка: `BORDER_COLOR`.
    - Тексты: `TEXT_COLOR`, `TEXT_LIGHT`.
    - Прогресс-бар: фон `PROGRESS_BG`, заливка градиентом темы `GRADIENT_START` -> `GRADIENT_END`.
    - Кнопки: стандартные кнопки в тонах `BUTTON_BG` / `BORDER_COLOR_ALT`, акцентные кнопки в тонах `ACCENT_COLOR_DARK` / `ACCENT_COLOR`.
  - Устанавливает нативное оформление заголовка окна Windows 11 / 10 через DWM API в соответствии с цветами темы (`PANEL_BG` и светлый/темный режим).

### Шаг 2: Создание модуля `src/utils/updater.py`
- Перенести логику из `DICOM WatchDog/ui/updater.py`, адаптировав под структуру проекта:
  - `DEFAULT_REPO = "Flacozyabra/DICOM_TPS_Harmonizer"`.
  - Поиск исполняемого файла: поиск ассетов с расширением `.exe` (содержащих `DICOM_TPS_Harmonizer` или `harmonizer`).
  - Классы `UpdateCheckWorker` и `FileDownloadWorker`.
  - Класс `DownloadProgressDialog`, оформленный в стиле активной темы через `apply_dialog_theme`.
  - Вспомогательные функции `cleanup_old_exe`, `check_github_updates`, `is_newer_version`, `find_matching_asset`, `get_clean_env`, `run_auto_update`.
  - Функция `show_themed_message(...)` для красивого отображения информационных и предупреждающих сообщений в активной теме вместо стандартных серых `QMessageBox`.

### Шаг 3: Стилизация диалога запроса на обновление (`UpdateDialog` в `src/gui/dialogs.py`)
- Стилизовать `UpdateDialog` через `apply_dialog_theme`, чтобы кнопки "Да", "Нет", "Не спрашивать для этой версии" и фон соответствовали активной теме приложения.

### Шаг 4: Вызов очистки при старте приложения (`main.py`)
- В `main.py` после инициализации `multiprocessing.freeze_support()` добавить вызов `cleanup_old_exe()`.

### Шаг 5: Интеграция в `src/gui/app.py`
- Обновить `check_updates()`:
  - Использовать `UpdateCheckWorker` из `src.utils.updater`, возвращающий тег, URL и словарь ассетов (`assets`).
  - При обнаружении новой версии показывать стилизованный диалог `UpdateDialog`.
  - При выборе "Да" вызывать `run_auto_update(self, new_version, assets)`.
  - При выборе "Не спрашивать для этой версии" сохранять версию в `config.json` (`skipped_version`).

### Шаг 6: Локализация сообщений (`locales/ru.json` и `locales/en.json`)
- Добавить все необходимые строки для процесса скачивания и обновления (скорость, загружено МБ, ошибки, диалоги перезапуска) в `ru.json` и `en.json`.

### Шаг 7: Проверка и тестирование
- Проверить корректность импортов и синтаксиса Python.
- Проверить отображение диалогов во всех 5 темах (dark, light, red, sunset, cyber).
- Проверить работу в режиме исходного кода (`source`).
