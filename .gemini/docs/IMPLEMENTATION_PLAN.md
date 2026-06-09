# План реализации: Переход на PyQt6 и обновление локализации

## 1. Зависимости (requirements.txt)
[MODIFY] [requirements.txt](file:///c:/Users/Falco/Desktop/DICOM%20TPS%20Harmonizer/requirements.txt)
- Добавить `PyQt6` в список зависимостей.
- Установить библиотеку `PyQt6` в виртуальное окружение.

## 2. Локализация (locales/ru.json и locales/en.json)
[MODIFY] [ru.json](file:///c:/Users/Falco/Desktop/DICOM%20TPS%20Harmonizer/locales/ru.json)
[MODIFY] [en.json](file:///c:/Users/Falco/Desktop/DICOM%20TPS%20Harmonizer/locales/en.json)
- Заменить значение ключа `patient_explorer` ("Проводник пациентов") на более лаконичное "Пациенты" ("Patients").

## 3. Переработка графического интерфейса (src/gui/app.py)
[MODIFY] [app.py](file:///c:/Users/Falco/Desktop/DICOM%20TPS%20Harmonizer/src/gui/app.py)
- Полностью переписать класс `DicomSplitterApp` на базе `QtWidgets.QMainWindow`.
- Реализовать дерево пациентов на базе `QtWidgets.QTreeWidget` с чекбоксами (это обеспечит мгновенную скорость работы при больших базах данных).
- Реализовать темную тему оформления через QSS (Qt Style Sheets) с использованием современной цветовой палитры (стеклянные эффекты, гармоничные цвета).
- Реализовать безопасное обновление UI из фоновых потоков сканирования и обработки с помощью сигналов (`QtCore.pyqtSignal`).
- Переписать диалоги `CustomQuestionDialog` и `PatientEditDialog` на базе `QtWidgets.QDialog`.
- Создать `ScanProgressDialog` на базе `QtWidgets.QDialog` с `QProgressBar` и кнопкой отмены.

## План проверки
1. Установить зависимости и проверить синтаксис обновленного кода.
2. Запустить приложение с помощью `python main.py` и проверить:
   - Внешний вид (современная темная тема).
   - Скорость сканирования и отображение модального окна прогресса сканирования (в процентах).
   - Лаконичность надписи "Пациенты" в левой панели.
   - Выбор чекбоксов и каскадный выбор (выбор пациента выбирает его исследования и серии).
   - Интерактивную валидацию пациента (появление диалога редактирования).
   - Корректность запуска обработки DICOM и отображения прогресса/логов в реальном времени.
