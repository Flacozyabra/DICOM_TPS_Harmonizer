from datetime import datetime
import json
import os
from pathlib import Path
import sys
import threading
import traceback
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

import numpy as np
import pydicom
from pydicom.uid import generate_uid

from src.core.config import ProcessingConfig
from src.core.converter import (
    MultiframeFrameMeta,
    clean_and_build_dataset,
    clean_and_build_dataset_inplace,
    copy_geometry_and_rescale,
    extract_multiframe_frames,
    save_dicom_file,
)
from src.core.recovery import safe_dcmread
from src.utils.helpers import as_int, make_safe_filename
from src.utils.logger import BaseLogger

# Маппинг модальностей в стандартные SOP Class UID для Monaco и Aria
SOP_CLASS_MAPPING = {
    'MR': '1.2.840.10008.5.1.4.1.1.4',     # MR Image Storage
    'CT': '1.2.840.10008.5.1.4.1.1.2',     # CT Image Storage
    'PT': '1.2.840.10008.5.1.4.1.1.128',   # Positron Emission Tomography Image Storage
    'US': '1.2.840.10008.5.1.4.1.1.6.1',   # Ultrasound Image Storage
}
DEFAULT_SOP_CLASS = '1.2.840.10008.5.1.4.1.1.7'  # Secondary Capture Image Storage


def _build_subseries_labels(
    group_frames: List[MultiframeFrameMeta],
    group_idx: int,
    used_folder_suffixes: Set[str],
    has_multiple_temporal: bool,
) -> Tuple[str, str]:
    """Build human-readable SeriesDescription suffix and filesystem-safe folder suffix."""
    first = group_frames[0]
    desc_parts: List[str] = []
    folder_parts: List[str] = []

    if first.stack_id:
        desc_parts.append(f"stack {first.stack_id}")
        folder_parts.append(f"Stack{make_safe_filename(first.stack_id)}")
    if first.echo_numbers:
        desc_parts.append(f"echo {first.echo_numbers}")
        folder_parts.append(f"Echo{make_safe_filename(first.echo_numbers)}")
    if first.temporal_index is not None and (has_multiple_temporal or first.temporal_index > 1):
        desc_parts.append(f"t{first.temporal_index}")
        folder_parts.append(f"T{first.temporal_index}")
    if first.b_value is not None:
        b_str = str(int(first.b_value)) if float(first.b_value).is_integer() else str(first.b_value)
        desc_parts.append(f"b{b_str}")
        folder_parts.append(f"b{make_safe_filename(b_str)}")

    folder_suffix = "_".join(folder_parts)
    if not folder_suffix or folder_suffix in used_folder_suffixes:
        seg_label = f"Seg{group_idx + 1}"
        folder_suffix = f"{folder_suffix}_{seg_label}" if folder_suffix else seg_label
        desc_parts.append(f"seg {group_idx + 1}")

    used_folder_suffixes.add(folder_suffix)
    desc_suffix = ", ".join(desc_parts) if desc_parts else f"series {group_idx + 1}"
    return desc_suffix, folder_suffix


def _group_multiframe_frames(
    frames_meta: List[MultiframeFrameMeta],
    split_series: bool,
) -> List[List[MultiframeFrameMeta]]:
    """Group and sort multiframe metadata into one or more subseries."""
    if not frames_meta:
        return []
    if not split_series:
        return [list(frames_meta)]

    groups_dict: Dict[Tuple[Any, ...], List[MultiframeFrameMeta]] = {}
    for frame in frames_meta:
        groups_dict.setdefault(frame.group_key(), []).append(frame)

    groups = list(groups_dict.values())

    def _group_sort_key(group: List[MultiframeFrameMeta]) -> Tuple[Any, ...]:
        first = group[0]
        ori_str = str(tuple(round(v, 4) for v in first.orientation)) if first.orientation else ""
        return (
            first.stack_id or "",
            first.temporal_index if first.temporal_index is not None else 0,
            first.echo_numbers or "",
            first.b_value if first.b_value is not None else -1.0,
            first.frame_type or (),
            ori_str,
        )

    groups.sort(key=_group_sort_key)
    for group in groups:
        group.sort(
            key=lambda f: (
                f.in_stack_position if f.in_stack_position is not None else 0,
                f.slice_location if f.slice_location is not None else 0.0,
                f.index,
            )
        )
    return groups


