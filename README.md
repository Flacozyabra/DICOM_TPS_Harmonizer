# DICOM TPS Harmonizer

[Русский](#русский) | [English](#english)

---

![DICOM TPS Harmonizer Interface](docs/screenshots/main_interface.jpg)

<details>
  <summary><b>DICOM Viewer Screenshot (Интерактивный вьюер)</b></summary>
  <br/>
  <img src="docs/screenshots/dicom_viewer.jpg" alt="DICOM Viewer" />
</details>

<details>
  <summary><b>Interface Customization (Кастомизация интерфейса / Темы)</b></summary>
  <br/>
  <img src="docs/screenshots/customization.jpg" alt="Customization" />
</details>

---

## Русский

**DICOM TPS Harmonizer** — это приложение с графическим интерфейсом для разделения мультифреймовых DICOM-файлов на одиночные срезы и оптимизации их метаданных под планирующие системы (TPS) **Varian Eclipse** и **Elekta Monaco**.

### Основные возможности
* **Умное разделение мультифреймов:** Преобразует Enhanced DICOM (CT/MR/RT) в классические single-frame срезы с разбиением на подсерии по геометрии, `StackID`, `EchoNumbers`, `TemporalPositionIndex`, b-value и `FrameType`, восстановлением пропущенных `ImagePositionPatient` и очисткой остаточных Enhanced-тегов контейнера.
* **Совместимость с TPS:** Очищает приватные теги, генерирует новые UID, нормализует кодировку текста (`ISO_IR 100` / автоматический переход на UTF-8 для кириллицы), обнуляет углы стола CT для Monaco и проводит пост-проверку целостности пикселей и дубликатов позиций срезов.
* **Автоматическое исправление (Siemens EOF Fix):** На лету восстанавливает повреждённые и усечённые файлы (включая проверку полноты несжатых `PixelData`).
* **Высокая скорость обработки:** Многопоточное сканирование с кешированием заголовков, адаптивные батчи и пофазный прогресс-бар в реальном времени.
* **Удобная структура папок:** Группирует результаты с защитой от коллизий имён:  
  `Dicom_output / <Имя_Пациента>_<ID_Пациента> / <Модальность_НомерСерии_Описание> / slice_XXXX.dcm`
* **Интерактивный DICOM вьюер:** Встроенный инструмент просмотра серий с поддержкой масштабирования (Zoom), перемещения (Pan), измерительной линейки и адаптивной настройки окна HU (включая МРТ).

### Редакции готовых сборок (EXE)
В разделе [Releases](https://github.com/Flacozyabra/DICOM_TPS_Harmonizer/releases) на GitHub доступны **две версии** исполняемого файла — выберите подходящую для вашего компьютера (автообновление автоматически сохраняет выбранную редакцию):

* **`DICOM_TPS_Harmonizer.exe`** *(Основная редакция — рекомендуется для Windows 10 1903+ / Windows 11)*
  * Собрана на **Python 3.12** и **`PyQt6`**.
  * Предназначена для современных рабочих станций. При отсутствии системных библиотек C++ может потребовать пакет [Microsoft Visual C++ Redistributable (2015–2022 x64)](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist).
* **`DICOM_TPS_Harmonizer_Legacy.exe`** *(Совместимая редакция — для Windows 7 / 8.1 и старых сборок Windows 10)*
  * Собрана на **Python 3.8.10** и **`PyQt5`** (через встроенный слой совместимости).
  * Предназначена для устаревших ПК, корпоративных сборок Windows 10 LTSC (1607/1809), Windows Server или компьютеров, на которых основная версия не запускается с ошибкой `DLL load failed while importing QtWidgets`.

---

## English

**DICOM TPS Harmonizer** is a desktop GUI application designed to split multi-frame DICOM files into classic single-frame slices and optimize their metadata for **Varian Eclipse** and **Elekta Monaco** Treatment Planning Systems (TPS).

### Key Features
* **Smart Multi-frame Splitting:** Converts Enhanced DICOM (CT/MR/RT) datasets into classic single-frame slices, splitting subseries by orientation, `StackID`, `EchoNumbers`, `TemporalPositionIndex`, b-value, and `FrameType`, reconstructing missing `ImagePositionPatient`, and stripping residual Enhanced container tags.
* **TPS Compatibility:** Filters incompatible private tags, generates clean UIDs, normalizes character sets (`ISO_IR 100` / auto UTF-8 for Cyrillic), resets CT couch angles for Monaco, and runs post-verification for pixel integrity and duplicate slice positions.
* **On-the-fly Recovery (Siemens EOF Fix):** Automatically repairs truncated DICOM files and verifies uncompressed `PixelData` byte completeness.
* **Fast Processing Pipeline:** Multithreaded scanning with reusable header cache, adaptive batch sizing, and smooth phase-based progress reporting.
* **Collision-Safe Directory Hierarchy:** Outputs structured patient datasets:  
  `Dicom_output / <PatientName>_<PatientID> / <Modality_SeriesNumber_Description> / slice_XXXX.dcm`
* **Interactive DICOM Viewer:** Integrated series visualization featuring Zoom, Pan, measurement ruler, and adaptive HU/intensity Level/Width sliders.

### Executable (EXE) Editions
Two standalone Windows `.exe` editions are available in the [Releases](https://github.com/Flacozyabra/DICOM_TPS_Harmonizer/releases) section — choose the one that best fits your system (auto-update automatically preserves your current edition):

* **`DICOM_TPS_Harmonizer.exe`** *(Modern Edition — recommended for Windows 10 1903+ / Windows 11)*
  * Built on **Python 3.12** with **`PyQt6`**.
  * Recommended for modern workstations. May require [Microsoft Visual C++ Redistributable (2015–2022 x64)](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) if missing on the target machine.
* **`DICOM_TPS_Harmonizer_Legacy.exe`** *(Compatibility Edition — Windows 7 / 8.1 / Legacy Windows 10)*
  * Built on **Python 3.8.10** with **`PyQt5`** via the built-in compatibility shim.
  * Designed for legacy workstations, Windows 10 LTSC (1607/1809), Windows Server, or machines where the modern build fails with `DLL load failed while importing QtWidgets`.
