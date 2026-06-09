# План реализации: Окно прогресса сканирования и исправление подсчета серий

## 1. Локализация (locales/ru.json и locales/en.json)
[MODIFY] [ru.json](file:///c:/Users/Falco/Desktop/DICOM%20TPS%20Harmonizer/locales/ru.json)
[MODIFY] [en.json](file:///c:/Users/Falco/Desktop/DICOM%20TPS%20Harmonizer/locales/en.json)
- Добавить ключи для заголовка окна сканирования, прогресса сканирования и кнопки отмены.

## 2. Логгер (src/utils/logger.py)
[MODIFY] [logger.py](file:///c:/Users/Falco/Desktop/DICOM%20TPS%20Harmonizer/src/utils/logger.py)
- Добавить метод `update_scan_progress(self, current: int, total: int)` в `BaseLogger` и `QueueLogger` для передачи прогресса сканирования в GUI.

## 3. Логика сканирования и фильтрации (src/core/processor.py)
[MODIFY] [processor.py](file:///c:/Users/Falco/Desktop/DICOM%20TPS%20Harmonizer/src/core/processor.py)
- В `scan_input_directory` добавить отправку прогресса сканирования через `self.logger.update_scan_progress`.
- В `scan_input_directory` добавить проверку флага `self.config.split_series` перед разделением серий по геометрическим группам.

## 4. Диалог прогресса и интеграция с GUI (src/gui/app.py)
[MODIFY] [app.py](file:///c:/Users/Falco/Desktop/DICOM%20TPS%20Harmonizer/src/gui/app.py)
- Создать класс `ScanProgressDialog(ctk.CTkToplevel)`.
- Интегрировать диалог в процесс запуска сканирования `run_input_scan`.
- Обрабатывать события `scan_progress` в `update_log_queue` для обновления интерфейса диалога.
- Закрывать диалог по завершению сканирования или при отмене.

## План проверки
1. Запустить приложение.
2. Проверить, что при нажатии на кнопку "Сканировать" появляется модальное окно с прогресс-баром и процентами.
3. Проверить отмену сканирования (диалог должен закрыться, сканирование прерваться).
4. Проверить, что при снятой галочке "Разделять смешанные серии (геометрически)" количество серий в дереве совпадает с MicroDicom.
