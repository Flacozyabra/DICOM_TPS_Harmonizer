from datetime import datetime
import json
import os
from pathlib import Path
import sys
import threading
import traceback
from typing import Any, Dict, List, Set, Union
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

import numpy as np
import pydicom
from pydicom.uid import generate_uid

from src.core.config import ProcessingConfig
from src.core.converter import (
    clean_and_build_dataset,
    clean_and_build_dataset_inplace,
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


def _process_batch_task(batch_task: dict) -> dict:
    """Глобальный воркер для обработки пакета (серии) DICOM файлов в одном дочернем процессе.

    Принимает словарь параметров задачи и обрабатывает список файлов, входящих в пакет.
    """
    tasks = batch_task['tasks']
    config = batch_task['config']
    
    results = {
        'status': 'success',
        'logs': [],
        'success_count': 0,
        'error_count': 0,
        'no_pixel_count': 0,
    }
    
    if not tasks:
        return results

    # Для агрегации логов по всей серии
    first_task = tasks[0]
    modality = first_task['modality']
    pat_name = first_task['pat_name']
    pat_id = first_task['pat_id']
    series_folder = first_task['series_folder']
    
    series_success = 0
    series_errors = 0
    
    for task in tasks:
        file_path = task['file_path']
        dest_dir = task['dest_dir']
        study_uid_mapped = task['study_uid_mapped']
        series_uid_mapped = task['series_uid_mapped']
        for_uid_mapped = task['for_uid_mapped']
        sop_class = task['sop_class']
        instance_number = task['instance_number']
        segment_idx = task['segment_idx']
        
        filename = file_path.name
        
        try:
            ds_full = safe_dcmread(file_path, stop_before_pixels=False)
            
            # Защита от файлов без пикселей
            has_pixels = any(tag in ds_full for tag in ['PixelData', 'FloatPixelData', 'DoubleFloatPixelData'])
            if not has_pixels:
                results['no_pixel_count'] += 1
                continue
                
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            results['status'] = 'error'
            results['error_count'] += 1
            series_errors += 1
            results['logs'].append(('log_pixel_error', filename, str(e)))
            results['logs'].append(('traceback', tb))
            continue

        is_multiframe = hasattr(ds_full, 'NumberOfFrames') and int(ds_full.NumberOfFrames) > 1

        if is_multiframe and config.split_multiframe:
            try:
                pixel_array = ds_full.pixel_array
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                results['status'] = 'error'
                results['error_count'] += 1
                series_errors += 1
                results['logs'].append(('log_pixel_error', filename, str(e)))
                results['logs'].append(('traceback', tb))
                continue

            n_frames = int(ds_full.NumberOfFrames)
            results['logs'].append(('log_split_multiframe', filename, n_frames))

            shared_info = ds_full.SharedFunctionalGroupsSequence[0] if hasattr(ds_full, 'SharedFunctionalGroupsSequence') else None
            
            if config.new_uids or segment_idx > 0:
                from pydicom.uid import generate_uid
                current_series_uid = generate_uid()
            else:
                current_series_uid = series_uid_mapped

            multiframe_errors = 0
            for i in range(n_frames):
                frame_info = ds_full.PerFrameFunctionalGroupsSequence[i] if hasattr(ds_full, 'PerFrameFunctionalGroupsSequence') else None

                try:
                    cleaned_ds = clean_and_build_dataset(
                        src_ds=ds_full,
                        pixel_data=pixel_array[i],
                        instance_number=i + 1,
                        study_uid=study_uid_mapped,
                        series_uid=current_series_uid,
                        sop_class=sop_class,
                        for_uid=for_uid_mapped,
                        config=config
                    )

                    cleaned_ds.PatientName = pat_name
                    cleaned_ds.PatientID = pat_id

                    copy_geometry_and_rescale(
                        src_ds=ds_full,
                        new_ds=cleaned_ds,
                        frame_info=frame_info,
                        shared_info=shared_info,
                        is_multiframe=True,
                        frame_idx=i
                    )

                    out_path = dest_dir / f"slice_{i+1:04d}.dcm"
                    save_dicom_file(out_path, cleaned_ds, config.explicit_vr)
                    results['success_count'] += 1
                    series_success += 1
                except Exception as e:
                    import traceback
                    tb = traceback.format_exc()
                    results['logs'].append(('log_frame_save_error', i + 1, filename, str(e)))
                    results['logs'].append(('traceback', tb))
                    multiframe_errors += 1
                    results['error_count'] += 1
                    series_errors += 1

            if multiframe_errors == 0:
                results['logs'].append(('log_split_success', modality, pat_name, pat_id, series_folder, filename, n_frames))
            else:
                results['logs'].append(('log_split_warning', modality, pat_name, pat_id, series_folder, filename, multiframe_errors))

        else:
            try:
                # Оптимизированный in-place путь для single-frame файлов
                cleaned_ds = clean_and_build_dataset_inplace(
                    src_ds=ds_full,
                    instance_number=instance_number,
                    study_uid=study_uid_mapped,
                    series_uid=series_uid_mapped,
                    sop_class=sop_class,
                    for_uid=for_uid_mapped,
                    config=config
                )

                cleaned_ds.PatientName = pat_name
                cleaned_ds.PatientID = pat_id

                copy_geometry_and_rescale(
                    src_ds=ds_full,
                    new_ds=cleaned_ds,
                    frame_info=None,
                    shared_info=None,
                    is_multiframe=False,
                    frame_idx=0
                )

                out_path = dest_dir / f"slice_{instance_number:04d}.dcm"
                save_dicom_file(out_path, cleaned_ds, config.explicit_vr)
                results['success_count'] += 1
                series_success += 1
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                results['logs'].append(('log_save_error', filename, str(e)))
                results['logs'].append(('traceback', tb))
                results['error_count'] += 1
                series_errors += 1
                results['status'] = 'error'

    # Добавляем агрегированный лог по серии
    if series_success > 0:
        if series_errors == 0:
            results['logs'].append(('log_series_success', modality, pat_name, pat_id, series_folder, series_success))
        else:
            results['logs'].append(('log_series_warning', modality, pat_name, pat_id, series_folder, series_success, series_errors))

    return results


def _read_header_task(file_path: Path) -> tuple:
    """Вспомогательная функция для параллельного чтения заголовков DICOM файлов."""
    try:
        ds = safe_dcmread(file_path, stop_before_pixels=True)
        return file_path, ds, None
    except Exception as e:
        return file_path, None, e


class DicomProcessor:
    """Оркестратор процессов оптимизации и разделения файлов DICOM."""

    def __init__(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        config: ProcessingConfig,
        logger: BaseLogger,
        stop_event: threading.Event,
        lang: str = "ru",
        selected_files: List[Path] = None,
        patient_overrides: Dict[tuple, tuple] = None
    ) -> None:
        """Инициализация процессора.

        Args:
            input_dir: Входная директория с исходными DICOM-файлами.
            output_dir: Целевая директория для сохранения результатов.
            config: Объект с параметрами оптимизации.
            logger: Объект логгера для вывода сообщений.
            stop_event: Флаг принудительной остановки выполнения.
            lang: Язык логирования ("ru" или "en").
            selected_files: Список файлов для обработки.
            patient_overrides: Словарь переопределения имен/ID пациентов.
        """
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.config = config
        self.logger = logger
        self.stop_event = stop_event
        self.lang = lang
        self.selected_files = selected_files
        self.patient_overrides = patient_overrides
        self.translations = self._load_translations(lang)
        self.study_uid_map: Dict[str, str] = {}
        self.series_uid_map: Dict[str, str] = {}
        self.for_uid_map: Dict[str, str] = {}
        self.series_counters: Dict[str, int] = {}

    def _load_translations(self, lang: str) -> Dict[str, str]:
        """Загружает файл локализации для процессора."""
        if getattr(sys, "frozen", False):
            locales_dir = Path(sys._MEIPASS) / "locales"
        else:
            locales_dir = Path(__file__).resolve().parents[2] / "locales"
            
        locale_file = locales_dir / f"{lang}.json"
        if locale_file.exists():
            try:
                with open(locale_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def loc(self, key: str, *args) -> str:
        """Возвращает строку перевода по ключу."""
        val = self.translations.get(key, key)
        if args:
            try:
                return val.format(*args)
            except Exception:
                pass
        return val

    def process(self) -> None:
        """Запускает процесс обработки DICOM файлов в многопроцессном режиме."""
        self.logger.log(self.loc("log_start"))
        self.logger.log(self.loc("log_input_dir", self.input_dir))
        self.logger.log(self.loc("log_output_dir", self.output_dir))

        self.logger.log(self.loc("log_settings"))
        self.logger.log(self.loc("log_setting_uids", self.config.new_uids))
        self.logger.log(self.loc("log_setting_split", self.config.split_multiframe))
        self.logger.log(self.loc("log_setting_clean", self.config.clean_tags))
        self.logger.log(self.loc("log_setting_default", self.config.default_tags))
        self.logger.log(self.loc("log_setting_explicit", self.config.explicit_vr))
        self.logger.log(self.loc("log_setting_exclude", self.config.exclude_reports))
        self.logger.log(self.loc("log_setting_exclude_localizers", self.config.exclude_localizers))

        try:
            if self.selected_files is not None:
                all_files = self.selected_files
            else:
                if not self.input_dir.exists():
                    self.logger.log(self.loc("error_input_not_exist", self.input_dir), "error")
                    return

                self.logger.log(self.loc("log_search_files"))
                all_files = []
                for file_path in self.input_dir.rglob("*"):
                    if file_path.is_file():
                        if file_path.suffix.lower() == '.dcm' or '.' not in file_path.name:
                            all_files.append(file_path)

            total_files = len(all_files)
            if total_files == 0:
                self.logger.log(self.loc("log_files_not_found", self.input_dir), "warning")
                return

            self.logger.log(self.loc("log_files_found", total_files))

            self.success_count = 0
            self.error_count = 0
            self.processed_count = 0
            self.non_dicom_count = 0
            self.no_pixel_count = 0
            self.excluded_count = 0
            start_time = datetime.now()

            # Группируем файлы по сериям для предварительного анализа (параллельный быстрый проход)
            series_groups = {}
            
            # Используем ThreadPoolExecutor для параллельного чтения заголовков (I/O)
            with ThreadPoolExecutor(max_workers=32) as header_executor:
                if self.stop_event.is_set():
                    self.logger.log(self.loc("log_stop_user"), "warning")
                    return
                
                header_futures = [header_executor.submit(_read_header_task, fp) for fp in all_files]
                for fut in as_completed(header_futures):
                    if self.stop_event.is_set():
                        self.logger.log(self.loc("log_stop_user"), "warning")
                        break
                    
                    file_path, ds, err = fut.result()
                    filename = file_path.name
                    if err is not None:
                        if isinstance(err, ValueError):
                            self.logger.log(self.loc("log_non_dicom", filename, str(err)), "warning")
                            self.non_dicom_count += 1
                        else:
                            self.logger.log(self.loc("log_read_error", filename, str(err)), "error")
                            self.error_count += 1
                        self.processed_count += 1
                        self.logger.update_progress(self.processed_count, total_files)
                        continue
                    
                    pat_name = getattr(ds, 'PatientName', 'UNKNOWN')
                    pat_id = getattr(ds, 'PatientID', 'UNKNOWN')

                    if self.patient_overrides and (str(pat_name), str(pat_id)) in self.patient_overrides:
                        pat_name, pat_id = self.patient_overrides[(str(pat_name), str(pat_id))]

                    study_uid = getattr(ds, 'StudyInstanceUID', 'unknown_study')
                    series_uid = getattr(ds, 'SeriesInstanceUID', 'unknown_series')

                    if not pat_name:
                        pat_name = "UNKNOWN"
                    if not pat_id:
                        pat_id = "UNKNOWN"

                    key = (str(pat_name), str(pat_id), str(study_uid), str(series_uid))
                    series_groups.setdefault(key, []).append((file_path, ds))

            # Собираем все подзадачи
            sub_tasks = []
            for (pat_name, pat_id, study_uid, series_uid), items in series_groups.items():
                if self.stop_event.is_set():
                    break

                # Группируем элементы серии по ImageOrientationPatient для геометрического разделения
                orientation_groups = {}
                for file_path, ds in items:
                    orientation_key = None
                    if hasattr(ds, 'ImageOrientationPatient'):
                        try:
                            orientation_key = tuple(round(float(x), 4) for x in ds.ImageOrientationPatient)
                        except Exception:
                            pass
                    orientation_groups.setdefault(orientation_key, []).append((file_path, ds))

                # Если включено разделение серий и у нас несколько ориентаций
                if self.config.split_series and len(orientation_groups) > 1:
                    seg_idx = 1
                    for ori_key, group_items in sorted(orientation_groups.items(), key=lambda x: str(x[0])):
                        self._prepare_tasks_for_segment(
                            pat_name, pat_id, study_uid, series_uid,
                            group_items, segment_idx=seg_idx, total_files=total_files, tasks_list=sub_tasks
                        )
                        seg_idx += 1
                else:
                    self._prepare_tasks_for_segment(
                        pat_name, pat_id, study_uid, series_uid,
                        items, segment_idx=0, total_files=total_files, tasks_list=sub_tasks
                    )

            # Группируем sub_tasks по series_uid_mapped, чтобы каждая серия обрабатывалась
            # в своем пакете (или делим серии на чанки по 50 файлов для балансировки нагрузки)
            from collections import defaultdict
            series_tasks = defaultdict(list)
            for task in sub_tasks:
                series_tasks[task['series_uid_mapped']].append(task)
                
            batch_tasks = []
            for s_uid, s_tasks in series_tasks.items():
                chunk_size = 50
                for i in range(0, len(s_tasks), chunk_size):
                    batch_tasks.append({
                        'tasks': s_tasks[i:i + chunk_size],
                        'config': self.config
                    })

            # Выполняем задачи в пуле процессов
            if batch_tasks and not self.stop_event.is_set():
                num_workers = max(1, (os.cpu_count() or 4) - 1)
                
                futures = {}
                with ProcessPoolExecutor(max_workers=num_workers) as executor:
                    for b_task in batch_tasks:
                        if self.stop_event.is_set():
                            break
                        fut = executor.submit(_process_batch_task, b_task)
                        futures[fut] = b_task

                    for fut in as_completed(futures):
                        if self.stop_event.is_set():
                            executor.shutdown(wait=False, cancel_futures=True)
                            self.logger.log(self.loc("log_stop_user"), "warning")
                            break

                        try:
                            res = fut.result()
                            self.success_count += res['success_count']
                            self.error_count += res['error_count']
                            self.no_pixel_count += res['no_pixel_count']

                            for log_item in res['logs']:
                                key = log_item[0]
                                args = log_item[1:]
                                if key == 'traceback':
                                    self.logger.log(args[0], "error")
                                else:
                                    # Определяем тег лога
                                    if key in ('log_pixel_error', 'log_frame_save_error', 'log_save_error', 'log_critical_error'):
                                        tag = "error"
                                    elif key in ('log_non_dicom', 'log_read_error', 'log_split_warning', 'log_files_not_found', 'log_stop_user', 'log_series_warning'):
                                        tag = "warning"
                                    elif key in ('log_finished_success', 'log_split_success', 'log_series_success'):
                                        tag = "success"
                                    else:
                                        tag = "info"
                                    self.logger.log(self.loc(key, *args), tag)
                        except Exception as e:
                            self.logger.log(self.loc("log_critical_error", str(e)), "error")
                            self.error_count += 1

                        # Обновляем прогресс на число файлов в этом батче
                        b_task_files_count = len(futures[fut]['tasks'])
                        self.processed_count += b_task_files_count
                        self.logger.update_progress(self.processed_count, total_files)

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            self.logger.log(self.loc("log_report_separator"))
            self.logger.log(self.loc("log_report_title"))
            self.logger.log(self.loc("log_report_found", total_files))
            self.logger.log(self.loc("log_report_non_dicom", self.non_dicom_count))
            self.logger.log(self.loc("log_report_no_pixels", self.no_pixel_count))
            self.logger.log(self.loc("log_report_excluded", self.excluded_count))
            self.logger.log(self.loc("log_report_saved", self.success_count))
            self.logger.log(self.loc("log_report_errors", self.error_count))
            self.logger.log(self.loc("log_report_duration", duration))
            self.logger.log(self.loc("log_report_separator"))

            if self.success_count > 0 and self.error_count == 0:
                self.logger.log(self.loc("log_finished_success"), "success")
            elif self.success_count > 0 and self.error_count > 0:
                self.logger.log(self.loc("log_finished_warning"), "warning")
            else:
                self.logger.log(self.loc("log_finished_error"), "error")

        except Exception as ex:
            self.logger.log(self.loc("log_critical_error", ex), "error")
            self.logger.log(traceback.format_exc(), "error")
        finally:
            self.logger.update_progress(self.processed_count, total_files)

    def _prepare_tasks_for_segment(
        self,
        pat_name: str,
        pat_id: str,
        study_uid: str,
        series_uid: str,
        items: List[tuple],
        segment_idx: int,
        total_files: int,
        tasks_list: list
    ) -> None:
        """Подготавливает задачи оптимизации для конкретного сегмента серии."""
        first_file_path, first_ds = items[0]
        modality = getattr(first_ds, 'Modality', 'OT')
        series_desc = make_safe_filename(getattr(first_ds, 'SeriesDescription', 'NoDescription'))

        if segment_idx > 0:
            series_desc = f"{series_desc}_Seg{segment_idx}"

        # Извлекаем SeriesNumber для предотвращения дублирования имен папок разных серий
        series_num = getattr(first_ds, 'SeriesNumber', None)
        series_num_str = make_safe_filename(str(series_num)).strip() if series_num is not None else ""

        # Проверка на исключение служебных серий до создания папок
        if self.config.exclude_reports:
            series_desc_lower = series_desc.lower()
            exclude_keywords = {
                'topogram', 'scout', 'patient protocol', 'dose report', 
                'protocol', 'report', 'screenshot'
            }
            is_excluded = any(kw in series_desc_lower for kw in exclude_keywords) or modality in ('SR', 'PR')
            if is_excluded:
                self.logger.log(self.loc("log_skip_service", series_desc, modality))
                self.excluded_count += len(items)
                self.processed_count += len(items)
                self.logger.update_progress(self.processed_count, total_files)
                return

        # Исключение локалайзеров
        if self.config.exclude_localizers:
            is_localizer = False
            series_desc_lower = series_desc.lower()
            if 'localizer' in series_desc_lower or 'scout' in series_desc_lower or 'topogram' in series_desc_lower:
                is_localizer = True
            
            if not is_localizer:
                try:
                    image_type = getattr(first_ds, 'ImageType', [])
                    if image_type:
                        if isinstance(image_type, str):
                            image_type = [image_type]
                        if any('LOCALIZER' in str(t).upper() for t in image_type):
                            is_localizer = True
                except Exception:
                    pass
            
            if is_localizer:
                self.logger.log(self.loc("log_skip_localizer", series_desc, modality))
                self.excluded_count += len(items)
                self.processed_count += len(items)
                self.logger.update_progress(self.processed_count, total_files)
                return

        patient_name = make_safe_filename(pat_name)
        patient_id = make_safe_filename(pat_id)
        patient_folder = f"{patient_name}_{patient_id}"
        
        if series_num_str:
            series_folder = f"{modality}_{series_num_str}_{series_desc}"
        else:
            series_folder = f"{modality}_{series_desc}"
            
        dest_dir = self.output_dir / patient_folder / series_folder
        dest_dir.mkdir(parents=True, exist_ok=True)

        sop_class = SOP_CLASS_MAPPING.get(modality, DEFAULT_SOP_CLASS)

        orig_study_uid = study_uid
        orig_series_uid = series_uid
        orig_for_uid = getattr(first_ds, 'FrameOfReferenceUID', None)

        if self.config.new_uids:
            study_uid_mapped = self.study_uid_map.setdefault(orig_study_uid, generate_uid())
            if segment_idx > 0:
                series_uid_mapped = generate_uid()
                for_uid_mapped = generate_uid()
            else:
                series_uid_mapped = self.series_uid_map.setdefault(orig_series_uid, generate_uid())
                if orig_for_uid:
                    for_uid_mapped = self.for_uid_map.setdefault(orig_for_uid, generate_uid())
                else:
                    for_uid_mapped = generate_uid()
        else:
            study_uid_mapped = orig_study_uid
            if segment_idx > 0:
                series_uid_mapped = generate_uid()
                for_uid_mapped = generate_uid()
            else:
                series_uid_mapped = orig_series_uid
                for_uid_mapped = orig_for_uid or generate_uid()

        for file_path, ds_header in items:
            if series_uid_mapped not in self.series_counters:
                self.series_counters[series_uid_mapped] = 1
            else:
                self.series_counters[series_uid_mapped] += 1

            current_instance = getattr(ds_header, 'InstanceNumber', None)
            if current_instance is None:
                current_instance = self.series_counters[series_uid_mapped]
            else:
                try:
                    current_instance = int(current_instance)
                except (ValueError, TypeError):
                    current_instance = self.series_counters[series_uid_mapped]

            task = {
                'file_path': file_path,
                'dest_dir': dest_dir,
                'pat_name': pat_name,
                'pat_id': pat_id,
                'study_uid_mapped': study_uid_mapped,
                'series_uid_mapped': series_uid_mapped,
                'for_uid_mapped': for_uid_mapped,
                'sop_class': sop_class,
                'config': self.config,
                'instance_number': current_instance,
                'segment_idx': segment_idx,
                'modality': modality,
                'series_folder': series_folder,
            }
            tasks_list.append(task)

    def scan_input_directory(self) -> Dict[str, Any]:
        """Сканирует входную директорию и возвращает дерево пациентов/исследований/серий.

        Returns:
            Словарь с иерархической структурой для GUI.
        """
        all_files: List[Path] = []
        if self.input_dir.exists():
            for file_path in self.input_dir.rglob("*"):
                if file_path.is_file():
                    if file_path.suffix.lower() == '.dcm' or '.' not in file_path.name:
                        all_files.append(file_path)

        total_files = len(all_files)
        if total_files > 0:
            self.logger.update_scan_progress(0, total_files)

        tree = {}
        for idx, file_path in enumerate(all_files):
            if self.stop_event.is_set():
                break
            try:
                ds = safe_dcmread(file_path, stop_before_pixels=True)
            except Exception:
                continue

            patient_name = str(getattr(ds, 'PatientName', 'UNKNOWN'))
            patient_id = str(getattr(ds, 'PatientID', 'UNKNOWN'))
            patient_key = (patient_name, patient_id)

            study_date = str(getattr(ds, 'StudyDate', ''))
            study_desc = str(getattr(ds, 'StudyDescription', 'NoDescription'))
            study_uid = str(getattr(ds, 'StudyInstanceUID', 'no_study_uid'))
            study_key = (study_date, study_desc, study_uid)

            series_num = str(getattr(ds, 'SeriesNumber', '0'))
            series_desc = str(getattr(ds, 'SeriesDescription', 'NoDescription'))
            modality = str(getattr(ds, 'Modality', 'OT'))
            series_uid = str(getattr(ds, 'SeriesInstanceUID', 'no_series_uid'))

            orientation_key = None
            if hasattr(ds, 'ImageOrientationPatient'):
                try:
                    orientation_key = tuple(round(float(x), 4) for x in ds.ImageOrientationPatient)
                except Exception:
                    pass

            p_dict = tree.setdefault(patient_key, {})
            st_dict = p_dict.setdefault(study_key, {})
            series_files = st_dict.setdefault(series_uid, [])
            series_files.append((file_path, series_num, series_desc, modality, orientation_key))

            if (idx + 1) % 10 == 0 or (idx + 1) == total_files:
                self.logger.update_scan_progress(idx + 1, total_files)

        final_tree = {}
        for (pat_name, pat_id), studies in tree.items():
            final_studies = {}
            for (study_date, study_desc, study_uid), series_dict in studies.items():
                final_series = {}
                for s_uid, files_info in series_dict.items():
                    orientation_groups = {}
                    for item in files_info:
                        file_path, series_num, series_desc, modality, orientation_key = item
                        orientation_groups.setdefault(orientation_key, []).append(item)

                    _, series_num, series_desc, modality, _ = files_info[0]
                    series_desc_lower = series_desc.lower()
                    exclude_keywords = {
                        'topogram', 'scout', 'patient protocol', 'dose report', 
                        'protocol', 'report', 'screenshot'
                    }
                    is_ignored = any(kw in series_desc_lower for kw in exclude_keywords) or modality in ('SR', 'PR')

                    if is_ignored or not self.config.split_series or len(orientation_groups) <= 1:
                        series_label = f"Series {series_num}: {modality} - {series_desc}"
                        final_series[(series_label, s_uid, 0)] = [x[0] for x in files_info]
                    else:
                        seg_idx = 1
                        for ori_key, group_files in sorted(orientation_groups.items(), key=lambda x: str(x[0])):
                            _, series_num, series_desc, modality, _ = group_files[0]
                            seg_desc = f"{series_desc}_Seg{seg_idx}"
                            series_label = f"Series {series_num}: {modality} - {seg_desc}"
                            final_series[(series_label, s_uid, seg_idx)] = [x[0] for x in group_files]
                            seg_idx += 1
                
                if final_series:
                    final_studies[(study_date, study_desc, study_uid)] = final_series
            
            if final_studies:
                final_tree[(pat_name, pat_id)] = final_studies

        return final_tree
