import tempfile
import threading
import unittest
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pydicom
from pydicom.uid import generate_uid

from src.core.config import ProcessingConfig
from src.core.converter import ENHANCED_CONTAINER_TAGS_TUPLES
from src.core.processor import (
    DicomProcessor,
    _compute_adaptive_chunk_size,
    _compute_worker_count,
    verify_dicom_series_on_disk,
)
from src.utils.helpers import compute_slice_normal
from src.utils.logger import BaseLogger
from tests.helpers_dicom import CLASSIC_MR_SOP_CLASS, build_enhanced_mr_dataset, save_dataset


class MemoryLogger(BaseLogger):
    """Thread-safe in-memory logger capturing log messages and tags for test assertions."""

    def __init__(self) -> None:
        self.records: List[Tuple[str, str]] = []
        self.progress: List[Tuple[int, int]] = []

    def log(self, text: str, tag: str = "info") -> None:
        self.records.append((tag, text))

    def update_progress(self, current: int, total: int) -> None:
        self.progress.append((current, total))

    def update_scan_progress(self, current: int, total: int) -> None:
        pass


def _default_config(**overrides) -> ProcessingConfig:
    params = dict(
        new_uids=True,
        split_multiframe=True,
        clean_tags=True,
        default_tags=True,
        explicit_vr=True,
        exclude_reports=True,
        split_series=True,
        exclude_localizers=True,
    )
    params.update(overrides)
    return ProcessingConfig(**params)


