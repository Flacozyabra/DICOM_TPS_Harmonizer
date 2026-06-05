from datetime import datetime
import json
import os
import queue
import sys
import threading
from pathlib import Path
from tkinter import filedialog
from typing import Any

from PIL import Image

import customtkinter as ctk

from src.core.config import ProcessingConfig
from src.core.processor import DicomProcessor
from src.utils.logger import QueueLogger

# Настройки оформления CustomTkinter
ctk.set_appearance_mode("dark")


class CustomQuestionDialog(ctk.CTkToplevel):
    """Кастомный диалог с вопросом о создании папок и тремя кнопками выбора."""

    def __init__(self, parent: ctk.CTk, title: str, message: str) -> None:
        super().__init__(parent)
        self.title(title)
        self.result = None

        self.geometry("400x150")
        self.resizable(False, False)
        
        # Поверх родительского окна и блокировка взаимодействия
        self.transient(parent)
        self.grab_set()

        # Центрирование относительно родителя
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 400) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 150) // 2
        self.geometry(f"+{x}+{y}")

        # Сообщение
        lbl = ctk.CTkLabel(self, text=message, wraplength=360, font=ctk.CTkFont(size=13))
        lbl.pack(pady=(20, 20), padx=20)

        # Контейнер для кнопок
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 15))

        # Кнопки: Да, Нет, Создать обе
        btn_yes = ctk.CTkButton(btn_frame, text="Да", width=90, command=self.on_yes)
        btn_yes.pack(side="left", padx=5, expand=True)

        btn_no = ctk.CTkButton(btn_frame, text="Нет", width=90, command=self.on_no)
        btn_no.pack(side="left", padx=5, expand=True)

        btn_both = ctk.CTkButton(btn_frame, text="Создать обе", width=120, command=self.on_both)
        btn_both.pack(side="left", padx=5, expand=True)

        # Ждем закрытия
        self.wait_window()

    def on_yes(self) -> None:
        self.result = "yes"
        self.destroy()

    def on_no(self) -> None:
        self.result = "no"
        self.destroy()

    def on_both(self) -> None:
        self.result = "both"
        self.destroy()


