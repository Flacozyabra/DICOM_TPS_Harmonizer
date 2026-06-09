from pathlib import Path
from typing import List, Optional, Union
import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian
from src.core.config import ProcessingConfig
from src.utils.helpers import get_seq_attr

def clean_and_build_dataset(
    src_ds: Dataset,
    pixel_data: np.ndarray,
    instance_number: int,
    study_uid: str,
    series_uid: str,
    sop_class: str,
    for_uid: str,
    config: ProcessingConfig
) -> Dataset:
    """Создает оптимизированный Dataset на основе исходного.

    Args:
        src_ds: Исходный Dataset.
        pixel_data: Numpy массив пикселей для текущего кадра.
        instance_number: Номер снимка в серии (InstanceNumber).
        study_uid: Уникальный идентификатор исследования.
        series_uid: Уникальный идентификатор серии.
        sop_class: Класс SOP (модальность).
        for_uid: Идентификатор системы координат (Frame of Reference UID).
        config: Настройки процесса оптимизации.

    Returns:
        Новый Dataset с заполненными тегами.
    """
    new_ds = Dataset()

    # Теги, которые запрещено копировать напрямую в сингл-фрейм
    forbidden_tags = {
        'PixelData', 'NumberOfFrames', 'PerFrameFunctionalGroupsSequence', 
        'SharedFunctionalGroupsSequence', 'SOPClassUID', 'SOPInstanceUID', 
        'SeriesInstanceUID', 'StudyInstanceUID', 'InstanceNumber', 'Rows', 'Columns',
        'FunctionalGroupPointer', 'SelectorSequencePointer'
    }

    if config.clean_tags:
        # Копируем только безопасные стандартные теги
        for element in src_ds:
            if element.keyword and element.keyword not in forbidden_tags and not element.is_private:
                try:
                    setattr(new_ds, element.keyword, element.value)
                except AttributeError:
                    pass
    else:
        # Копируем всё, кроме структурных тегов мультифрейма и пикселей
        for element in src_ds:
            if element.keyword and element.keyword not in forbidden_tags:
                try:
                    setattr(new_ds, element.keyword, element.value)
                except AttributeError:
                    pass

    # Идентификаторы и метаданные
    new_ds.SpecificCharacterSet = 'ISO_IR 100'
    new_ds.SOPClassUID = sop_class
    new_ds.SOPInstanceUID = generate_uid()
    new_ds.StudyInstanceUID = study_uid
    new_ds.SeriesInstanceUID = series_uid
    new_ds.InstanceNumber = int(instance_number)
    new_ds.FrameOfReferenceUID = for_uid
    new_ds.ImageType = getattr(src_ds, 'ImageType', ['ORIGINAL', 'PRIMARY'])

    # Геометрия матрицы
    new_ds.Rows = pixel_data.shape[0]
    new_ds.Columns = pixel_data.shape[1]
    new_ds.SamplesPerPixel = getattr(src_ds, 'SamplesPerPixel', 1)
    new_ds.PhotometricInterpretation = getattr(src_ds, 'PhotometricInterpretation', 'MONOCHROME2')
    new_ds.BitsAllocated = getattr(src_ds, 'BitsAllocated', 16)
    new_ds.BitsStored = getattr(src_ds, 'BitsStored', 16)
    new_ds.HighBit = getattr(src_ds, 'HighBit', 15)
    new_ds.PixelRepresentation = getattr(src_ds, 'PixelRepresentation', 0)

    # Принудительное приведение к 16-битному формату для Monaco TPS
    if new_ds.BitsAllocated != 16:
        new_ds.BitsAllocated = 16
        new_ds.BitsStored = 16
        new_ds.HighBit = 15

    # Обязательные теги по умолчанию (если включено)
    if config.default_tags:
        if not hasattr(new_ds, 'AccessionNumber') or not new_ds.AccessionNumber:
            new_ds.AccessionNumber = "000000"
        if not hasattr(new_ds, 'StudyID') or not new_ds.StudyID:
            new_ds.StudyID = "1"
        if not hasattr(new_ds, 'ReferringPhysicianName') or not new_ds.ReferringPhysicianName:
            new_ds.ReferringPhysicianName = "UNKNOWN"
        if not hasattr(new_ds, 'Manufacturer') or not new_ds.Manufacturer:
            new_ds.Manufacturer = getattr(src_ds, 'Manufacturer', 'UNKNOWN')
        if not hasattr(new_ds, 'PatientID') or not new_ds.PatientID:
            new_ds.PatientID = "UNKNOWN"
        if not hasattr(new_ds, 'PatientName') or not new_ds.PatientName:
            new_ds.PatientName = "UNKNOWN"
        if not hasattr(new_ds, 'PatientBirthDate'):
            new_ds.PatientBirthDate = getattr(src_ds, 'PatientBirthDate', '')
        if not hasattr(new_ds, 'PatientSex'):
            new_ds.PatientSex = getattr(src_ds, 'PatientSex', 'O')

        # Специальные Type 1 теги для модальности MR (для совместимости с TPS)
        if getattr(src_ds, 'Modality', None) == 'MR':
            if not hasattr(new_ds, 'MRAcquisitionType') or not new_ds.MRAcquisitionType:
                new_ds.MRAcquisitionType = getattr(src_ds, 'MRAcquisitionType', '2D')
            if not hasattr(new_ds, 'ScanningSequence') or not new_ds.ScanningSequence:
                new_ds.ScanningSequence = getattr(src_ds, 'ScanningSequence', 'SE')
            if not hasattr(new_ds, 'SequenceVariant') or not new_ds.SequenceVariant:
                new_ds.SequenceVariant = getattr(src_ds, 'SequenceVariant', 'NONE')
            if not hasattr(new_ds, 'ScanOptions') or not new_ds.ScanOptions:
                new_ds.ScanOptions = getattr(src_ds, 'ScanOptions', 'NONE')
            if not hasattr(new_ds, 'EchoTime') or new_ds.EchoTime is None or new_ds.EchoTime == "":
                new_ds.EchoTime = getattr(src_ds, 'EchoTime', 0.0)
            if not hasattr(new_ds, 'RepetitionTime') or new_ds.RepetitionTime is None or new_ds.RepetitionTime == "":
                new_ds.RepetitionTime = getattr(src_ds, 'RepetitionTime', 0.0)
            if not hasattr(new_ds, 'MagneticFieldStrength') or new_ds.MagneticFieldStrength is None or new_ds.MagneticFieldStrength == "":
                new_ds.MagneticFieldStrength = getattr(src_ds, 'MagneticFieldStrength', 1.5)
            if not hasattr(new_ds, 'AcquisitionNumber') or new_ds.AcquisitionNumber is None or new_ds.AcquisitionNumber == "":
                new_ds.AcquisitionNumber = getattr(src_ds, 'AcquisitionNumber', 1)

        # Специальные теги для модальности CT (для совместимости с Monaco TPS)
        if getattr(src_ds, 'Modality', None) == 'CT':
            new_ds.PatientSupportAngle = 0.0
            new_ds.TableTopPitchAngle = 0.0
            new_ds.TableTopRollAngle = 0.0

    # Запись пикселей
    if new_ds.PixelRepresentation == 1:
        new_ds.PixelData = pixel_data.astype(np.int16).tobytes()
    else:
        new_ds.PixelData = pixel_data.astype(np.uint16).tobytes()

    return new_ds

