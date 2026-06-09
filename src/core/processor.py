from datetime import datetime
import json
from pathlib import Path
import sys
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
        """Запускает процесс обработки DICOM файлов."""
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

            # Группируем файлы по сериям для предварительного анализа
            series_groups = {}
            for file_path in all_files:
                if self.stop_event.is_set():
                    self.logger.log(self.loc("log_stop_user"), "warning")
                    break

                filename = file_path.name
                try:
                    ds = safe_dcmread(file_path, stop_before_pixels=True)
                except ValueError as e:
                    self.logger.log(self.loc("log_non_dicom", filename, e), "warning")
                    self.non_dicom_count += 1
                    self.processed_count += 1
                    self.logger.update_progress(self.processed_count, total_files)
                    continue
                except Exception as e:
                    self.logger.log(self.loc("log_read_error", filename, e), "error")
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

            # Обрабатываем сгруппированные серии
            for (pat_name, pat_id, study_uid, series_uid), items in series_groups.items():
                if self.stop_event.is_set():
                    self.logger.log(self.loc("log_stop_user"), "warning")
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
                        self._process_series_segment(
                            pat_name, pat_id, study_uid, series_uid,
                            group_items, segment_idx=seg_idx, total_files=total_files
                        )
                        seg_idx += 1
                else:
                    self._process_series_segment(
                        pat_name, pat_id, study_uid, series_uid,
                        items, segment_idx=0, total_files=total_files
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

    def _process_series_segment(
        self,
        pat_name: str,
        pat_id: str,
        study_uid: str,
        series_uid: str,
        items: List[tuple],
        segment_idx: int,
        total_files: int
    ) -> None:
        first_file_path, first_ds = items[0]
        modality = getattr(first_ds, 'Modality', 'OT')
        series_desc = make_safe_filename(getattr(first_ds, 'SeriesDescription', 'NoDescription'))

        if segment_idx > 0:
            series_desc = f"{series_desc}_Seg{segment_idx}"

        patient_name = make_safe_filename(pat_name)
        patient_id = make_safe_filename(pat_id)
        patient_folder = f"{patient_name}_{patient_id}"
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
            if self.stop_event.is_set():
                break

            filename = file_path.name
            
            # Исключение служебных серий
            if self.config.exclude_reports:
                series_desc_lower = series_desc.lower()
                exclude_keywords = {
                    'topogram', 'scout', 'patient protocol', 'dose report', 
                    'protocol', 'report', 'screenshot'
                }
                is_excluded = any(kw in series_desc_lower for kw in exclude_keywords) or modality in ('SR', 'PR')
                if is_excluded:
                    self.logger.log(self.loc("log_skip_service", series_desc, modality))
                    self.excluded_count += 1
                    self.processed_count += 1
                    self.logger.update_progress(self.processed_count, total_files)
                    continue

            try:
                ds_full = safe_dcmread(file_path, stop_before_pixels=False)
                
                # Защита от файлов без пикселей
                has_pixels = any(tag in ds_full for tag in ['PixelData', 'FloatPixelData', 'DoubleFloatPixelData'])
                if not has_pixels:
                    self.no_pixel_count += 1
                    self.processed_count += 1
                    self.logger.update_progress(self.processed_count, total_files)
                    continue

                pixel_array = ds_full.pixel_array
            except Exception as e:
                self.logger.log(self.loc("log_pixel_error", filename, e), "error")
                self.logger.log(traceback.format_exc(), "error")
                self.error_count += 1
                self.processed_count += 1
                self.logger.update_progress(self.processed_count, total_files)
                continue

            is_multiframe = hasattr(ds_full, 'NumberOfFrames') and int(ds_full.NumberOfFrames) > 1

            if is_multiframe and self.config.split_multiframe:
                n_frames = int(ds_full.NumberOfFrames)
                self.logger.log(self.loc("log_split_multiframe", filename, n_frames))

                shared_info = ds_full.SharedFunctionalGroupsSequence[0] if hasattr(ds_full, 'SharedFunctionalGroupsSequence') else None
                
                if self.config.new_uids or segment_idx > 0:
                    current_series_uid = generate_uid()
                else:
                    current_series_uid = series_uid_mapped

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
                            study_uid=study_uid_mapped,
                            series_uid=current_series_uid,
                            sop_class=sop_class,
                            for_uid=for_uid_mapped,
                            config=self.config
                        )

                        # Принудительно выставляем валидные PatientName и PatientID
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
                        save_dicom_file(out_path, cleaned_ds, self.config.explicit_vr)
                        self.success_count += 1
                    except Exception as e:
                        self.logger.log(self.loc("log_frame_save_error", i + 1, filename, e), "error")
                        self.logger.log(traceback.format_exc(), "error")
                        multiframe_errors += 1
                        self.error_count += 1

                if self.stop_event.is_set():
                    break

                if multiframe_errors == 0:
                    self.logger.log(
                        self.loc("log_split_success", modality, pat_name, pat_id, series_folder, filename, n_frames),
                        "success"
                    )
                else:
                    self.logger.log(
                        self.loc("log_split_warning", modality, pat_name, pat_id, series_folder, filename, multiframe_errors),
                        "warning"
                    )

            else:
                if series_uid_mapped not in self.series_counters:
                    self.series_counters[series_uid_mapped] = 1
                else:
                    self.series_counters[series_uid_mapped] += 1

                current_instance = getattr(ds_full, 'InstanceNumber', None)
                if current_instance is None:
                    current_instance = self.series_counters[series_uid_mapped]
                else:
                    try:
                        current_instance = int(current_instance)
                    except (ValueError, TypeError):
                        current_instance = self.series_counters[series_uid_mapped]

                try:
                    cleaned_ds = clean_and_build_dataset(
                        src_ds=ds_full,
                        pixel_data=pixel_array,
                        instance_number=current_instance,
                        study_uid=study_uid_mapped,
                        series_uid=series_uid_mapped,
                        sop_class=sop_class,
                        for_uid=for_uid_mapped,
                        config=self.config
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

                    out_path = dest_dir / f"slice_{current_instance:04d}.dcm"
                    save_dicom_file(out_path, cleaned_ds, self.config.explicit_vr)
                    self.logger.log(
                        self.loc("log_save_slice", modality, pat_name, pat_id, series_folder, filename, current_instance)
                    )
                    self.success_count += 1
                except Exception as e:
                    self.logger.log(self.loc("log_save_error", filename, e), "error")
                    self.logger.log(traceback.format_exc(), "error")
                    self.error_count += 1

            self.processed_count += 1
            self.logger.update_progress(self.processed_count, total_files)

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

        tree = {}
        for file_path in all_files:
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

                    if len(orientation_groups) <= 1:
                        _, series_num, series_desc, modality, _ = files_info[0]
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