class ProcessorMultiframeTests(unittest.TestCase):
    def _run_processor(self, input_dir: Path, output_dir: Path, config: ProcessingConfig) -> Tuple[DicomProcessor, MemoryLogger]:
        logger = MemoryLogger()
        stop_event = threading.Event()
        proc = DicomProcessor(input_dir, output_dir, config, logger, stop_event, lang="en")
        proc.process()
        return proc, logger

    def test_splits_multiframe_by_stack_id_and_orientation(self):
        # Stack 1: 3 axial frames (out of order by InStackPositionNumber), Stack 2: 2 sagittal frames
        frame_specs = [
            {"position": (0.0, 0.0, 20.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), "stack_id": "1", "in_stack_position": 3},
            {"position": (0.0, 0.0, 10.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), "stack_id": "1", "in_stack_position": 1},
            {"position": (0.0, 0.0, 15.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), "stack_id": "1", "in_stack_position": 2},
            {"position": (-5.0, 0.0, 0.0), "orientation": (0.0, 1.0, 0.0, 0.0, 0.0, -1.0), "stack_id": "2", "in_stack_position": 1},
            {"position": (5.0, 0.0, 0.0), "orientation": (0.0, 1.0, 0.0, 0.0, 0.0, -1.0), "stack_id": "2", "in_stack_position": 2},
        ]
        ds, pixels = build_enhanced_mr_dataset(frame_specs, series_number=101, series_description="LOC_3PLANE")

        with tempfile.TemporaryDirectory() as tmpdir:
            in_dir = Path(tmpdir) / "in"
            out_dir = Path(tmpdir) / "out"
            save_dataset(ds, in_dir / "enhanced.dcm")

            proc, logger = self._run_processor(in_dir, out_dir, _default_config(split_series=True))
            self.assertEqual(proc.success_count, 5)
            self.assertEqual(proc.error_count, 0)

            dcm_files = sorted(out_dir.rglob("*.dcm"))
            self.assertEqual(len(dcm_files), 5)

            # Should create 2 subseries folders and no empty parent leftover folder
            series_dirs = sorted(p for p in (out_dir / "Test^Patient_PAT001").iterdir() if p.is_dir())
            self.assertEqual(len(series_dirs), 2)
            self.assertIn("MR_101_LOC_3PLANE_Stack1", [d.name for d in series_dirs])
            self.assertIn("MR_102_LOC_3PLANE_Stack2", [d.name for d in series_dirs])

            datasets = [pydicom.dcmread(str(p)) for p in dcm_files]
            self.assertEqual(len({str(d.SeriesInstanceUID) for d in datasets}), 2)
            self.assertEqual(len({str(d.SOPInstanceUID) for d in datasets}), 5)

            # Check bit-exact pixel preservation matched by ImagePositionPatient and normalized SliceLocation
            for out_ds in datasets:
                self.assertEqual(out_ds.SOPClassUID, CLASSIC_MR_SOP_CLASS)
                self.assertEqual(int(out_ds.BitsStored), 12)
                for tag_tuple in ENHANCED_CONTAINER_TAGS_TUPLES:
                    self.assertNotIn(tag_tuple, out_ds)
                self.assertFalse(any(t.is_private for t in out_ds.keys()))

                pos_out = tuple(round(float(v), 4) for v in out_ds.ImagePositionPatient)
                src_idx = next(
                    i for i, spec in enumerate(frame_specs)
                    if tuple(round(v, 4) for v in spec["position"]) == pos_out
                )
                np.testing.assert_array_equal(out_ds.pixel_array, pixels[src_idx])

                normal = compute_slice_normal([float(v) for v in out_ds.ImageOrientationPatient])
                expected_loc = sum(p * n for p, n in zip(pos_out, normal))
                self.assertAlmostEqual(float(out_ds.SliceLocation), expected_loc, places=3)

            # Should NOT emit duplicate IPP warning when stacks are cleanly split
            self.assertFalse(any("duplicate ImagePositionPatient" in msg for _, msg in logger.records))

    def test_splits_multiframe_by_echo_temporal_and_b_value(self):
        # 2 echoes + 2 b-values + 2 temporal phases across same orientation
        axial = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        frame_specs = [
            # Group 1: stack 1, echo 1, t1, b=0
            {"position": (0.0, 0.0, 0.0), "orientation": axial, "stack_id": "1", "echo_number": 1, "temporal_index": 1, "b_value": 0.0},
            {"position": (0.0, 0.0, 5.0), "orientation": axial, "stack_id": "1", "echo_number": 1, "temporal_index": 1, "b_value": 0.0},
            # Group 2: stack 1, echo 2, t1, b=0
            {"position": (0.0, 0.0, 0.0), "orientation": axial, "stack_id": "1", "echo_number": 2, "temporal_index": 1, "b_value": 0.0},
            {"position": (0.0, 0.0, 5.0), "orientation": axial, "stack_id": "1", "echo_number": 2, "temporal_index": 1, "b_value": 0.0},
            # Group 3: stack 1, echo 1, t2, b=1000
            {"position": (0.0, 0.0, 0.0), "orientation": axial, "stack_id": "1", "echo_number": 1, "temporal_index": 2, "b_value": 1000.0},
            {"position": (0.0, 0.0, 5.0), "orientation": axial, "stack_id": "1", "echo_number": 1, "temporal_index": 2, "b_value": 1000.0},
        ]
        ds, _ = build_enhanced_mr_dataset(frame_specs, series_number=201, series_description="MULTI_DIM")

        with tempfile.TemporaryDirectory() as tmpdir:
            in_dir = Path(tmpdir) / "in"
            out_dir = Path(tmpdir) / "out"
            save_dataset(ds, in_dir / "multi.dcm")

            proc, logger = self._run_processor(in_dir, out_dir, _default_config(split_series=True))
            self.assertEqual(proc.success_count, 6)
            self.assertEqual(proc.error_count, 0)

            series_dirs = sorted(p for p in (out_dir / "Test^Patient_PAT001").iterdir() if p.is_dir())
            self.assertEqual(len(series_dirs), 3)
            for sdir in series_dirs:
                files = sorted(sdir.glob("*.dcm"))
                self.assertEqual(len(files), 2)
                report = verify_dicom_series_on_disk(files)
                self.assertEqual(report["pixel_errors"], [])
                self.assertFalse(report["duplicate_positions"])

            self.assertFalse(any("duplicate ImagePositionPatient" in msg for _, msg in logger.records))

    def test_split_series_false_keeps_single_series_and_warns_duplicate_ipp(self):
        axial = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        frame_specs = [
            {"position": (0.0, 0.0, 0.0), "orientation": axial, "stack_id": "1", "echo_number": 1},
            {"position": (0.0, 0.0, 5.0), "orientation": axial, "stack_id": "1", "echo_number": 1},
            {"position": (0.0, 0.0, 0.0), "orientation": axial, "stack_id": "1", "echo_number": 2},
            {"position": (0.0, 0.0, 5.0), "orientation": axial, "stack_id": "1", "echo_number": 2},
        ]
        ds, _ = build_enhanced_mr_dataset(frame_specs, series_number=301, series_description="DUAL_ECHO")

        with tempfile.TemporaryDirectory() as tmpdir:
            in_dir = Path(tmpdir) / "in"
            out_dir = Path(tmpdir) / "out"
            save_dataset(ds, in_dir / "echoes.dcm")

            proc, logger = self._run_processor(in_dir, out_dir, _default_config(split_series=False))
            self.assertEqual(proc.success_count, 4)

            series_dirs = sorted(p for p in (out_dir / "Test^Patient_PAT001").iterdir() if p.is_dir())
            self.assertEqual(len(series_dirs), 1)
            dcm_files = sorted(series_dirs[0].glob("*.dcm"))
            self.assertEqual(len(dcm_files), 4)
            self.assertEqual(len({str(pydicom.dcmread(str(p)).SeriesInstanceUID) for p in dcm_files}), 1)

            self.assertTrue(
                any(tag == "warning" and "duplicate ImagePositionPatient" in msg for tag, msg in logger.records),
                f"Expected duplicate IPP warning in logs: {logger.records}",
            )

    def test_collision_protection_across_multiframes_and_duplicate_instances(self):
        axial = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        shared_series_uid = generate_uid()
        shared_study_uid = generate_uid()

        # Two multiframe files with the exact same SeriesInstanceUID
        ds_mf1, _ = build_enhanced_mr_dataset(
            [
                {"position": (0.0, 0.0, 0.0), "orientation": axial, "stack_id": "1"},
                {"position": (0.0, 0.0, 2.5), "orientation": axial, "stack_id": "1"},
            ],
            study_uid=shared_study_uid,
            series_uid=shared_series_uid,
            series_number=401,
            series_description="SAME_SERIES",
        )
        ds_mf2, _ = build_enhanced_mr_dataset(
            [
                {"position": (0.0, 0.0, 5.0), "orientation": axial, "stack_id": "1"},
                {"position": (0.0, 0.0, 7.5), "orientation": axial, "stack_id": "1"},
            ],
            study_uid=shared_study_uid,
            series_uid=shared_series_uid,
            series_number=401,
            series_description="SAME_SERIES",
        )

        # Two classic single-frame files with identical InstanceNumber=1 in a different series
        ds_sf1, _ = build_enhanced_mr_dataset(
            [{"position": (0.0, 0.0, 0.0), "orientation": axial}],
            study_uid=shared_study_uid,
            series_number=402,
            series_description="DUP_INST",
        )
        ds_sf1.NumberOfFrames = 1
        ds_sf1.InstanceNumber = 1
        ds_sf1.ImagePositionPatient = [0.0, 0.0, 0.0]
        ds_sf1.ImageOrientationPatient = list(axial)

        ds_sf2, _ = build_enhanced_mr_dataset(
            [{"position": (0.0, 0.0, 5.0), "orientation": axial}],
            study_uid=shared_study_uid,
            series_uid=ds_sf1.SeriesInstanceUID,
            series_number=402,
            series_description="DUP_INST",
        )
        ds_sf2.NumberOfFrames = 1
        ds_sf2.InstanceNumber = 1
        ds_sf2.ImagePositionPatient = [0.0, 0.0, 5.0]
        ds_sf2.ImageOrientationPatient = list(axial)

        with tempfile.TemporaryDirectory() as tmpdir:
            in_dir = Path(tmpdir) / "in"
            out_dir = Path(tmpdir) / "out"
            save_dataset(ds_mf1, in_dir / "mf1.dcm")
            save_dataset(ds_mf2, in_dir / "mf2.dcm")
            save_dataset(ds_sf1, in_dir / "sf1.dcm")
            save_dataset(ds_sf2, in_dir / "sf2.dcm")

            proc, _ = self._run_processor(in_dir, out_dir, _default_config())
            self.assertEqual(proc.success_count, 6)
            self.assertEqual(proc.error_count, 0)

            all_out = sorted(out_dir.rglob("*.dcm"))
            self.assertEqual(len(all_out), 6)

    def test_missing_ipp_reconstructed_and_logged_in_processor(self):
        axial = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        ds, _ = build_enhanced_mr_dataset(
            [
                {"position": (0.0, 0.0, 10.0), "orientation": axial, "spacing_between": 3.0},
                {"position": None, "orientation": axial, "spacing_between": 3.0},
                {"position": None, "orientation": axial, "spacing_between": 3.0},
            ],
            series_number=501,
            series_description="MISSING_IPP",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            in_dir = Path(tmpdir) / "in"
            out_dir = Path(tmpdir) / "out"
            save_dataset(ds, in_dir / "missing_ipp.dcm")

            proc, logger = self._run_processor(in_dir, out_dir, _default_config())
            self.assertEqual(proc.success_count, 3)
            self.assertTrue(
                any(tag == "warning" and "lacked ImagePositionPatient" in msg for tag, msg in logger.records),
                f"Expected reconstructed IPP warning in logs: {logger.records}",
            )

            out_files = sorted(out_dir.rglob("*.dcm"))
            z_vals = sorted(float(pydicom.dcmread(str(p)).ImagePositionPatient[2]) for p in out_files)
            self.assertEqual(z_vals, [10.0, 13.0, 16.0])
            self.assertFalse(verify_dicom_series_on_disk(out_files)["duplicate_positions"])

    def test_verify_dicom_series_on_disk_detects_corruption_and_duplicates(self):
        axial = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = Path(tmpdir) / "s1.dcm"
            p2 = Path(tmpdir) / "s2.dcm"

            ds1, _ = build_enhanced_mr_dataset([{"position": (0.0, 0.0, 0.0), "orientation": axial}])
            ds1.NumberOfFrames = 1
            ds1.ImagePositionPatient = [0.0, 0.0, 10.0]
            save_dataset(ds1, p1)

            ds2, _ = build_enhanced_mr_dataset([{"position": (0.0, 0.0, 0.0), "orientation": axial}])
            ds2.NumberOfFrames = 1
            ds2.ImagePositionPatient = [0.0, 0.0, 10.0]  # Duplicate IPP!
            ds2.PixelData = b"\x00" * 10  # Truncated PixelData!
            save_dataset(ds2, p2)

            report = verify_dicom_series_on_disk([p1, p2])
            self.assertTrue(report["duplicate_positions"])
            self.assertEqual(len(report["pixel_errors"]), 1)
            self.assertEqual(report["pixel_errors"][0][0], "s2.dcm")

    def test_splits_multiframe_by_frame_type_and_orientation_without_stack_id(self):
        axial = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        sagittal = (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)
        frame_specs = [
            {"position": (0.0, 0.0, 0.0), "orientation": axial, "frame_type": ("ORIGINAL", "PRIMARY", "M_FFE")},
            {"position": (0.0, 0.0, 0.0), "orientation": axial, "frame_type": ("DERIVED", "PRIMARY", "ADC")},
            {"position": (5.0, 0.0, 0.0), "orientation": sagittal, "frame_type": ("ORIGINAL", "PRIMARY", "M_FFE")},
        ]
        ds, _ = build_enhanced_mr_dataset(frame_specs, series_number=601, series_description="MIXED_FT")
        with tempfile.TemporaryDirectory() as tmpdir:
            in_dir = Path(tmpdir) / "in"
            out_dir = Path(tmpdir) / "out"
            save_dataset(ds, in_dir / "mixed_ft.dcm")

            proc, logger = self._run_processor(in_dir, out_dir, _default_config(split_series=True))
            self.assertEqual(proc.success_count, 3)
            self.assertEqual(proc.error_count, 0)

            series_dirs = sorted(p for p in (out_dir / "Test^Patient_PAT001").iterdir() if p.is_dir())
            self.assertEqual(len(series_dirs), 3)
            out_files = sorted(out_dir.rglob("*.dcm"))
            self.assertEqual(len({str(pydicom.dcmread(str(p)).SeriesInstanceUID) for p in out_files}), 3)
            self.assertFalse(any("duplicate ImagePositionPatient" in msg for _, msg in logger.records))

    def test_deterministic_ordering_for_single_frame_without_instance_number(self):
        axial = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        study_uid = generate_uid()
        series_uid = generate_uid()

        with tempfile.TemporaryDirectory() as tmpdir:
            in_dir = Path(tmpdir) / "in"
            out_dir = Path(tmpdir) / "out"
            for fname, z_val in (("d.dcm", 30.0), ("a.dcm", 10.0), ("c.dcm", 40.0), ("b.dcm", 20.0)):
                ds, _ = build_enhanced_mr_dataset(
                    [{"position": (0.0, 0.0, z_val), "orientation": axial}],
                    study_uid=study_uid,
                    series_uid=series_uid,
                    series_number=701,
                    series_description="NO_INST",
                )
                ds.NumberOfFrames = 1
                ds.ImagePositionPatient = [0.0, 0.0, z_val]
                ds.ImageOrientationPatient = list(axial)
                if "InstanceNumber" in ds:
                    del ds.InstanceNumber
                save_dataset(ds, in_dir / fname)

            proc, _ = self._run_processor(in_dir, out_dir, _default_config())
            self.assertEqual(proc.success_count, 4)

            out_files = sorted(out_dir.rglob("*.dcm"))
            z_by_slice = [float(pydicom.dcmread(str(p)).ImagePositionPatient[2]) for p in out_files]
            self.assertEqual(z_by_slice, [10.0, 20.0, 30.0, 40.0])

    def test_mismatched_number_of_frames_reports_clear_error(self):
        axial = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        ds, px = build_enhanced_mr_dataset(
            [
                {"position": (0.0, 0.0, 0.0), "orientation": axial},
                {"position": (0.0, 0.0, 2.5), "orientation": axial},
            ],
            series_number=801,
            series_description="BAD_NFRAMES",
        )
        # Claim 5 frames in header when PixelData only holds 2 frames
        ds.NumberOfFrames = 5
        with tempfile.TemporaryDirectory() as tmpdir:
            in_dir = Path(tmpdir) / "in"
            out_dir = Path(tmpdir) / "out"
            save_dataset(ds, in_dir / "bad_frames.dcm")

            proc, logger = self._run_processor(in_dir, out_dir, _default_config())
            self.assertEqual(proc.success_count, 0)
            self.assertGreaterEqual(proc.error_count, 1)
            self.assertTrue(
                any(
                    tag == "error" and ("Truncated uncompressed PixelData" in msg or "expected 5" in msg)
                    for tag, msg in logger.records
                ),
                f"Expected frame count mismatch error in logs: {logger.records}",
            )

    def test_adaptive_chunking_and_worker_cap_bounds(self):
        self.assertEqual(_compute_adaptive_chunk_size(1), 1)
        self.assertEqual(_compute_adaptive_chunk_size(3), 1)
        self.assertEqual(_compute_adaptive_chunk_size(6), 3)
        self.assertEqual(_compute_adaptive_chunk_size(15), 7)
        self.assertLessEqual(_compute_adaptive_chunk_size(500), 15)
        self.assertGreaterEqual(_compute_adaptive_chunk_size(500), 5)

        self.assertEqual(_compute_worker_count(3, cpu_count=16), 3)
        self.assertEqual(_compute_worker_count(20, cpu_count=16), 8)
        self.assertEqual(_compute_worker_count(5, cpu_count=1), 1)
        self.assertEqual(_compute_worker_count(5, cpu_count=4), 3)

    def test_phase_progress_and_single_series_log_across_batches(self):
        axial = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        study_uid = generate_uid()
        series_uid = generate_uid()

        with tempfile.TemporaryDirectory() as tmpdir:
            in_dir = Path(tmpdir) / "in"
            out_dir = Path(tmpdir) / "out"
            for idx in range(6):
                ds, _ = build_enhanced_mr_dataset(
                    [{"position": (0.0, 0.0, float(idx * 3)), "orientation": axial}],
                    study_uid=study_uid,
                    series_uid=series_uid,
                    series_number=901,
                    series_description="MULTI_CHUNK_SERIES",
                )
                ds.NumberOfFrames = 1
                ds.InstanceNumber = idx + 1
                ds.ImagePositionPatient = [0.0, 0.0, float(idx * 3)]
                ds.ImageOrientationPatient = list(axial)
                save_dataset(ds, in_dir / f"s_{idx:02d}.dcm")

            proc, logger = self._run_processor(in_dir, out_dir, _default_config())
            self.assertEqual(proc.success_count, 6)
            self.assertEqual(proc.error_count, 0)

            # Should emit header progress (25% range) before batch completion and end at 100%
            ratios = [cur / tot for cur, tot in logger.progress if tot > 0]
            self.assertTrue(ratios)
            self.assertTrue(any(0.0 < r <= 0.25 for r in ratios), f"Expected header progress updates in {logger.progress}")
            self.assertEqual(ratios[-1], 1.0)
            self.assertEqual(ratios, sorted(ratios))

            # 6 slices split into 2 batches (chunk_size=3), yet series summary should log once
            series_logs = [msg for tag, msg in logger.records if tag == "success" and "successfully optimized 6 slices" in msg]
            self.assertEqual(len(series_logs), 1, f"Expected single series summary log, got: {logger.records}")
            self.assertTrue(any("Reading DICOM headers" in msg for _, msg in logger.records))
            self.assertTrue(any("Starting optimization (2 batches" in msg for _, msg in logger.records))

            # Missing input_dir returns cleanly without UnboundLocalError
            proc_missing, _ = self._run_processor(Path(tmpdir) / "nonexistent", out_dir, _default_config())
            self.assertEqual(proc_missing.success_count, 0)


if __name__ == "__main__":
    unittest.main()
