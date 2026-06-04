from datetime import datetime
from pathlib import Path
import threading
import traceback
from typing import Dict, List, Set, Union

import numpy as np
import pydicom
from pydicom.uid import generate_uid

from src.core.config import ProcessingConfig
from src.core.converter import (
    clean_and_build_dataset,
    copy_geometry_and_rescale,
    save_dicom_file,
)
from src.core.recovery import safe_dcmread
from src.utils.helpers import make_safe_filename
from src.utils.logger import BaseLogger

# Маппинг модальностей в стандартные SOP Class UID для Monaco и Aria
SOP_CLASS_MAPPING = {
    'MR': '1.2.840.10008.5.1.4.1.1.4',     # MR Image Storage
    'CT': '1.2.840.10008.5.1.4.1.1.2',     # CT Image Storage
    'PT': '1.2.840.10008.5.1.4.1.1.128',   # Positron Emission Tomography Image Storage
    'US': '1.2.840.10008.5.1.4.1.1.6.1',   # Ultrasound Image Storage
}
DEFAULT_SOP_CLASS = '1.2.840.10008.5.1.4.1.1.7'  # Secondary Capture Image Storage


class DicomProcessor:
    """Оркестратор процессов оптимизации и разделения файлов DICOM."""

    def __init__(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        config: ProcessingConfig,
        logger: BaseLogger,
        stop_event: threading.Event
    ) -> None:
        """Инициализация процессора.

        Args:
            input_dir: Входная директория с исходными DICOM-файлами.
            output_dir: Целевая директория для сохранения результатов.
            config: Объект с параметрами оптимизации.
            logger: Объект логгера для вывода сообщений.
            stop_event: Флаг принудительной остановки выполнения.
        """
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.config = config
        self.logger = logger
        self.stop_event = stop_event

    def process(self) -> None:
        """Запускает процесс обработки DICOM файлов."""
        self.logger.log("=== НАЧАЛО ОБРАБОТКИ DICOM ===")
        self.logger.log(f"Папка ввода: {self.input_dir}")
        self.logger.log(f"Папка вывода: {self.output_dir}")

        self.logger.log("Настройки:")
        self.logger.log(f" - Генерировать новые UID: {self.config.new_uids}")
        self.logger.log(f" - Разделять мультифреймы: {self.config.split_multiframe}")
        self.logger.log(f" - Очищать приватные теги: {self.config.clean_tags}")
        self.logger.log(f" - Заполнять теги по умолчанию: {self.config.default_tags}")
        self.logger.log(f" - Вывод в Explicit VR Little Endian: {self.config.explicit_vr}")
        self.logger.log(f" - Исключать отчеты/протоколы/топограммы: {self.config.exclude_reports}")

        try:
            if not self.input_dir.exists():
                self.logger.log(f"Ошибка: Входная папка не существует: {self.input_dir}", "error")
                return

            self.logger.log("Поиск DICOM-файлов...")
            all_files: List[Path] = []
            
            for file_path in self.input_dir.rglob("*"):
                if file_path.is_file():
                    if file_path.suffix.lower() == '.dcm' or '.' not in file_path.name:
                        all_files.append(file_path)

            total_files = len(all_files)
            if total_files == 0:
                self.logger.log(f"В папке {self.input_dir} файлы DICOM не найдены.", "warning")
                return

            self.logger.log(f"Найдено файлов для анализа: {total_files}")

            # Словари для маппинга UID (сохранение целостности связей)
            study_uid_map: Dict[str, str] = {}
            series_uid_map: Dict[str, str] = {}
            for_uid_map: Dict[str, str] = {}
            series_counters: Dict[str, int] = {}

            success_count = 0
            error_count = 0
            processed_count = 0
            non_dicom_count = 0
            no_pixel_count = 0
            excluded_count = 0
            start_time = datetime.now()

            for file_path in all_files:
                if self.stop_event.is_set():
                    self.logger.log("=== ОБРАБОТКА ОСТАНОВЛЕНА ПОЛЬЗОВАТЕЛЕМ ===", "warning")
                    break

                filename = file_path.name
                try:
                    # Двухэтапное чтение: сначала без пикселей для быстрой фильтрации
                    ds = safe_dcmread(file_path, stop_before_pixels=True)
                except ValueError as e:
                    self.logger.log(f"Не-DICOM или поврежденный файл {filename}: {e}", "warning")
                    non_dicom_count += 1
                    processed_count += 1
                    self.logger.update_progress(processed_count, total_files)
                    continue
                except Exception as e:
                    self.logger.log(f"Не удалось прочитать файл {filename}: {e}", "error")
                    error_count += 1
                    processed_count += 1
                    self.logger.update_progress(processed_count, total_files)
                    continue



                # Читаем основные теги
                patient_name = make_safe_filename(getattr(ds, 'PatientName', 'UNKNOWN'))
                patient_id = make_safe_filename(getattr(ds, 'PatientID', 'UNKNOWN'))
                patient_folder = f"{patient_name}_{patient_id}"

                modality = getattr(ds, 'Modality', 'OT')
                series_desc = make_safe_filename(getattr(ds, 'SeriesDescription', 'NoDescription'))

                # Исключение служебных серий
                if self.config.exclude_reports:
                    series_desc_lower = series_desc.lower()
                    exclude_keywords = {
                        'topogram', 'scout', 'patient protocol', 'dose report', 
                        'protocol', 'report', 'screenshot'
                    }
                    is_excluded = any(kw in series_desc_lower for kw in exclude_keywords) or modality in ('SR', 'PR')
                    if is_excluded:
                        self.logger.log(f"Пропущена служебная серия: {series_desc} ({modality})")
                        excluded_count += 1
                        processed_count += 1
                        self.logger.update_progress(processed_count, total_files)
                        continue

                series_folder = f"{modality}_{series_desc}"
                dest_dir = self.output_dir / patient_folder / series_folder
                dest_dir.mkdir(parents=True, exist_ok=True)

                sop_class = SOP_CLASS_MAPPING.get(modality, DEFAULT_SOP_CLASS)

                orig_study_uid = getattr(ds, 'StudyInstanceUID', None)
                if not orig_study_uid:
                    orig_study_uid = generate_uid()

                orig_series_uid = getattr(ds, 'SeriesInstanceUID', None)
                if not orig_series_uid:
                    orig_series_uid = generate_uid()

                orig_for_uid = getattr(ds, 'FrameOfReferenceUID', None)

                if self.config.new_uids:
                    study_uid = study_uid_map.setdefault(orig_study_uid, generate_uid())
                    series_uid = series_uid_map.setdefault(orig_series_uid, generate_uid())
                    if orig_for_uid:
                        for_uid = for_uid_map.setdefault(orig_for_uid, generate_uid())
                    else:
                        for_uid = generate_uid()
                else:
                    study_uid = orig_study_uid
                    series_uid = orig_series_uid
                    for_uid = orig_for_uid or generate_uid()

                try:
                    ds_full = safe_dcmread(file_path, stop_before_pixels=False)
                    
                    # Защита от файлов без пикселей (структурные отчеты, карты доз и т.д.)
                    has_pixels = any(tag in ds_full for tag in ['PixelData', 'FloatPixelData', 'DoubleFloatPixelData'])
                    if not has_pixels:
                        no_pixel_count += 1
                        processed_count += 1
                        self.logger.update_progress(processed_count, total_files)
                        continue

                    pixel_array = ds_full.pixel_array
                except Exception as e:
                    self.logger.log(f"Ошибка декодирования пикселей в {filename}: {e}", "error")
                    self.logger.log(traceback.format_exc(), "error")
                    error_count += 1
                    processed_count += 1
                    self.logger.update_progress(processed_count, total_files)
                    continue

                is_multiframe = hasattr(ds_full, 'NumberOfFrames') and int(ds_full.NumberOfFrames) > 1

                if is_multiframe and self.config.split_multiframe:
                    n_frames = int(ds_full.NumberOfFrames)
                    self.logger.log(f"Мультифрейм: {filename} ({n_frames} кадров) -> разделение...")

                    shared_info = ds_full.SharedFunctionalGroupsSequence[0] if hasattr(ds_full, 'SharedFunctionalGroupsSequence') else None
                    
                    if self.config.new_uids:
                        current_series_uid = generate_uid()
                    else:
                        current_series_uid = series_uid

                    multiframe_errors = 0
                    for i in range(n_frames):
                        if self.stop_event.is_set():
                            break

                        frame_info = ds_full.PerFrameFunctionalGroupsSequence[i] if hasattr(ds_full, 'PerFrameFunctionalGroupsSequence') else None

                        try:
                            cleaned_ds = clean_and_build_dataset(
                                src_ds=ds_full,
                                pixel_data=pixel_array[i],
                                instance_number=i + 1,
                                study_uid=study_uid,
                                series_uid=current_series_uid,
                                sop_class=sop_class,
                                for_uid=for_uid,
                                config=self.config
                            )

                            copy_geometry_and_rescale(
                                src_ds=ds_full,
                                new_ds=cleaned_ds,
                                frame_info=frame_info,
                                shared_info=shared_info,
                                is_multiframe=True,
                                frame_idx=i
                            )

                            out_path = dest_dir / f"slice_{i+1:04d}.dcm"
                            save_dicom_file(out_path, cleaned_ds, self.config.explicit_vr)
                            success_count += 1
                        except Exception as e:
                            self.logger.log(f"Ошибка сохранения кадра {i+1} из файла {filename}: {e}", "error")
                            self.logger.log(traceback.format_exc(), "error")
                            multiframe_errors += 1
                            error_count += 1

                    if self.stop_event.is_set():
                        self.logger.log("=== ОБРАБОТКА ОСТАНОВЛЕНА ПОЛЬЗОВАТЕЛЕМ ===", "warning")
                        break

                    if multiframe_errors == 0:
                        self.logger.log(
                            f"[{modality}] {patient_name} ({patient_id}) | "
                            f"{series_folder} | {filename} -> разделен на {n_frames} срезов", 
                            "success"
                        )
                    else:
                        self.logger.log(
                            f"[{modality}] {patient_name} ({patient_id}) | "
                            f"{series_folder} | {filename} -> разделен с {multiframe_errors} ошибками", 
                            "warning"
                        )

                else:
                    if series_uid not in series_counters:
                        series_counters[series_uid] = 1
                    else:
                        series_counters[series_uid] += 1

                    current_instance = getattr(ds_full, 'InstanceNumber', None)
                    if current_instance is None:
                        current_instance = series_counters[series_uid]
                    else:
                        try:
                            current_instance = int(current_instance)
                        except (ValueError, TypeError):
                            current_instance = series_counters[series_uid]

                    try:
                        cleaned_ds = clean_and_build_dataset(
                            src_ds=ds_full,
                            pixel_data=pixel_array,
                            instance_number=current_instance,
                            study_uid=study_uid,
                            series_uid=series_uid,
                            sop_class=sop_class,
                            for_uid=for_uid,
                            config=self.config
                        )

                        copy_geometry_and_rescale(
                            src_ds=ds_full,
                            new_ds=cleaned_ds,
                            frame_info=None,
                            shared_info=None,
                            is_multiframe=False,
                            frame_idx=0
                        )

                        out_path = dest_dir / f"slice_{current_instance:04d}.dcm"
                        save_dicom_file(out_path, cleaned_ds, self.config.explicit_vr)
                        self.logger.log(
                            f"[{modality}] {patient_name} ({patient_id}) | "
                            f"{series_folder} | {filename} -> slice_{current_instance:04d}.dcm"
                        )
                        success_count += 1
                    except Exception as e:
                        self.logger.log(f"Ошибка сохранения файла {filename}: {e}", "error")
                        self.logger.log(traceback.format_exc(), "error")
                        error_count += 1

                processed_count += 1
                self.logger.update_progress(processed_count, total_files)

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            self.logger.log("=" * 70)
            self.logger.log("ОТЧЕТ О ВЫПОЛНЕНИИ ОПЕРАЦИИ:")
            self.logger.log(f" - Найдено исходных файлов: {total_files}")
            self.logger.log(f" - Из них не-DICOM файлов: {non_dicom_count}")
            self.logger.log(f" - Пропущено файлов без пикселей: {no_pixel_count}")
            self.logger.log(f" - Исключено файлов служебных серий: {excluded_count}")
            self.logger.log(f" - Успешно сохранено срезов: {success_count}")
            self.logger.log(f" - Ошибок при обработке: {error_count}")
            self.logger.log(f" - Время выполнения: {duration:.1f} сек.")
            self.logger.log("=" * 70)

            if success_count > 0 and error_count == 0:
                self.logger.log("=== ОБРАБОТКА ЗАВЕРШЕНА УСПЕШНО ===", "success")
            elif success_count > 0 and error_count > 0:
                self.logger.log("=== ОБРАБОТКА ЗАВЕРШЕНА С ОШИБКАМИ ===", "warning")
            else:
                self.logger.log("=== ОБРАБОТКА ЗАВЕРШИЛАСЬ НЕУДАЧЕЙ ===", "error")

        except Exception as ex:
            self.logger.log(f"Критическая ошибка при обработке: {ex}", "error")
            self.logger.log(traceback.format_exc(), "error")
        finally:
            # Уведомляем вызывающий код о завершении, передавая финальный прогресс
            self.logger.update_progress(processed_count, total_files)