def copy_geometry_and_rescale(
    src_ds: Dataset,
    new_ds: Dataset,
    frame_info: Optional[Dataset],
    shared_info: Optional[Dataset],
    is_multiframe: bool,
    frame_idx: int
) -> None:
    """Копирует или вычисляет геометрические параметры и калибровочные коэффициенты.

    Args:
        src_ds: Исходный Dataset.
        new_ds: Создаваемый целевой Dataset.
        frame_info: Метаданные конкретного кадра (для мультифреймов).
        shared_info: Общие метаданные всех кадров (для мультифреймов).
        is_multiframe: Является ли исходный файл многокадровым.
        frame_idx: Индекс кадра.
    """
    if is_multiframe:
        img_pos = get_seq_attr(frame_info, shared_info, 'PlanePositionSequence', 'ImagePositionPatient') or \
                  get_seq_attr(frame_info, shared_info, 'PlanePositionPatientSequence', 'ImagePositionPatient')
        img_ori = get_seq_attr(frame_info, shared_info, 'PlaneOrientationSequence', 'ImageOrientationPatient') or \
                  get_seq_attr(frame_info, shared_info, 'PlaneOrientationPatientSequence', 'ImageOrientationPatient')
        
        if img_pos: 
            new_ds.ImagePositionPatient = img_pos
        if img_ori: 
            new_ds.ImageOrientationPatient = img_ori

        # Расчет SliceLocation
        if img_pos and img_ori:
            try:
                pos = [float(x) for x in img_pos]
                ori = [float(x) for x in img_ori]
                row, col = ori[0:3], ori[3:6]
                normal = [
                    row[1]*col[2] - row[2]*col[1],
                    row[2]*col[0] - row[0]*col[2],
                    row[0]*col[1] - row[1]*col[0],
                ]
                new_ds.SliceLocation = round(sum(p*n for p, n in zip(pos, normal)), 4)
            except (ValueError, TypeError, ZeroDivisionError):
                # В случае некорректных значений геометрии, используем индекс кадра
                new_ds.SliceLocation = float(frame_idx)
        else:
            new_ds.SliceLocation = float(frame_idx)

        # Шаг пикселей и толщина среза
        for attr in ['PixelSpacing', 'SliceThickness', 'SpacingBetweenSlices']:
            val = get_seq_attr(frame_info, shared_info, 'PixelMeasuresSequence', attr)
            if val: 
                setattr(new_ds, attr, val)

        # Rescale параметры
        new_ds.RescaleIntercept = get_seq_attr(frame_info, shared_info, 'PixelValueTransformationSequence', 'RescaleIntercept') or 0
        new_ds.RescaleSlope = get_seq_attr(frame_info, shared_info, 'PixelValueTransformationSequence', 'RescaleSlope') or 1
        rescale_type = get_seq_attr(frame_info, shared_info, 'PixelValueTransformationSequence', 'RescaleType')
        if rescale_type: 
            new_ds.RescaleType = rescale_type

        # Window параметры
        wc = get_seq_attr(frame_info, shared_info, 'FrameVOILUTSequence', 'WindowCenter') or \
             get_seq_attr(frame_info, shared_info, 'VOILUTSequence', 'WindowCenter')
        ww = get_seq_attr(frame_info, shared_info, 'FrameVOILUTSequence', 'WindowWidth') or \
             get_seq_attr(frame_info, shared_info, 'VOILUTSequence', 'WindowWidth')
        if wc is not None: 
            new_ds.WindowCenter = wc[0] if isinstance(wc, (list, tuple)) else wc
        if ww is not None: 
            new_ds.WindowWidth = ww[0] if isinstance(ww, (list, tuple)) else ww

    else:
        # Для одиночного кадра копируем напрямую
        for attr in ['ImagePositionPatient', 'ImageOrientationPatient', 'SliceLocation', 
                     'PixelSpacing', 'SliceThickness', 'SpacingBetweenSlices',
                     'RescaleIntercept', 'RescaleSlope', 'RescaleType',
                     'WindowCenter', 'WindowWidth']:
            if hasattr(src_ds, attr):
                setattr(new_ds, attr, getattr(src_ds, attr))
        
        # Расчет SliceLocation, если его не было
        if hasattr(new_ds, 'ImagePositionPatient') and hasattr(new_ds, 'ImageOrientationPatient') and not hasattr(new_ds, 'SliceLocation'):
            try:
                pos = [float(x) for x in new_ds.ImagePositionPatient]
                ori = [float(x) for x in new_ds.ImageOrientationPatient]
                row, col = ori[0:3], ori[3:6]
                normal = [
                    row[1]*col[2] - row[2]*col[1],
                    row[2]*col[0] - row[0]*col[2],
                    row[0]*col[1] - row[1]*col[0],
                ]
                new_ds.SliceLocation = round(sum(p*n for p, n in zip(pos, normal)), 4)
            except (ValueError, TypeError, ZeroDivisionError):
                pass

def save_dicom_file(out_path: Path, dataset: Dataset, explicit_vr: bool) -> None:
    """Сохраняет Dataset в файл DICOM на диске.

    Args:
        out_path: Целевой путь сохранения файла.
        dataset: Сохраняемый Dataset.
        explicit_vr: Флаг сохранения в Explicit VR Little Endian.
    """
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = dataset.SOPClassUID
    file_meta.MediaStorageSOPInstanceUID = dataset.SOPInstanceUID
    file_meta.ImplementationClassUID = pydicom.uid.PYDICOM_IMPLEMENTATION_UID
    
    if explicit_vr:
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        final_ds = FileDataset(str(out_path), dataset, file_meta=file_meta, preamble=b"\0" * 128)
        final_ds.is_implicit_VR = False
        final_ds.is_little_endian = True
    else:
        # Используем синтаксис по умолчанию (обычно Implicit VR Little Endian)
        file_meta.TransferSyntaxUID = pydicom.uid.ImplicitVRLittleEndian
        final_ds = FileDataset(str(out_path), dataset, file_meta=file_meta, preamble=b"\0" * 128)
        final_ds.is_implicit_VR = True
        final_ds.is_little_endian = True

    final_ds.save_as(str(out_path), write_like_original=False)