class DicomSplitterApp(ctk.CTk):
    """Главный класс графического интерфейса приложения DICOM TPS Harmonizer."""

    def __init__(self) -> None:
        super().__init__()
        
        self.title("DICOM TPS Harmonizer")
        
        # Определение путей к ресурсам относительно корня проекта с поддержкой PyInstaller
        if getattr(sys, "frozen", False):
            project_root = Path(sys._MEIPASS)
        else:
            project_root = Path(__file__).resolve().parents[2]
        theme_path = project_root / "themes" / "deep_dark.json"
        icon_path = project_root / "themes" / "app_icon.ico"
        
        # Установка темы
        if theme_path.exists():
            ctk.set_default_color_theme(str(theme_path))
            
        # Установка иконки приложения
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass

        width, height = 900, 720
        self.minimum_width = 800
        self.minimum_height = 620
        self.minsize(self.minimum_width, self.minimum_height)
        
        # Центрирование окна на экране при запуске
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

        # Очередь для вывода логов и прогресса из фонового потока
        self.log_queue: queue.Queue[tuple[str, Any, Any] | tuple[str, Any]] = queue.Queue()
        
        # Загрузка путей (с поддержкой AppData и плейсхолдеров при первом запуске)
        saved_input, saved_output = self.load_last_paths()
        self.input_dir_var = ctk.StringVar(value=saved_input)
        self.output_dir_var = ctk.StringVar(value=saved_output)
        
        # Переменные для чекбоксов настроек
        self.new_uids_var = ctk.BooleanVar(value=True)
        self.split_multiframe_var = ctk.BooleanVar(value=True)
        self.clean_tags_var = ctk.BooleanVar(value=True)
        self.default_tags_var = ctk.BooleanVar(value=True)
        self.explicit_vr_var = ctk.BooleanVar(value=True)
        self.exclude_reports_var = ctk.BooleanVar(value=True)

        self.is_processing = False
        self.stop_event = threading.Event()
        
        # Создание интерфейса
        self.create_widgets()
        
        # Запуск таймера для чтения логов из очереди в главном потоке
        self.after(100, self.update_log_queue)

    def get_config_path(self) -> Path:
        """Возвращает путь к файлу конфигурации в AppData пользователя."""
        appdata = os.getenv("APPDATA")
        if appdata:
            config_dir = Path(appdata) / "DicomTpsHarmonizer"
        else:
            config_dir = Path.home() / ".dicom_tps_harmonizer"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "config.json"

    def load_last_paths(self) -> tuple[str, str]:
        """Загружает последние выбранные пути.
        
        Если конфига нет (первый запуск), возвращает плейсхолдеры.
        """
        config_file = self.get_config_path()
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    inp = data.get("input_dir", "")
                    out = data.get("output_dir", "")
                    if inp and out:
                        return inp, out
            except Exception:
                pass
        return "Введите путь для папки Dicom_input", "Введите путь для папки Dicom_output"

    def save_last_paths(self) -> None:
        """Сохраняет текущие пути из GUI в файл конфигурации."""
        inp = self.input_dir_var.get()
        out = self.output_dir_var.get()
        
        # Не сохраняем плейсхолдеры
        if "Введите путь" in inp or "Введите путь" in out:
            return
            
        config_file = self.get_config_path()
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump({"input_dir": inp, "output_dir": out}, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def ask_and_create_folder(self, dir_type: str) -> None:
        """Запрашивает пользователя и создает соответствующую папку."""
        folder_name = "Dicom_input" if dir_type == "input" else "Dicom_output"
        message = f"Создать папку {folder_name} в папке с программой?"
        
        dialog = CustomQuestionDialog(self, "Создание папки", message)
        result = dialog.result
        
        if not result or result == "no":
            return
            
        # Определяем директорию запуска (учитываем скомпилированный EXE)
        if getattr(sys, "frozen", False):
            app_dir = Path(sys.executable).parent
        else:
            app_dir = Path(__file__).resolve().parents[2]
            
        input_path = app_dir / "Dicom_input"
        output_path = app_dir / "Dicom_output"
        
        if result == "yes":
            target_path = input_path if dir_type == "input" else output_path
            try:
                target_path.mkdir(parents=True, exist_ok=True)
                if dir_type == "input":
                    self.input_dir_var.set(str(target_path.resolve()))
                else:
                    self.output_dir_var.set(str(target_path.resolve()))
                self.log_queue.put(("log", f"Создана папка: {target_path.resolve()}", "success"))
            except Exception as e:
                self.log_queue.put(("log", f"Ошибка при создании папки: {e}", "error"))
                
        elif result == "both":
            try:
                input_path.mkdir(parents=True, exist_ok=True)
                output_path.mkdir(parents=True, exist_ok=True)
                self.input_dir_var.set(str(input_path.resolve()))
                self.output_dir_var.set(str(output_path.resolve()))
                self.log_queue.put(("log", f"Созданы папки: {input_path.resolve()} и {output_path.resolve()}", "success"))
            except Exception as e:
                self.log_queue.put(("log", f"Ошибка при создании папок: {e}", "error"))
                
        self.save_last_paths()

    def create_widgets(self) -> None:
        """Инициализирует и позиционирует все виджеты на форме."""
        # Конфигурация сетки главного окна
        self.grid_rowconfigure(3, weight=1)  # Текстовое окно лога растягивается по вертикали
        self.grid_columnconfigure(0, weight=1)
        
        # Загрузка иконок для кнопок
        if getattr(sys, "frozen", False):
            resources_dir = Path(sys._MEIPASS) / "themes"
        else:
            resources_dir = Path(__file__).resolve().parents[2] / "themes"
            
        icon_create_path = resources_dir / "create_folder.png"
        icon_open_in_path = resources_dir / "open_folder_input.png"
        icon_open_out_path = resources_dir / "open_folder_output.png"
        
        self.img_create = ctk.CTkImage(Image.open(icon_create_path), size=(20, 20)) if icon_create_path.exists() else None
        self.img_open_in = ctk.CTkImage(Image.open(icon_open_in_path), size=(20, 20)) if icon_open_in_path.exists() else None
        self.img_open_out = ctk.CTkImage(Image.open(icon_open_out_path), size=(20, 20)) if icon_open_out_path.exists() else None

        # 1. Заголовок
        title_label = ctk.CTkLabel(
            self, 
            text="DICOM TPS Harmonizer", 
            font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold")
        )
        title_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")
        
        # 2. Выбор папок
        folder_frame = ctk.CTkFrame(self)
        folder_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        
        folder_frame.grid_columnconfigure(0, weight=0)
        folder_frame.grid_columnconfigure(1, weight=0)
        folder_frame.grid_columnconfigure(2, weight=1)
        folder_frame.grid_columnconfigure(3, weight=0)
        folder_frame.grid_columnconfigure(4, weight=0)
        
        # Папка ввода
        input_create_btn = ctk.CTkButton(
            folder_frame,
            text="",
            image=self.img_create,
            width=30,
            height=30,
            fg_color="transparent",
            hover_color=("#E5E7EB", "#374151"),
            command=lambda: self.ask_and_create_folder("input")
        )
        input_create_btn.grid(row=0, column=0, padx=(10, 5), pady=10)
        
        input_label = ctk.CTkLabel(folder_frame, text="Папка ввода:", font=ctk.CTkFont(size=13, weight="bold"))
        input_label.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="w")
        
        input_entry = ctk.CTkEntry(folder_frame, textvariable=self.input_dir_var)
        input_entry.grid(row=0, column=2, padx=10, pady=10, sticky="ew")
        
        input_open_btn = ctk.CTkButton(
            folder_frame,
            text="",
            image=self.img_open_in,
            width=30,
            height=30,
            fg_color="transparent",
            hover_color=("#E5E7EB", "#374151"),
            command=self.open_input_dir
        )
        input_open_btn.grid(row=0, column=3, padx=(5, 10), pady=10)
        
        input_btn = ctk.CTkButton(folder_frame, text="Обзор...", width=100, command=self.browse_input)
        input_btn.grid(row=0, column=4, padx=(0, 10), pady=10)
        
        # Папка вывода
        output_create_btn = ctk.CTkButton(
            folder_frame,
            text="",
            image=self.img_create,
            width=30,
            height=30,
            fg_color="transparent",
            hover_color=("#E5E7EB", "#374151"),
            command=lambda: self.ask_and_create_folder("output")
        )
        output_create_btn.grid(row=1, column=0, padx=(10, 5), pady=(0, 10))
        
        output_label = ctk.CTkLabel(folder_frame, text="Папка вывода:", font=ctk.CTkFont(size=13, weight="bold"))
        output_label.grid(row=1, column=1, padx=(5, 10), pady=(0, 10), sticky="w")
        
        output_entry = ctk.CTkEntry(folder_frame, textvariable=self.output_dir_var)
        output_entry.grid(row=1, column=2, padx=10, pady=(0, 10), sticky="ew")
        
        output_open_btn = ctk.CTkButton(
            folder_frame,
            text="",
            image=self.img_open_out,
            width=30,
            height=30,
            fg_color="transparent",
            hover_color=("#E5E7EB", "#374151"),
            command=self.open_output_dir
        )
        output_open_btn.grid(row=1, column=3, padx=(5, 10), pady=(0, 10))
        
        output_btn = ctk.CTkButton(folder_frame, text="Обзор...", width=100, command=self.browse_output)
        output_btn.grid(row=1, column=4, padx=(0, 10), pady=(0, 10))

        # 3. Настройки (Чекбоксы)
        settings_frame = ctk.CTkFrame(self)
        settings_frame.grid(row=2, column=0, padx=20, pady=10, sticky="nsew")
        settings_frame.grid_columnconfigure((0, 1), weight=1)
        
        settings_title = ctk.CTkLabel(settings_frame, text="Параметры оптимизации", font=ctk.CTkFont(size=14, weight="bold"))
        settings_title.grid(row=0, column=0, columnspan=2, padx=15, pady=(10, 5), sticky="w")
        
        cb_new_uids = ctk.CTkCheckBox(
            settings_frame, 
            text="Генерировать новые UID (Study, Series, SOP)", 
            variable=self.new_uids_var
        )
        cb_new_uids.grid(row=1, column=0, padx=15, pady=5, sticky="w")
        
        cb_split_mf = ctk.CTkCheckBox(
            settings_frame, 
            text="Разделить Multi-frame на Single-frame", 
            variable=self.split_multiframe_var
        )
        cb_split_mf.grid(row=1, column=1, padx=15, pady=5, sticky="w")
        
        cb_clean_tags = ctk.CTkCheckBox(
            settings_frame, 
            text="Очищать приватные и несовместимые теги", 
            variable=self.clean_tags_var
        )
        cb_clean_tags.grid(row=2, column=0, padx=15, pady=5, sticky="w")
        
        cb_default_tags = ctk.CTkCheckBox(
            settings_frame, 
            text="Заполнять обязательные теги по умолчанию", 
            variable=self.default_tags_var
        )
        cb_default_tags.grid(row=2, column=1, padx=15, pady=5, sticky="w")
        
        cb_explicit_vr = ctk.CTkCheckBox(
            settings_frame, 
            text="Запись в формате Explicit VR Little Endian (несжатый)", 
            variable=self.explicit_vr_var
        )
        cb_explicit_vr.grid(row=3, column=0, padx=15, pady=(5, 10), sticky="w")

        cb_exclude_reports = ctk.CTkCheckBox(
            settings_frame, 
            text="Исключать отчеты, протоколы и топограммы", 
            variable=self.exclude_reports_var
        )
        cb_exclude_reports.grid(row=3, column=1, padx=15, pady=(5, 10), sticky="w")

        # 4. Поле для вывода логов
        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=3, column=0, padx=20, pady=10, sticky="nsew")
        log_frame.grid_rowconfigure(1, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        
        log_title = ctk.CTkLabel(log_frame, text="Ход выполнения операций", font=ctk.CTkFont(size=14, weight="bold"))
        log_title.grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")
        
        self.log_textbox = ctk.CTkTextbox(log_frame, font=ctk.CTkFont(family="Consolas", size=11))
        self.log_textbox.grid(row=1, column=0, padx=15, pady=(0, 10), sticky="nsew")
        self.log_textbox.configure(state="disabled")
        
        # Настройка цветовых тегов для лога
        self.log_textbox.tag_config("info", foreground="white")
        self.log_textbox.tag_config("warning", foreground="#ffb347")
        self.log_textbox.tag_config("error", foreground="#ff6961")
        self.log_textbox.tag_config("success", foreground="#77dd77")

        # 5. Управление и прогресс
        control_frame = ctk.CTkFrame(self)
        control_frame.grid(row=4, column=0, padx=20, pady=(0, 20), sticky="nsew")
        
        control_frame.grid_columnconfigure(0, weight=1)
        control_frame.grid_rowconfigure((0, 1, 2), weight=1)
        
        # Прогресс-бар
        self.progress_bar = ctk.CTkProgressBar(
            control_frame, 
            height=18, 
            corner_radius=8,
            border_width=1
        )
        self.progress_bar.grid(row=0, column=0, padx=15, pady=(15, 2), sticky="ew")
        self.progress_bar.set(0)
        
        # Процентный индикатор под прогресс-баром
        self.percent_label = ctk.CTkLabel(
            control_frame, 
            text="Готов к работе (0%)", 
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.percent_label.grid(row=1, column=0, padx=15, pady=(0, 10), sticky="n")
        
        # Кнопка запуска оптимизации
        self.start_btn = ctk.CTkButton(
            control_frame, 
            text="Запустить оптимизацию", 
            font=ctk.CTkFont(weight="bold"),
            width=300,
            height=40,
            command=self.start_processing
        )
        self.start_btn.grid(row=2, column=0, padx=15, pady=(0, 15), sticky="n")

    # Методы обзора папок
    def browse_input(self) -> None:
        """Открывает диалог выбора входной папки."""
        initial = self.input_dir_var.get()
        if "Введите путь" in initial:
            initial = None
        dir_path = filedialog.askdirectory(initialdir=initial)
        if dir_path:
            self.input_dir_var.set(str(Path(dir_path).resolve()))
            self.save_last_paths()

    def browse_output(self) -> None:
        """Открывает диалог выбора папки для вывода."""
        initial = self.output_dir_var.get()
        if "Введите путь" in initial:
            initial = None
        dir_path = filedialog.askdirectory(initialdir=initial)
        if dir_path:
            self.output_dir_var.set(str(Path(dir_path).resolve()))
            self.save_last_paths()

    def open_input_dir(self) -> None:
        """Открывает входную папку в Проводнике Windows."""
        inp_dir = self.input_dir_var.get()
        if "Введите путь" in inp_dir:
            self.log_queue.put(("log", "Ошибка: Путь ввода не настроен.", "error"))
            return
            
        path = Path(inp_dir)
        if path.exists():
            import os
            os.startfile(path)
        else:
            self.log_queue.put(("log", f"Папка ввода не существует: {path}", "warning"))

    def open_output_dir(self) -> None:
        """Открывает выходную папку в Проводнике Windows."""
        out_dir = self.output_dir_var.get()
        if "Введите путь" in out_dir:
            self.log_queue.put(("log", "Ошибка: Путь вывода не настроен.", "error"))
            return
            
        path = Path(out_dir)
        if path.exists():
            import os
            os.startfile(path)
        else:
            self.log_queue.put(("log", f"Папка вывода не существует: {path}", "warning"))

    def update_log_queue(self) -> None:
        """Периодически опрашивает очередь и безопасно обновляет виджеты в главном потоке."""
        try:
            while True:
                msg = self.log_queue.get_nowait()
                msg_type = msg[0]
                
                if msg_type == "log":
                    _, text, tag = msg
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    formatted_text = f"[{timestamp}] {text}\n"
                    self.log_textbox.configure(state="normal")
                    self.log_textbox.insert("end", formatted_text, tag)
                    self.log_textbox.configure(state="disabled")
                    self.log_textbox.yview("end")
                    
                elif msg_type == "progress":
                    _, current, total = msg
                    if total > 0:
                        prog = current / total
                        self.progress_bar.set(prog)
                        if self.is_processing and not self.stop_event.is_set():
                            self.percent_label.configure(text=f"Обработка... {int(prog * 100)}%")
                            
                elif msg_type == "finished":
                    self.is_processing = False
                    self.start_btn.configure(
                        text="Запустить оптимизацию", 
                        fg_color=("#3B82F6", "#1D4ED8"), 
                        hover_color=("#2563EB", "#1E40AF"),
                        state="normal"
                    )
                    if self.stop_event.is_set():
                        self.percent_label.configure(text="Готово (обратка остановлена)")
                    else:
                        self.percent_label.configure(text="Готово")
                    self.set_gui_state(True)
                    
                self.log_queue.task_done()
        except queue.Empty:
            pass
            
        self.after(100, self.update_log_queue)

    def set_gui_state(self, enabled: bool) -> None:
        """Включает или отключает интерактивные элементы управления."""
        state = "normal" if enabled else "disabled"
        self.start_btn.configure(state=state)

    def start_processing(self) -> None:
        """Запускает или останавливает фоновый поток обработки DICOM."""
        if self.is_processing:
            self.stop_event.set()
            self.start_btn.configure(text="Останавливается...", state="disabled")
            self.percent_label.configure(text="Остановка процесса...")
            return

        input_raw = self.input_dir_var.get()
        output_raw = self.output_dir_var.get()

        if "Введите путь" in input_raw or "Введите путь" in output_raw:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert(
                "end", 
                f"[{timestamp}] Ошибка: Перед запуском оптимизации необходимо указать пути к папкам ввода и вывода.\n", 
                "error"
            )
            self.log_textbox.configure(state="disabled")
            return

        input_dir = Path(input_raw)
        output_dir = Path(output_raw)

        if not input_dir.exists():
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert(
                "end", 
                f"[{timestamp}] Ошибка: Входная папка не существует: {input_dir}\n", 
                "error"
            )
            self.log_textbox.configure(state="disabled")
            return

        self.is_processing = True
        self.stop_event.clear()
        
        self.start_btn.configure(
            text="Остановить оптимизацию", 
            fg_color="#ef4444", 
            hover_color="#dc2626"
        )
        
        self.percent_label.configure(text="Запуск (0%)")
        self.progress_bar.set(0)
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

        # Создаем DTO настроек
        config = ProcessingConfig(
            new_uids=self.new_uids_var.get(),
            split_multiframe=self.split_multiframe_var.get(),
            clean_tags=self.clean_tags_var.get(),
            default_tags=self.default_tags_var.get(),
            explicit_vr=self.explicit_vr_var.get(),
            exclude_reports=self.exclude_reports_var.get()
        )

        logger = QueueLogger(self.log_queue)
        processor = DicomProcessor(input_dir, output_dir, config, logger, self.stop_event)

        # Запускаем обработку в фоновом потоке
        threading.Thread(
            target=self._run_processor, 
            args=(processor,), 
            daemon=True
        ).start()

    def _run_processor(self, processor: DicomProcessor) -> None:
        """Функция-обертка для запуска процессора в отдельном потоке."""
        try:
            processor.process()
        finally:
            # Уведомляем GUI о завершении работы
            self.log_queue.put(("finished",))
