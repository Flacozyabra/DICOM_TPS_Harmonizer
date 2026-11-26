"""Synthetic DICOM dataset builders for unit and integration tests."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence as DicomSequence
from pydicom.uid import ExplicitVRLittleEndian, generate_uid


ENHANCED_MR_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.4.1"
CLASSIC_MR_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.4"


def make_per_frame_group(
    position: Optional[Sequence[float]] = None,
    orientation: Optional[Sequence[float]] = None,
    stack_id: Optional[str] = None,
    in_stack_position: Optional[int] = None,
    temporal_index: Optional[int] = None,
    echo_number: Optional[int] = None,
    b_value: Optional[float] = None,
    gradient_dir: Optional[Sequence[float]] = None,
    frame_type: Optional[Sequence[str]] = None,
    dimension_values: Optional[Sequence[int]] = None,
    window_center: Optional[float] = None,
    window_width: Optional[float] = None,
    slice_thickness: Optional[float] = None,
    spacing_between: Optional[float] = None,
    pixel_spacing: Optional[Sequence[float]] = None,
) -> Dataset:
    """Create a PerFrameFunctionalGroupsSequence item."""
    item = Dataset()

    if position is not None:
        pos_ds = Dataset()
        pos_ds.ImagePositionPatient = [float(v) for v in position]
        item.PlanePositionSequence = DicomSequence([pos_ds])

    if orientation is not None:
        ori_ds = Dataset()
        ori_ds.ImageOrientationPatient = [float(v) for v in orientation]
        item.PlaneOrientationSequence = DicomSequence([ori_ds])

    if any(v is not None for v in (stack_id, in_stack_position, temporal_index, echo_number, dimension_values)):
        fc_ds = Dataset()
        if stack_id is not None:
            fc_ds.StackID = str(stack_id)
        if in_stack_position is not None:
            fc_ds.InStackPositionNumber = int(in_stack_position)
        if temporal_index is not None:
            fc_ds.TemporalPositionIndex = int(temporal_index)
        if echo_number is not None:
            fc_ds.EchoNumbers = int(echo_number)
        if dimension_values is not None:
            fc_ds.DimensionIndexValues = [int(v) for v in dimension_values]
        item.FrameContentSequence = DicomSequence([fc_ds])

    if b_value is not None or gradient_dir is not None:
        diff_ds = Dataset()
        if b_value is not None:
            diff_ds.DiffusionBValue = float(b_value)
        if gradient_dir is not None:
            grad_ds = Dataset()
            grad_ds.DiffusionGradientOrientation = [float(v) for v in gradient_dir]
            diff_ds.DiffusionGradientDirectionSequence = DicomSequence([grad_ds])
            diff_ds.DiffusionDirectionality = "DIRECTIONAL"
        item.MRDiffusionSequence = DicomSequence([diff_ds])

    if frame_type is not None:
        ft_ds = Dataset()
        ft_ds.FrameType = list(frame_type)
        item.MRImageFrameTypeSequence = DicomSequence([ft_ds])

    if window_center is not None or window_width is not None:
        voi_ds = Dataset()
        if window_center is not None:
            voi_ds.WindowCenter = float(window_center)
        if window_width is not None:
            voi_ds.WindowWidth = float(window_width)
        item.FrameVOILUTSequence = DicomSequence([voi_ds])

    if any(v is not None for v in (pixel_spacing, slice_thickness, spacing_between)):
        pm_ds = Dataset()
        if pixel_spacing is not None:
            pm_ds.PixelSpacing = [float(v) for v in pixel_spacing]
        if slice_thickness is not None:
            pm_ds.SliceThickness = float(slice_thickness)
        if spacing_between is not None:
            pm_ds.SpacingBetweenSlices = float(spacing_between)
        item.PixelMeasuresSequence = DicomSequence([pm_ds])

    return item


def build_enhanced_mr_dataset(
    frame_specs: List[Dict[str, Any]],
    rows: int = 16,
    cols: int = 16,
    bits_allocated: int = 16,
    bits_stored: int = 12,
    high_bit: int = 11,
    study_uid: Optional[str] = None,
    series_uid: Optional[str] = None,
    for_uid: Optional[str] = None,
    series_number: int = 101,
    series_description: str = "T2_AX_ENHANCED",
    patient_name: str = "Test^Patient",
    patient_id: str = "PAT001",
    dimension_pointers: Optional[Sequence[Tuple[int, int]]] = None,
    include_enhanced_container_tags: bool = True,
    add_private_tag: bool = True,
) -> Tuple[FileDataset, np.ndarray]:
    """Build an in-memory Enhanced MR FileDataset and its pixel array."""
    n_frames = len(frame_specs)
    dtype = np.uint8 if bits_allocated == 8 else np.uint16
    pixels = np.zeros((n_frames, rows, cols), dtype=dtype)
    max_val = (1 << bits_stored) - 1
    for i in range(n_frames):
        base = (i + 1) * 50
        ramp = (np.arange(rows * cols, dtype=np.int64).reshape(rows, cols) + base) % (max_val + 1)
        pixels[i] = ramp.astype(dtype)

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = ENHANCED_MR_SOP_CLASS
    sop_uid = generate_uid()
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = pydicom.uid.PYDICOM_IMPLEMENTATION_UID

    ds = FileDataset("", {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    ds.SpecificCharacterSet = "ISO_IR 100"
    ds.SOPClassUID = ENHANCED_MR_SOP_CLASS
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid or generate_uid()
    ds.SeriesInstanceUID = series_uid or generate_uid()
    ds.FrameOfReferenceUID = for_uid or generate_uid()
    ds.Modality = "MR"
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.SeriesNumber = series_number
    ds.SeriesDescription = series_description
    ds.ImageType = ["ORIGINAL", "PRIMARY", "M_FFE", "M", "FFE"]

    ds.Rows = rows
    ds.Columns = cols
    ds.NumberOfFrames = n_frames
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = bits_allocated
    ds.BitsStored = bits_stored
    ds.HighBit = high_bit
    ds.PixelRepresentation = 0

    shared_ds = Dataset()
    pm_ds = Dataset()
    pm_ds.PixelSpacing = [1.0, 1.0]
    pm_ds.SliceThickness = 2.5
    pm_ds.SpacingBetweenSlices = 2.5
    shared_ds.PixelMeasuresSequence = DicomSequence([pm_ds])

    pvt_ds = Dataset()
    pvt_ds.RescaleIntercept = 0.0
    pvt_ds.RescaleSlope = 1.0
    pvt_ds.RescaleType = "US"
    shared_ds.PixelValueTransformationSequence = DicomSequence([pvt_ds])

    voi_ds = Dataset()
    voi_ds.WindowCenter = 500.0
    voi_ds.WindowWidth = 1000.0
    shared_ds.FrameVOILUTSequence = DicomSequence([voi_ds])

    ds.SharedFunctionalGroupsSequence = DicomSequence([shared_ds])
    ds.PerFrameFunctionalGroupsSequence = DicomSequence(
        [make_per_frame_group(**spec) for spec in frame_specs]
    )

    if dimension_pointers:
        dim_items = []
        for ptr in dimension_pointers:
            dim_item = Dataset()
            dim_item.DimensionIndexPointer = pydicom.tag.Tag(ptr[0], ptr[1])
            dim_item.DimensionOrganizationUID = generate_uid()
            dim_items.append(dim_item)
        ds.DimensionIndexSequence = DicomSequence(dim_items)

    if include_enhanced_container_tags:
        dim_org = Dataset()
        dim_org.DimensionOrganizationUID = generate_uid()
        ds.DimensionOrganizationSequence = DicomSequence([dim_org])
        ds.FrameLaterality = "U"
        ref_img = Dataset()
        ref_img.ReferencedSOPClassUID = ENHANCED_MR_SOP_CLASS
        ref_img.ReferencedSOPInstanceUID = generate_uid()
        ds.ReferencedImageSequence = DicomSequence([ref_img])
        ref_pps = Dataset()
        ref_pps.ReferencedSOPClassUID = "1.2.840.10008.3.1.2.3.3"
        ref_pps.ReferencedSOPInstanceUID = generate_uid()
        ds.ReferencedPerformedProcedureStepSequence = DicomSequence([ref_pps])
        ds.PixelPresentation = "MONOCHROME"
        ds.VolumetricProperties = "VOLUME"
        ds.VolumeBasedCalculationTechnique = "NONE"
        ds.ComplexImageComponent = "MAGNITUDE"
        ds.AcquisitionContrast = "T2"

    if add_private_tag:
        ds.add_new((0x2001, 0x0010), "LO", "Philips Imaging DD 001")
        ds.add_new((0x2001, 0x1001), "IS", "42")

    ds.PixelData = pixels.tobytes()
    ds["PixelData"].VR = "OB" if bits_allocated == 8 else "OW"
    return ds, pixels


def save_dataset(ds: FileDataset, path: Path) -> Path:
    """Save a FileDataset to disk compatibly across pydicom 2.4+ and 3.x."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), write_like_original=False)
    return path
