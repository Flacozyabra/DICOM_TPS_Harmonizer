from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian
from pydicom.tag import Tag
from src.core.config import ProcessingConfig
from src.utils.helpers import (
    as_floats,
    as_int,
    compute_slice_location,
    compute_slice_normal,
    first_seq_item,
    get_seq_attr,
    resolve_seq_tag,
)

FORBIDDEN_TAGS_STR = {
    'PixelData', 'NumberOfFrames', 'PerFrameFunctionalGroupsSequence',
    'SharedFunctionalGroupsSequence', 'SOPClassUID', 'SOPInstanceUID',
    'SeriesInstanceUID', 'StudyInstanceUID', 'InstanceNumber', 'Rows', 'Columns',
    'FunctionalGroupPointer', 'SelectorSequencePointer'
}
FORBIDDEN_TAGS_IDS = {Tag(t) for t in FORBIDDEN_TAGS_STR}

FORBIDDEN_TAGS_INPLACE_STR = {
    'NumberOfFrames', 'PerFrameFunctionalGroupsSequence',
    'SharedFunctionalGroupsSequence', 'SOPClassUID', 'SOPInstanceUID',
    'SeriesInstanceUID', 'StudyInstanceUID', 'InstanceNumber',
    'FunctionalGroupPointer', 'SelectorSequencePointer'
}
FORBIDDEN_TAGS_INPLACE_IDS = {Tag(t) for t in FORBIDDEN_TAGS_INPLACE_STR}

# Container and Enhanced-IOD-only tags that have no place in single-frame slices
ENHANCED_CONTAINER_TAGS_TUPLES = (
    (0x0020, 0x9221),  # DimensionOrganizationSequence
    (0x0020, 0x9222),  # DimensionIndexSequence
    (0x0020, 0x9072),  # FrameLaterality
    (0x0028, 0x9001),  # DataPointRows
    (0x0028, 0x9002),  # DataPointColumns
    (0x0028, 0x9003),  # SignalDomainColumns
    (0x0028, 0x9108),  # DataRepresentation
    (0x0008, 0x1140),  # ReferencedImageSequence
    (0x0008, 0x1111),  # ReferencedPerformedProcedureStepSequence
    (0x0008, 0x9205),  # PixelPresentation
    (0x0008, 0x9206),  # VolumetricProperties
    (0x0008, 0x9207),  # VolumeBasedCalculationTechnique
    (0x0008, 0x9208),  # ComplexImageComponent
    (0x0008, 0x9209),  # AcquisitionContrast
)
ENHANCED_CONTAINER_TAGS_IDS = {Tag(t) for t in ENHANCED_CONTAINER_TAGS_TUPLES}

_SEQ_SHARED_GROUPS = (0x5200, 0x9229)
_SEQ_PER_FRAME_GROUPS = (0x5200, 0x9230)
_SEQ_DIMENSION_INDEX = (0x0020, 0x9222)
_SEQ_PLANE_POSITION = (0x0020, 0x9113)
_SEQ_PLANE_ORIENTATION = (0x0020, 0x9116)
_SEQ_PIXEL_MEASURES = (0x0028, 0x9110)
_SEQ_FRAME_VOI_LUT = (0x0028, 0x9132)
_SEQ_PIXEL_VALUE_TRANSFORM = (0x0028, 0x9145)
_SEQ_FRAME_CONTENT = (0x0020, 0x9111)
_SEQ_MR_FRAME_TYPE = (0x0018, 0x9226)
_SEQ_CT_FRAME_TYPE = (0x0018, 0x9329)
_SEQ_MR_ECHO = (0x0018, 0x9114)
_SEQ_MR_DIFFUSION = (0x0018, 0x9117)

_TAG_POSITION = (0x0020, 0x0032)
_TAG_ORIENTATION = (0x0020, 0x0037)
_TAG_PIXEL_SPACING = (0x0028, 0x0030)
_TAG_SLICE_THICKNESS = (0x0018, 0x0050)
_TAG_SPACING_BETWEEN = (0x0018, 0x0088)
_TAG_WINDOW_CENTER = (0x0028, 0x1050)
_TAG_WINDOW_WIDTH = (0x0028, 0x1051)
_TAG_RESCALE_INTERCEPT = (0x0028, 0x1052)
_TAG_RESCALE_SLOPE = (0x0028, 0x1053)
_TAG_RESCALE_TYPE = (0x0028, 0x1054)
_TAG_IMAGE_TYPE = (0x0008, 0x0008)
_TAG_FRAME_TYPE = (0x0008, 0x9007)
_TAG_STACK_ID = (0x0020, 0x9056)
_TAG_IN_STACK_POSITION = (0x0020, 0x9057)
_TAG_TEMPORAL_INDEX = (0x0020, 0x9128)
_TAG_ECHO_NUMBERS = (0x0018, 0x0086)
_TAG_DIMENSION_INDEX_VALUES = (0x0020, 0x9157)
_TAG_DIMENSION_INDEX_POINTER = (0x0020, 0x9165)
_TAG_DIFFUSION_B_VALUE = (0x0018, 0x9087)