def _check_dataset_pixel_integrity(ds: pydicom.Dataset) -> Optional[Tuple[int, int]]:
    """Return ``(actual_len, expected_len)`` if uncompressed PixelData size mismatches."""
    if 'PixelData' not in ds:
        return None
    pixel_bytes = ds.PixelData
    file_meta = getattr(ds, 'file_meta', None)
    ts_uid = getattr(file_meta, 'TransferSyntaxUID', None) if file_meta is not None else None
    if ts_uid is not None and ts_uid.is_compressed:
        return None
    rows = as_int(ds.get('Rows')) or 0
    cols = as_int(ds.get('Columns')) or 0
    bits = as_int(ds.get('BitsAllocated')) or 16
    samples = as_int(ds.get('SamplesPerPixel')) or 1
    expected_len = rows * cols * samples * (bits // 8)
    actual_len = len(pixel_bytes)
    if expected_len > 0 and actual_len != expected_len:
        return actual_len, expected_len
    return None


def verify_dicom_series_on_disk(file_paths: Sequence[Path]) -> Dict[str, Any]:
    """Verify PixelData integrity and duplicate ImagePositionPatient across written files."""
    pixel_errors: List[Tuple[str, int, int]] = []
    positions: List[Tuple[float, float, float]] = []

    for file_path in file_paths:
        ds = pydicom.dcmread(str(file_path))
        mismatch = _check_dataset_pixel_integrity(ds)
        if mismatch is not None:
            pixel_errors.append((Path(file_path).name, mismatch[0], mismatch[1]))
        ipp = getattr(ds, 'ImagePositionPatient', None)
        if ipp is not None and len(ipp) >= 3:
            try:
                positions.append(tuple(round(float(v), 4) for v in ipp[:3]))
            except (TypeError, ValueError):
                pass

    unique_positions = set(positions)
    has_duplicates = len(positions) > 1 and len(unique_positions) < len(positions)
    return {
        'total_files': len(file_paths),
        'pixel_errors': pixel_errors,
        'position_count': len(positions),
        'unique_positions': len(unique_positions),
        'duplicate_positions': has_duplicates,
    }


def _record_verified_slice(
    results: dict,
    ds: pydicom.Dataset,
    out_path: Path,
    modality: str,
    pat_name: str,
    fallback_series_label: str,
) -> bool:
    """Check uncompressed PixelData length and record ImagePositionPatient for post-verification."""
    mismatch = _check_dataset_pixel_integrity(ds)
    if mismatch is not None:
        results['logs'].append(('log_pixel_length_error', out_path.name, mismatch[0], mismatch[1]))
        return False

    ipp = getattr(ds, 'ImagePositionPatient', None)
    ipp_tuple: Optional[Tuple[float, float, float]] = None
    if ipp is not None and len(ipp) >= 3:
        try:
            ipp_tuple = tuple(round(float(v), 4) for v in ipp[:3])
        except (TypeError, ValueError):
            ipp_tuple = None

    series_label = str(getattr(ds, 'SeriesDescription', '') or fallback_series_label)
    results['series_positions'].append(
        (str(ds.SeriesInstanceUID), modality, pat_name, series_label, ipp_tuple)
    )
    return True


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
        'series_positions': [],
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
        output_filename = task.get('output_filename')
        mf_file_suffix = task.get('mf_file_suffix', '')

        filename = file_path.name

        try:
            ds_full = safe_dcmread(file_path, stop_before_pixels=False)

            # Защита от файлов без пикселей
            has_pixels = any(tag in ds_full for tag in ['PixelData', 'FloatPixelData', 'DoubleFloatPixelData'])
            if not has_pixels:
                results['no_pixel_count'] += 1
                continue

        except Exception as e:
            tb = traceback.format_exc()
            results['status'] = 'error'
            results['error_count'] += 1
            series_errors += 1
            results['logs'].append(('log_pixel_error', filename, str(e)))
            results['logs'].append(('traceback', tb))
            continue

        is_multiframe = (as_int(ds_full.get('NumberOfFrames')) or 1) > 1

        if is_multiframe and config.split_multiframe:
            try:
                pixel_array = ds_full.pixel_array
            except Exception as e:
                tb = traceback.format_exc()
                results['status'] = 'error'
                results['error_count'] += 1
                series_errors += 1
                results['logs'].append(('log_pixel_error', filename, str(e)))
                results['logs'].append(('traceback', tb))
                continue

            if pixel_array.ndim == 2:
                pixel_array = pixel_array[np.newaxis, ...]

            n_frames = int(ds_full.NumberOfFrames)
            results['logs'].append(('log_split_multiframe', filename, n_frames))

            frames_meta, geo_warnings = extract_multiframe_frames(ds_full)
            for warn in geo_warnings:
                if warn[0] == 'reconstructed_ipp':
                    results['logs'].append(('log_reconstructed_ipp', filename, warn[1]))

            groups = _group_multiframe_frames(frames_meta, split_series=config.split_series)
            has_multiple_subseries = len(groups) > 1
            if has_multiple_subseries:
                results['logs'].append(('log_subseries_split', filename, len(groups), n_frames))

            shared_info = ds_full.SharedFunctionalGroupsSequence[0] if hasattr(ds_full, 'SharedFunctionalGroupsSequence') and ds_full.SharedFunctionalGroupsSequence else None
            per_frame_seq = ds_full.PerFrameFunctionalGroupsSequence if hasattr(ds_full, 'PerFrameFunctionalGroupsSequence') else None

            if config.new_uids or segment_idx > 0 or mf_file_suffix:
                base_group_series_uid = generate_uid()
            else:
                base_group_series_uid = series_uid_mapped

            base_series_num = as_int(ds_full.get('SeriesNumber'))
            if base_series_num is None:
                base_series_num = 1
            orig_series_desc = str(getattr(ds_full, 'SeriesDescription', '') or '').strip()
            safe_desc = make_safe_filename(orig_series_desc) if orig_series_desc else 'NoDescription'
            if segment_idx > 0:
                safe_desc = f"{safe_desc}_Seg{segment_idx}"

            temporal_vals = {f.temporal_index for f in frames_meta if f.temporal_index is not None}
            has_multiple_temporal = len(temporal_vals) > 1
            used_folder_suffixes: Set[str] = set()

            multiframe_errors = 0
            for group_idx, group_frames in enumerate(groups):
                if has_multiple_subseries:
                    sub_series_uid = base_group_series_uid if group_idx == 0 else generate_uid()
                    sub_series_num = base_series_num + group_idx
                    desc_suffix, folder_suffix = _build_subseries_labels(
                        group_frames, group_idx, used_folder_suffixes, has_multiple_temporal
                    )
                    sub_series_desc = f"{orig_series_desc} [{desc_suffix}]" if orig_series_desc else desc_suffix
                    sub_folder_name = f"{modality}_{sub_series_num}_{safe_desc}_{folder_suffix}{mf_file_suffix}"
                    target_dir = dest_dir.parent / sub_folder_name
                else:
                    sub_series_uid = base_group_series_uid
                    sub_series_num = None
                    sub_series_desc = None
                    target_dir = dest_dir

                target_dir.mkdir(parents=True, exist_ok=True)
                slice_suffix = '' if has_multiple_subseries else mf_file_suffix

                for inst_idx, frame_meta in enumerate(group_frames, start=1):
                    frame_idx = frame_meta.index
                    frame_info = (
                        per_frame_seq[frame_idx]
                        if per_frame_seq is not None and frame_idx < len(per_frame_seq)
                        else None
                    )

                    try:
                        cleaned_ds = clean_and_build_dataset(
                            src_ds=ds_full,
                            pixel_data=pixel_array[frame_idx],
                            instance_number=inst_idx,
                            study_uid=study_uid_mapped,
                            series_uid=sub_series_uid,
                            sop_class=sop_class,
                            for_uid=for_uid_mapped,
                            config=config,
                            frame_type=frame_meta.frame_type,
                        )

                        cleaned_ds.PatientName = pat_name
                        cleaned_ds.PatientID = pat_id
                        if sub_series_num is not None:
                            cleaned_ds.SeriesNumber = sub_series_num
                        if sub_series_desc is not None:
                            cleaned_ds.SeriesDescription = sub_series_desc

                        copy_geometry_and_rescale(
                            src_ds=ds_full,
                            new_ds=cleaned_ds,
                            frame_info=frame_info,
                            shared_info=shared_info,
                            is_multiframe=True,
                            frame_idx=frame_idx,
                            frame_meta=frame_meta,
                        )

                        out_path = target_dir / f"slice_{inst_idx:04d}{slice_suffix}.dcm"
                        save_dicom_file(out_path, cleaned_ds, config.explicit_vr)
                        if _record_verified_slice(
                            results, cleaned_ds, out_path, modality, pat_name, target_dir.name
                        ):
                            results['success_count'] += 1
                            series_success += 1
                        else:
                            multiframe_errors += 1
                            results['error_count'] += 1
                            series_errors += 1
                    except Exception as e:
                        tb = traceback.format_exc()
                        results['logs'].append(('log_frame_save_error', frame_idx + 1, filename, str(e)))
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
                dest_dir.mkdir(parents=True, exist_ok=True)
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

                fname = output_filename or f"slice_{instance_number:04d}.dcm"
                out_path = dest_dir / fname
                save_dicom_file(out_path, cleaned_ds, config.explicit_vr)
                if _record_verified_slice(
                    results, cleaned_ds, out_path, modality, pat_name, series_folder
                ):
                    results['success_count'] += 1
                    series_success += 1
                else:
                    results['error_count'] += 1
                    series_errors += 1
                    results['status'] = 'error'
            except Exception as e:
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
        self.assigned_dest_dirs: Dict[Path, str] = {}
        self.dest_dir_used_names: Dict[Path, Set[str]] = {}
        self.dest_dir_mf_counts: Dict[Path, int] = {}

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
            self.assigned_dest_dirs.clear()
            self.dest_dir_used_names.clear()
            self.dest_dir_mf_counts.clear()
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
            series_pos_map: Dict[str, List[Tuple[str, str, str, Optional[Tuple[float, float, float]]]]] = {}
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
                            if sys.version_info >= (3, 9):
                                executor.shutdown(wait=False, cancel_futures=True)
                            else:
                                for pending_fut in futures:
                                    pending_fut.cancel()
                                executor.shutdown(wait=False)
                            self.logger.log(self.loc("log_stop_user"), "warning")
                            break

                        try:
                            res = fut.result()
                            self.success_count += res['success_count']
                            self.error_count += res['error_count']
                            self.no_pixel_count += res['no_pixel_count']

                            for s_uid, mod, p_name, s_label, ipp_tuple in res.get('series_positions', []):
                                series_pos_map.setdefault(s_uid, []).append((mod, p_name, s_label, ipp_tuple))

                            for log_item in res['logs']:
                                key = log_item[0]
                                args = log_item[1:]
                                if key == 'traceback':
                                    self.logger.log(args[0], "error")
                                else:
                                    # Определяем тег лога
                                    if key in ('log_pixel_error', 'log_frame_save_error', 'log_save_error', 'log_critical_error', 'log_pixel_length_error'):
                                        tag = "error"
                                    elif key in ('log_non_dicom', 'log_read_error', 'log_split_warning', 'log_files_not_found', 'log_stop_user', 'log_series_warning', 'log_reconstructed_ipp', 'log_duplicate_ipp'):
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

            # Post-verification: check for duplicate ImagePositionPatient within each output series
            if not self.stop_event.is_set():
                for s_uid, entries in series_pos_map.items():
                    total_slices = len(entries)
                    positions = [e[3] for e in entries if e[3] is not None]
                    if total_slices > 1 and len(positions) > 1:
                        unique_positions = set(positions)
                        if len(unique_positions) < len(positions):
                            mod, p_name, s_label, _ = entries[0]
                            self.logger.log(
                                self.loc("log_duplicate_ipp", mod, p_name, s_label, len(unique_positions), total_slices),
                                "warning"
                            )

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

        # Assign a unique output directory per mapped series to prevent folder collisions
        claim_key = f"{series_uid_mapped}_{segment_idx}"
        dest_dir = self.output_dir / patient_folder / series_folder
        suffix_idx = 2
        while dest_dir in self.assigned_dest_dirs and self.assigned_dest_dirs[dest_dir] != claim_key:
            dest_dir = self.output_dir / patient_folder / f"{series_folder}_{suffix_idx}"
            suffix_idx += 1
        self.assigned_dest_dirs[dest_dir] = claim_key
        series_folder = dest_dir.name

        used_names = self.dest_dir_used_names.setdefault(dest_dir, set())

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

            n_frames = as_int(ds_header.get('NumberOfFrames')) or 1
            is_mf_task = self.config.split_multiframe and n_frames > 1

            if is_mf_task:
                mf_idx = self.dest_dir_mf_counts.get(dest_dir, 0)
                self.dest_dir_mf_counts[dest_dir] = mf_idx + 1
                if mf_idx == 0 and not any(f"slice_{i + 1:04d}.dcm" in used_names for i in range(n_frames)):
                    mf_file_suffix = ""
                else:
                    cand_num = max(2, mf_idx + 1)
                    while any(f"slice_{i + 1:04d}_mf{cand_num}.dcm" in used_names for i in range(n_frames)):
                        cand_num += 1
                    mf_file_suffix = f"_mf{cand_num}"
                for i in range(n_frames):
                    used_names.add(f"slice_{i + 1:04d}{mf_file_suffix}.dcm")
                output_filename = None
            else:
                base_name = f"slice_{current_instance:04d}"
                candidate_name = f"{base_name}.dcm"
                dup_idx = 2
                while candidate_name in used_names:
                    candidate_name = f"{base_name}_{dup_idx}.dcm"
                    dup_idx += 1
                used_names.add(candidate_name)
                output_filename = candidate_name
                mf_file_suffix = ""

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
                'output_filename': output_filename,
                'mf_file_suffix': mf_file_suffix,
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
        problems = {
            'implicit_vr': 0,
            'multiframe': 0,
            'private_tags': 0,
            'bits_allocated': 0,
            'missing_tags': 0,
            'corrupted_siemens': 0
        }
        for idx, file_path in enumerate(all_files):
            if self.stop_event.is_set():
                break
            try:
                ds = safe_dcmread(file_path, stop_before_pixels=True)
            except Exception:
                continue

            # Сбор статистики проблем
            try:
                if getattr(ds, 'file_meta', None) and getattr(ds.file_meta, 'TransferSyntaxUID', None) and ds.file_meta.TransferSyntaxUID.is_implicit_VR:
                    problems['implicit_vr'] += 1
            except Exception:
                pass

            try:
                if hasattr(ds, 'NumberOfFrames') and int(ds.NumberOfFrames) > 1:
                    problems['multiframe'] += 1
            except Exception:
                pass

            try:
                if any(tag.is_private for tag in ds.keys()):
                    problems['private_tags'] += 1
            except Exception:
                pass

            try:
                if hasattr(ds, 'BitsAllocated') and ds.BitsAllocated != 16:
                    problems['bits_allocated'] += 1
            except Exception:
                pass

            try:
                missing = False
                for tag in ['AccessionNumber', 'StudyID', 'ReferringPhysicianName']:
                    if not hasattr(ds, tag) or not getattr(ds, tag):
                        missing = True
                        break
                if missing:
                    problems['missing_tags'] += 1
            except Exception:
                pass

            if getattr(ds, 'is_restored', False):
                problems['corrupted_siemens'] += 1

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

        # Вывод статистики обнаруженных проблем
        has_any_problem = any(val > 0 for val in problems.values())
        self.logger.log(self.loc("scan_stats_title"))
        if has_any_problem:
            if problems['implicit_vr'] > 0:
                self.logger.log(self.loc("scan_stats_implicit_vr", problems['implicit_vr']), "warning")
            if problems['multiframe'] > 0:
                self.logger.log(self.loc("scan_stats_multiframe", problems['multiframe']), "warning")
            if problems['private_tags'] > 0:
                self.logger.log(self.loc("scan_stats_private_tags", problems['private_tags']), "warning")
            if problems['bits_allocated'] > 0:
                self.logger.log(self.loc("scan_stats_bits_allocated", problems['bits_allocated']), "warning")
            if problems['missing_tags'] > 0:
                self.logger.log(self.loc("scan_stats_missing_tags", problems['missing_tags']), "warning")
            if problems['corrupted_siemens'] > 0:
                self.logger.log(self.loc("scan_stats_corrupted_siemens", problems['corrupted_siemens']), "warning")
        else:
            self.logger.log(self.loc("scan_stats_none"), "success")
        self.logger.log(self.loc("scan_stats_end"))

        return final_tree
