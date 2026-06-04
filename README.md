# DICOM TPS Harmonizer

[Русский](#русский) | [English](#english)

---

## Русский

**DICOM TPS Harmonizer** — это приложение с графическим интерфейсом (GUI) для разделения мультифреймовых DICOM-файлов на одиночные срезы и оптимизации их метаданных под планирующие системы (TPS) **Varian Aria** и **Elekta Monaco**.

### Основные возможности
* **Разделение мультифреймов:** Преобразует файлы Enhanced DICOM в классические single-frame срезы.
* **Совместимость с TPS:** Очищает приватные теги, генерирует новые UID и приводит файлы к стандарту, необходимому для Aria и Monaco.
* **Автоматическое исправление (Siemens EOF Fix):** На лету восстанавливает поврежденные файлы, у которых отсутствует концевой маркер последовательности пикселей.
* **Удобная структура папок:** Группирует результаты в виде:  
  `Dicom_output / <Имя_Пациента>_<ID_Пациента> / <Модальность_Описание_Серии> / slice_XXXX.dcm`
* **Современный GUI:** Интерфейс на базе `CustomTkinter` с темной темой, прогресс-баром и интерактивным цветовым логированием операций в реальном времени.

### Быстрый запуск (Windows)
Просто запустите файл [run.bat](file:///c:/Users/Falco/Desktop/Dicom%20splitter/run.bat) в корневой папке проекта. Он автоматически активирует виртуальное окружение и запустит программу.

### Установка вручную
1. Создайте виртуальное окружение: `python -m venv .venv`
2. Активируйте его: `.venv\Scripts\activate` (Windows) или `source .venv/bin/activate` (Linux/macOS)
3. Установите зависимости: `pip install -r requirements.txt`
4. Запустите: `python main.py`

---

## English

**DICOM TPS Harmonizer** is a desktop GUI application designed to split multi-frame DICOM files into classic single-frame slices and optimize their metadata for **Varian Aria** and **Elekta Monaco** Treatment Planning Systems (TPS).

### Key Features
* **Multi-frame Splitting:** Converted Enhanced DICOM datasets into standard single-frame slices.
* **TPS Compatibility:** Filters incompatible private tags, generates clean UIDs, and standardizes files for Aria & Monaco imports.
* **On-the-fly Recovery (Siemens EOF Fix):** Automatically fixes and parses truncated files lacking sequence delimiters.
* **Clear Directory Hierarchy:** Outputs structured patient datasets:  
  `Dicom_output / <PatientName>_<PatientID> / <Modality_SeriesDescription> / slice_XXXX.dcm`
* **Modern GUI:** Powered by `CustomTkinter` with a dark theme, real-time progress bar, and color-coded operation logs.

### Quick Start (Windows)
Double-click [run.bat](file:///c:/Users/Falco/Desktop/Dicom%20splitter/run.bat) in the project folder. It will configure the virtual environment and start the application automatically.

### Manual Installation
1. Create virtual environment: `python -m venv .venv`
2. Activate it: `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Linux/macOS)
3. Install dependencies: `pip install -r requirements.txt`
4. Launch the app: `python main.py`