# Allowlist of DimensionIndexPointer tags that legitimately distinguish separate 3D series.
# Spatial, instance, timestamp, and gradient-direction indices must NOT split a 3D volume.
_SERIES_SPLIT_DIMENSIONS = {
    (0x0018, 0x9082),  # EffectiveEchoTime
    (0x0018, 0x0082),  # InversionTime
    (0x0018, 0x1314),  # FlipAngle
    (0x0018, 0x0080),  # RepetitionTime
}


@dataclass
class MultiframeFrameMeta:
    """Resolved per-frame metadata and geometry extracted from an Enhanced DICOM dataset."""
    index: int
    position: Optional[Tuple[float, ...]] = None
    orientation: Optional[Tuple[float, ...]] = None
    pixel_spacing: Optional[Tuple[float, ...]] = None
    slice_thickness: Any = None
    spacing_between_slices: Any = None
    window_center: Any = None
    window_width: Any = None
    rescale_intercept: Any = None
    rescale_slope: Any = None
    rescale_type: Any = None
    frame_type: Optional[Tuple[str, ...]] = None
    stack_id: Optional[str] = None
    in_stack_position: Optional[int] = None
    temporal_index: Optional[int] = None
    echo_numbers: Optional[str] = None
    b_value: Optional[float] = None
    dimension_index_values: Optional[Tuple[int, ...]] = None
    extra_dimensions: Tuple[Tuple[Tuple[int, int], int], ...] = ()
    slice_location: Optional[float] = None

    def group_key(self) -> Tuple[Any, ...]:
        """Return the grouping key identifying frames that belong to the same single-frame series."""
        orientation_key = (
            tuple(round(v, 4) for v in self.orientation) if self.orientation else None
        )
        return (
            self.stack_id,
            self.temporal_index,
            self.echo_numbers,
            self.b_value,
            self.frame_type,
            orientation_key,
            self.extra_dimensions,
        )


def _dimension_pointers(ds: Dataset) -> List[Tuple[int, int]]:
    """Return tag pointers listed in DimensionIndexSequence in index order."""
    element = ds.get(_SEQ_DIMENSION_INDEX)
    if element is None or not element.value:
        return []
    pointers: List[Tuple[int, int]] = []
    for item in element.value:
        pointer = item.get(_TAG_DIMENSION_INDEX_POINTER)
        if pointer is None or pointer.value is None:
            continue
        value = pointer.value
        if hasattr(value, "group") and hasattr(value, "element"):
            pointers.append((int(value.group), int(value.element)))
        else:
            try:
                pointers.append((int(value[0]), int(value[1])))
            except (TypeError, IndexError, ValueError):
                continue
    return pointers


def _extra_dimensions(
    pointers: Sequence[Tuple[int, int]],
    values: Optional[Sequence[int]],
) -> Tuple[Tuple[Tuple[int, int], int], ...]:
    """Return allowlisted contrast/physics dimension index pairs for series grouping."""
    if not pointers or not values or len(pointers) != len(values):
        return ()
    extras: List[Tuple[Tuple[int, int], int]] = []
    for pointer, value in zip(pointers, values):
        if pointer not in _SERIES_SPLIT_DIMENSIONS:
            continue
        extras.append((pointer, int(value)))
    return tuple(extras)


def _normalize_str_sequence(raw: Any) -> Optional[Tuple[str, ...]]:
    """Normalize DICOM ImageType/FrameType value to a tuple of strings."""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="ignore")
    if isinstance(raw, str):
        parts = tuple(p.strip() for p in raw.split("\\") if p.strip())
        return parts or None
    try:
        parts = tuple(str(v).strip() for v in raw if str(v).strip())
        return parts or None
    except TypeError:
        return None


def _resolve_frame_type(
    per_frame: Optional[Dataset],
    shared: Optional[Dataset],
    top_ds: Dataset,
) -> Optional[Tuple[str, ...]]:
    """Resolve FrameType/ImageType across MR/CT frame-type sequences and top-level ImageType."""
    for seq_tag in (_SEQ_MR_FRAME_TYPE, _SEQ_CT_FRAME_TYPE):
        for container in (per_frame, shared):
            item = first_seq_item(container, seq_tag)
            if item is not None:
                if _TAG_FRAME_TYPE in item:
                    res = _normalize_str_sequence(item[_TAG_FRAME_TYPE].value)
                    if res:
                        return res
                if _TAG_IMAGE_TYPE in item:
                    res = _normalize_str_sequence(item[_TAG_IMAGE_TYPE].value)
                    if res:
                        return res
    if _TAG_IMAGE_TYPE in top_ds:
        return _normalize_str_sequence(top_ds[_TAG_IMAGE_TYPE].value)
    return None


def _extract_scalar_or_pair(val: Any) -> Any:
    """Return the first element if ``val`` is a multi-value list/tuple, else ``val``."""
    if val is None:
        return None
    if isinstance(val, (list, tuple)) or (hasattr(val, "__iter__") and not isinstance(val, (str, bytes))):
        seq = list(val)
        return seq[0] if seq else None
    return val


def extract_multiframe_frames(src_ds: Dataset) -> Tuple[List[MultiframeFrameMeta], List[Tuple[Any, ...]]]:
    """Extract per-frame metadata and geometry from a multi-frame DICOM dataset.

    Reconstructs missing ImagePositionPatient values along the slice normal using
    SpacingBetweenSlices or SliceThickness when orientation is valid and multiple frames exist.
    Returns ``(frames, warnings)`` where each warning is a structured tuple.
    """
    n_frames = as_int(src_ds.get("NumberOfFrames")) or 1
    per_frame_seq = src_ds.get(_SEQ_PER_FRAME_GROUPS)
    per_frame_items = list(per_frame_seq.value) if (per_frame_seq is not None and per_frame_seq.value) else []
    shared = first_seq_item(src_ds, _SEQ_SHARED_GROUPS)
    dimension_pointers = _dimension_pointers(src_ds)

    frames: List[MultiframeFrameMeta] = []
    warnings: List[Tuple[Any, ...]] = []

    for idx in range(n_frames):
        per_frame = per_frame_items[idx] if idx < len(per_frame_items) else None

        pos_raw = resolve_seq_tag(per_frame, shared, src_ds, _SEQ_PLANE_POSITION, _TAG_POSITION)
        if pos_raw is None:
            pos_raw = get_seq_attr(per_frame, shared, "PlanePositionPatientSequence", "ImagePositionPatient")
        position = as_floats(pos_raw)

        ori_raw = resolve_seq_tag(per_frame, shared, src_ds, _SEQ_PLANE_ORIENTATION, _TAG_ORIENTATION)
        if ori_raw is None:
            ori_raw = get_seq_attr(per_frame, shared, "PlaneOrientationPatientSequence", "ImageOrientationPatient")
        orientation = as_floats(ori_raw)

        pixel_spacing = as_floats(
            resolve_seq_tag(per_frame, shared, src_ds, _SEQ_PIXEL_MEASURES, _TAG_PIXEL_SPACING)
        )
        slice_thickness = resolve_seq_tag(per_frame, shared, src_ds, _SEQ_PIXEL_MEASURES, _TAG_SLICE_THICKNESS)
        spacing_between = resolve_seq_tag(per_frame, shared, src_ds, _SEQ_PIXEL_MEASURES, _TAG_SPACING_BETWEEN)

        wc = resolve_seq_tag(per_frame, shared, src_ds, _SEQ_FRAME_VOI_LUT, _TAG_WINDOW_CENTER)
        if wc is None:
            wc = get_seq_attr(per_frame, shared, "VOILUTSequence", "WindowCenter")
            if wc is None and "WindowCenter" in src_ds:
                wc = src_ds.WindowCenter
        ww = resolve_seq_tag(per_frame, shared, src_ds, _SEQ_FRAME_VOI_LUT, _TAG_WINDOW_WIDTH)
        if ww is None:
            ww = get_seq_attr(per_frame, shared, "VOILUTSequence", "WindowWidth")
            if ww is None and "WindowWidth" in src_ds:
                ww = src_ds.WindowWidth

        rescale_intercept = resolve_seq_tag(
            per_frame, shared, src_ds, _SEQ_PIXEL_VALUE_TRANSFORM, _TAG_RESCALE_INTERCEPT
        )
        rescale_slope = resolve_seq_tag(
            per_frame, shared, src_ds, _SEQ_PIXEL_VALUE_TRANSFORM, _TAG_RESCALE_SLOPE
        )
        rescale_type = resolve_seq_tag(
            per_frame, shared, src_ds, _SEQ_PIXEL_VALUE_TRANSFORM, _TAG_RESCALE_TYPE
        )

        frame_content = first_seq_item(per_frame, _SEQ_FRAME_CONTENT)
        if frame_content is None:
            frame_content = first_seq_item(shared, _SEQ_FRAME_CONTENT)

        stack_id = None
        in_stack_position = None
        temporal_index = None
        echo_numbers = None
        dimension_values: Optional[Tuple[int, ...]] = None

        if frame_content is not None:
            if _TAG_STACK_ID in frame_content:
                val = str(frame_content[_TAG_STACK_ID].value).strip()
                stack_id = val if val else None
            if _TAG_IN_STACK_POSITION in frame_content:
                in_stack_position = as_int(frame_content[_TAG_IN_STACK_POSITION].value)
            if _TAG_TEMPORAL_INDEX in frame_content:
                temporal_index = as_int(frame_content[_TAG_TEMPORAL_INDEX].value)
            if _TAG_ECHO_NUMBERS in frame_content:
                echo_numbers = str(frame_content[_TAG_ECHO_NUMBERS].value).strip() or None
            if _TAG_DIMENSION_INDEX_VALUES in frame_content:
                raw_dims = frame_content[_TAG_DIMENSION_INDEX_VALUES].value
                if raw_dims is not None:
                    try:
                        if isinstance(raw_dims, (int, float)):
                            dimension_values = (int(raw_dims),)
                        else:
                            dimension_values = tuple(int(v) for v in raw_dims)
                    except (TypeError, ValueError):
                        dimension_values = None

        if echo_numbers is None:
            echo_seq = first_seq_item(per_frame, _SEQ_MR_ECHO) or first_seq_item(shared, _SEQ_MR_ECHO)
            if echo_seq is not None and _TAG_ECHO_NUMBERS in echo_seq:
                echo_numbers = str(echo_seq[_TAG_ECHO_NUMBERS].value).strip() or None

        b_value = None
        diffusion_seq = first_seq_item(per_frame, _SEQ_MR_DIFFUSION) or first_seq_item(shared, _SEQ_MR_DIFFUSION)
        if diffusion_seq is not None and _TAG_DIFFUSION_B_VALUE in diffusion_seq:
            try:
                b_value = float(diffusion_seq[_TAG_DIFFUSION_B_VALUE].value)
            except (TypeError, ValueError):
                b_value = None

        frame_type = _resolve_frame_type(per_frame, shared, src_ds)
        extra_dims = _extra_dimensions(dimension_pointers, dimension_values)

        slice_loc = (
            compute_slice_location(position, orientation)
            if (position is not None and orientation is not None)
            else None
        )

        frames.append(
            MultiframeFrameMeta(
                index=idx,
                position=position,
                orientation=orientation,
                pixel_spacing=pixel_spacing,
                slice_thickness=slice_thickness,
                spacing_between_slices=spacing_between,
                window_center=_extract_scalar_or_pair(wc),
                window_width=_extract_scalar_or_pair(ww),
                rescale_intercept=rescale_intercept,
                rescale_slope=rescale_slope,
                rescale_type=rescale_type,
                frame_type=frame_type,
                stack_id=stack_id,
                in_stack_position=in_stack_position,
                temporal_index=temporal_index,
                echo_numbers=echo_numbers,
                b_value=b_value,
                dimension_index_values=dimension_values,
                extra_dimensions=extra_dims,
                slice_location=slice_loc,
            )
        )

    # Reconstruct missing ImagePositionPatient values when multiple frames share valid orientation
    if n_frames > 1:
        reconstructed_count = 0
        ori_groups: Dict[Tuple[float, ...], List[MultiframeFrameMeta]] = {}
        for frame in frames:
            if frame.orientation is None:
                continue
            if compute_slice_normal(frame.orientation) is None:
                continue
            ori_key = tuple(round(v, 4) for v in frame.orientation)
            ori_groups.setdefault(ori_key, []).append(frame)

        for ori_key, group_frames in ori_groups.items():
            if not any(f.position is None for f in group_frames):
                continue
            normal = compute_slice_normal(group_frames[0].orientation)
            if normal is None:
                continue

            anchor_idx = None
            anchor_pos = None
            for pos_in_group, frame in enumerate(group_frames):
                if frame.position is not None and len(frame.position) >= 3:
                    anchor_idx = pos_in_group
                    anchor_pos = frame.position
                    break

            for pos_in_group, frame in enumerate(group_frames):
                if frame.position is not None:
                    continue
                step_vals = as_floats(frame.spacing_between_slices) or as_floats(frame.slice_thickness)
                step = float(step_vals[0]) if step_vals else 1.0
                if anchor_pos is not None and anchor_idx is not None:
                    delta = (pos_in_group - anchor_idx) * step
                    frame.position = (
                        round(anchor_pos[0] + normal[0] * delta, 6),
                        round(anchor_pos[1] + normal[1] * delta, 6),
                        round(anchor_pos[2] + normal[2] * delta, 6),
                    )
                else:
                    delta = pos_in_group * step
                    frame.position = (
                        round(normal[0] * delta, 6),
                        round(normal[1] * delta, 6),
                        round(normal[2] * delta, 6),
                    )
                frame.slice_location = compute_slice_location(frame.position, frame.orientation)
                reconstructed_count += 1

        if reconstructed_count > 0:
            warnings.append(("reconstructed_ipp", reconstructed_count))

    return frames, warnings


def clean_and_build_dataset(
    src_ds: Dataset,
    pixel_data: np.ndarray,
    instance_number: int,
    study_uid: str,
    series_uid: str,
    sop_class: str,
    for_uid: str,
    config: ProcessingConfig,
    frame_type: Optional[Sequence[str]] = None,
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
        frame_type: Optional per-frame ImageType/FrameType sequence values.

    Returns:
        Новый Dataset с заполненными тегами.
    """
    new_ds = Dataset()
    excluded_tags = FORBIDDEN_TAGS_IDS | ENHANCED_CONTAINER_TAGS_IDS

    if config.clean_tags:
        # Быстрое копирование безопасных стандартных тегов по целочисленным ID
        for element in src_ds:
            if element.tag not in excluded_tags and not element.is_private and element.keyword:
                new_ds[element.tag] = element
    else:
        # Копируем всё, кроме структурных тегов мультифрейма, Enhanced-контейнера и пикселей
        for element in src_ds:
            if element.tag not in excluded_tags:
                new_ds[element.tag] = element

    # Preserve original SpecificCharacterSet when valid; save_dicom_file upgrades to ISO_IR 192 if needed
    orig_charset = getattr(src_ds, 'SpecificCharacterSet', None)
    new_ds.SpecificCharacterSet = orig_charset if orig_charset else 'ISO_IR 100'
    new_ds.SOPClassUID = sop_class
    new_ds.SOPInstanceUID = generate_uid()
    new_ds.StudyInstanceUID = study_uid
    new_ds.SeriesInstanceUID = series_uid
    new_ds.InstanceNumber = int(instance_number)
    new_ds.FrameOfReferenceUID = for_uid
    if frame_type:
        new_ds.ImageType = list(frame_type)
    else:
        new_ds.ImageType = getattr(src_ds, 'ImageType', ['ORIGINAL', 'PRIMARY'])

    # Геометрия матрицы
    new_ds.Rows = pixel_data.shape[0]
    new_ds.Columns = pixel_data.shape[1]
    samples_per_pixel = int(getattr(src_ds, 'SamplesPerPixel', 1) or 1)
    new_ds.SamplesPerPixel = samples_per_pixel
    new_ds.PhotometricInterpretation = getattr(src_ds, 'PhotometricInterpretation', 'MONOCHROME2')
    new_ds.BitsAllocated = getattr(src_ds, 'BitsAllocated', 16)
    new_ds.BitsStored = getattr(src_ds, 'BitsStored', 16)
    new_ds.HighBit = getattr(src_ds, 'HighBit', 15)
    new_ds.PixelRepresentation = getattr(src_ds, 'PixelRepresentation', 0)

    # Force 16-bit grayscale format for Monaco TPS (do not corrupt 8-bit RGB images)
    if samples_per_pixel == 1 and new_ds.BitsAllocated != 16:
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
    if new_ds.BitsAllocated == 8:
        dtype = np.int8 if new_ds.PixelRepresentation == 1 else np.uint8
        new_ds.PixelData = pixel_data.astype(dtype).tobytes()
        new_ds['PixelData'].VR = 'OB'
    else:
        dtype = np.int16 if new_ds.PixelRepresentation == 1 else np.uint16
        new_ds.PixelData = pixel_data.astype(dtype).tobytes()
        new_ds['PixelData'].VR = 'OW'

    return new_ds


def clean_and_build_dataset_inplace(
    src_ds: Dataset,
    instance_number: int,
    study_uid: str,
    series_uid: str,
    sop_class: str,
    for_uid: str,
    config: ProcessingConfig
) -> Dataset:
    """Модифицирует исходный Dataset на месте (in-place) для ускорения обработки.

    Исключает медленное копирование тегов и извлечение pixel_array (если BitsAllocated == 16).
    """
    is_unsplit_multiframe = (not config.split_multiframe) and ((as_int(src_ds.get('NumberOfFrames')) or 1) > 1)
    excluded_tags = FORBIDDEN_TAGS_INPLACE_IDS if is_unsplit_multiframe else (FORBIDDEN_TAGS_INPLACE_IDS | ENHANCED_CONTAINER_TAGS_IDS)

    # Удаляем запрещенные, Enhanced-контейнерные, приватные и некорректные теги
    if config.clean_tags:
        for tag in list(src_ds.keys()):
            element = src_ds[tag]
            if tag in excluded_tags or tag.is_private or not element.keyword:
                del src_ds[tag]
    else:
        for tag in list(src_ds.keys()):
            if tag in excluded_tags:
                del src_ds[tag]


    # Preserve original SpecificCharacterSet when present; save_dicom_file upgrades to ISO_IR 192 if needed
    orig_charset = getattr(src_ds, 'SpecificCharacterSet', None)
    src_ds.SpecificCharacterSet = orig_charset if orig_charset else 'ISO_IR 100'
    src_ds.SOPClassUID = sop_class
    src_ds.SOPInstanceUID = generate_uid()
    src_ds.StudyInstanceUID = study_uid
    src_ds.SeriesInstanceUID = series_uid
    src_ds.InstanceNumber = int(instance_number)
    src_ds.FrameOfReferenceUID = for_uid

    if not hasattr(src_ds, 'ImageType') or not src_ds.ImageType:
        src_ds.ImageType = ['ORIGINAL', 'PRIMARY']

    # Force 16-bit grayscale format for Monaco TPS (do not corrupt 8-bit RGB images)
    need_pixel_conversion = False
    samples_per_pixel = int(getattr(src_ds, 'SamplesPerPixel', 1) or 1)
    bits_allocated = getattr(src_ds, 'BitsAllocated', 16)
    if samples_per_pixel == 1 and bits_allocated != 16:
        src_ds.BitsAllocated = 16
        src_ds.BitsStored = 16
        src_ds.HighBit = 15
        need_pixel_conversion = True

    # Обязательные теги по умолчанию (если включено)
    if config.default_tags:
        if not hasattr(src_ds, 'AccessionNumber') or not src_ds.AccessionNumber:
            src_ds.AccessionNumber = "000000"
        if not hasattr(src_ds, 'StudyID') or not src_ds.StudyID:
            src_ds.StudyID = "1"
        if not hasattr(src_ds, 'ReferringPhysicianName') or not src_ds.ReferringPhysicianName:
            src_ds.ReferringPhysicianName = "UNKNOWN"
        if not hasattr(src_ds, 'Manufacturer') or not src_ds.Manufacturer:
            src_ds.Manufacturer = 'UNKNOWN'
        if not hasattr(src_ds, 'PatientID') or not src_ds.PatientID:
            src_ds.PatientID = "UNKNOWN"
        if not hasattr(src_ds, 'PatientName') or not src_ds.PatientName:
            src_ds.PatientName = "UNKNOWN"
        if not hasattr(src_ds, 'PatientBirthDate'):
            src_ds.PatientBirthDate = ''
        if not hasattr(src_ds, 'PatientSex') or not src_ds.PatientSex:
            src_ds.PatientSex = 'O'

        modality = getattr(src_ds, 'Modality', None)
        if modality == 'MR':
            if not hasattr(src_ds, 'MRAcquisitionType') or not src_ds.MRAcquisitionType:
                src_ds.MRAcquisitionType = '2D'
            if not hasattr(src_ds, 'ScanningSequence') or not src_ds.ScanningSequence:
                src_ds.ScanningSequence = 'SE'
            if not hasattr(src_ds, 'SequenceVariant') or not src_ds.SequenceVariant:
                src_ds.SequenceVariant = 'NONE'
            if not hasattr(src_ds, 'ScanOptions') or not src_ds.ScanOptions:
                src_ds.ScanOptions = 'NONE'
            if not hasattr(src_ds, 'EchoTime') or src_ds.EchoTime is None or src_ds.EchoTime == "":
                src_ds.EchoTime = 0.0
            if not hasattr(src_ds, 'RepetitionTime') or src_ds.RepetitionTime is None or src_ds.RepetitionTime == "":
                src_ds.RepetitionTime = 0.0
            if not hasattr(src_ds, 'MagneticFieldStrength') or src_ds.MagneticFieldStrength is None or src_ds.MagneticFieldStrength == "":
                src_ds.MagneticFieldStrength = 1.5
            if not hasattr(src_ds, 'AcquisitionNumber') or src_ds.AcquisitionNumber is None or src_ds.AcquisitionNumber == "":
                src_ds.AcquisitionNumber = 1

        elif modality == 'CT':
            src_ds.PatientSupportAngle = 0.0
            src_ds.TableTopPitchAngle = 0.0
            src_ds.TableTopRollAngle = 0.0

    # Выполняем конвертацию пикселей только в случае, если глубина исходного файла не 16 бит
    if need_pixel_conversion and any(tag in src_ds for tag in ['PixelData', 'FloatPixelData', 'DoubleFloatPixelData']):
        pixel_array = src_ds.pixel_array
        if getattr(src_ds, 'PixelRepresentation', 0) == 1:
            src_ds.PixelData = pixel_array.astype(np.int16).tobytes()
        else:
            src_ds.PixelData = pixel_array.astype(np.uint16).tobytes()

    return src_ds


def copy_geometry_and_rescale(
    src_ds: Dataset,
    new_ds: Dataset,
    frame_info: Optional[Dataset],
    shared_info: Optional[Dataset],
    is_multiframe: bool,
    frame_idx: int,
    frame_meta: Optional[MultiframeFrameMeta] = None,
) -> None:
    """Копирует или вычисляет геометрические параметры и калибровочные коэффициенты.

    Args:
        src_ds: Исходный Dataset.
        new_ds: Создаваемый целевой Dataset.
        frame_info: Метаданные конкретного кадра (для мультифреймов).
        shared_info: Общие метаданные всех кадров (для мультифреймов).
        is_multiframe: Является ли исходный файл многокадровым.
        frame_idx: Индекс кадра.
        frame_meta: Optional pre-extracted frame metadata.
    """
    if is_multiframe:
        if frame_meta is not None:
            img_pos = list(frame_meta.position) if frame_meta.position is not None else None
            img_ori = list(frame_meta.orientation) if frame_meta.orientation is not None else None
            pixel_spacing = list(frame_meta.pixel_spacing) if frame_meta.pixel_spacing is not None else None
            slice_thickness = frame_meta.slice_thickness
            spacing_between = frame_meta.spacing_between_slices
            rescale_intercept = frame_meta.rescale_intercept
            rescale_slope = frame_meta.rescale_slope
            rescale_type = frame_meta.rescale_type
            wc = frame_meta.window_center
            ww = frame_meta.window_width
            slice_location = frame_meta.slice_location
        else:
            img_pos = get_seq_attr(frame_info, shared_info, 'PlanePositionSequence', 'ImagePositionPatient') or \
                      get_seq_attr(frame_info, shared_info, 'PlanePositionPatientSequence', 'ImagePositionPatient')
            img_ori = get_seq_attr(frame_info, shared_info, 'PlaneOrientationSequence', 'ImageOrientationPatient') or \
                      get_seq_attr(frame_info, shared_info, 'PlaneOrientationPatientSequence', 'ImageOrientationPatient')
            pixel_spacing = get_seq_attr(frame_info, shared_info, 'PixelMeasuresSequence', 'PixelSpacing')
            slice_thickness = get_seq_attr(frame_info, shared_info, 'PixelMeasuresSequence', 'SliceThickness')
            spacing_between = get_seq_attr(frame_info, shared_info, 'PixelMeasuresSequence', 'SpacingBetweenSlices')
            rescale_intercept = get_seq_attr(frame_info, shared_info, 'PixelValueTransformationSequence', 'RescaleIntercept')
            rescale_slope = get_seq_attr(frame_info, shared_info, 'PixelValueTransformationSequence', 'RescaleSlope')
            rescale_type = get_seq_attr(frame_info, shared_info, 'PixelValueTransformationSequence', 'RescaleType')
            wc = get_seq_attr(frame_info, shared_info, 'FrameVOILUTSequence', 'WindowCenter') or \
                 get_seq_attr(frame_info, shared_info, 'VOILUTSequence', 'WindowCenter')
            ww = get_seq_attr(frame_info, shared_info, 'FrameVOILUTSequence', 'WindowWidth') or \
                 get_seq_attr(frame_info, shared_info, 'VOILUTSequence', 'WindowWidth')
            slice_location = compute_slice_location(img_pos, img_ori) if (img_pos and img_ori) else None

        if img_pos:
            new_ds.ImagePositionPatient = img_pos
        if img_ori:
            new_ds.ImageOrientationPatient = img_ori

        if slice_location is not None:
            new_ds.SliceLocation = slice_location
        elif img_pos and img_ori:
            calc_loc = compute_slice_location(img_pos, img_ori)
            new_ds.SliceLocation = calc_loc if calc_loc is not None else float(frame_idx)
        else:
            new_ds.SliceLocation = float(frame_idx)

        if pixel_spacing:
            new_ds.PixelSpacing = pixel_spacing
        if slice_thickness is not None:
            new_ds.SliceThickness = slice_thickness
        if spacing_between is not None:
            new_ds.SpacingBetweenSlices = spacing_between

        new_ds.RescaleIntercept = rescale_intercept if rescale_intercept is not None else 0
        new_ds.RescaleSlope = rescale_slope if rescale_slope is not None else 1
        if rescale_type is not None:
            new_ds.RescaleType = rescale_type

        wc_val = _extract_scalar_or_pair(wc)
        ww_val = _extract_scalar_or_pair(ww)
        if wc_val is not None:
            new_ds.WindowCenter = wc_val
        if ww_val is not None:
            new_ds.WindowWidth = ww_val

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
            calc_loc = compute_slice_location(new_ds.ImagePositionPatient, new_ds.ImageOrientationPatient)
            if calc_loc is not None:
                new_ds.SliceLocation = calc_loc

_CHARSET_CODECS = {
    "ISO_IR 100": "latin_1",
    "ISO_IR 101": "iso8859_2",
    "ISO_IR 109": "iso8859_3",
    "ISO_IR 110": "iso8859_4",
    "ISO_IR 144": "iso8859_5",
    "ISO_IR 127": "iso8859_6",
    "ISO_IR 126": "iso8859_7",
    "ISO_IR 138": "iso8859_8",
    "ISO_IR 148": "iso8859_9",
    "ISO_IR 192": "utf_8",
}
_TEXT_VRS = {"SH", "LO", "ST", "LT", "UT", "UC", "PN"}


def _iter_text_strings(ds: Dataset):
    """Yield string representations of text and PersonName elements recursively."""
    for elem in ds:
        if elem.VR == "SQ" and elem.value:
            for item in elem.value:
                for nested in _iter_text_strings(item):
                    yield nested
        elif elem.VR in _TEXT_VRS and elem.value is not None:
            if isinstance(elem.value, (list, tuple)):
                for part in elem.value:
                    if part is not None:
                        yield str(part)
            else:
                yield str(elem.value)


def _can_encode_all(texts: Sequence[str], codec: str) -> bool:
    """Return True if every string in ``texts`` can be encoded with ``codec``."""
    for text in texts:
        try:
            text.encode(codec)
        except UnicodeEncodeError:
            return False
    return True


def _ensure_encodable_charset(dataset: Dataset) -> None:
    """Prefer ISO_IR 100 for Monaco compatibility when Latin-1 suffices; upgrade only for non-Latin-1 text."""
    texts = list(_iter_text_strings(dataset))
    if _can_encode_all(texts, "latin_1"):
        dataset.SpecificCharacterSet = "ISO_IR 100"
        return

    cs_raw = getattr(dataset, "SpecificCharacterSet", None)
    if isinstance(cs_raw, (list, tuple)):
        cs_name = str(cs_raw[0]).strip() if cs_raw else ""
    else:
        cs_name = str(cs_raw).strip() if cs_raw else ""

    codec = _CHARSET_CODECS.get(cs_name)
    if codec and _can_encode_all(texts, codec):
        return

    dataset.SpecificCharacterSet = "ISO_IR 192"


def save_dicom_file(out_path: Path, dataset: Dataset, explicit_vr: bool) -> None:
    """Сохраняет Dataset в файл DICOM на диске.

    Args:
        out_path: Целевой путь сохранения файла.
        dataset: Сохраняемый Dataset.
        explicit_vr: Флаг сохранения в Explicit VR Little Endian.
    """
    _ensure_encodable_charset(dataset)

    if 'PixelData' in dataset:
        bits = int(getattr(dataset, 'BitsAllocated', 16) or 16)
        dataset['PixelData'].VR = 'OB' if bits == 8 else 'OW'

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = dataset.SOPClassUID
    file_meta.MediaStorageSOPInstanceUID = dataset.SOPInstanceUID
    file_meta.ImplementationClassUID = pydicom.uid.PYDICOM_IMPLEMENTATION_UID
    file_meta.TransferSyntaxUID = (
        ExplicitVRLittleEndian if explicit_vr else pydicom.uid.ImplicitVRLittleEndian
    )

    final_ds = FileDataset(str(out_path), dataset, file_meta=file_meta, preamble=b"\0" * 128)
    try:
        final_ds.save_as(str(out_path), enforce_file_format=True)
    except TypeError:
        final_ds.is_implicit_VR = not explicit_vr
        final_ds.is_little_endian = True
        final_ds.save_as(str(out_path), write_like_original=False)
