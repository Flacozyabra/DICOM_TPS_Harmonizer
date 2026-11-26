import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pydicom
from pydicom.uid import generate_uid

from src.core.config import ProcessingConfig
from src.core.converter import (
    ENHANCED_CONTAINER_TAGS_TUPLES,
    clean_and_build_dataset,
    clean_and_build_dataset_inplace,
    copy_geometry_and_rescale,
    extract_multiframe_frames,
    save_dicom_file,
)
from src.core.recovery import safe_dcmread
from src.utils.helpers import compute_slice_location, compute_slice_normal
from tests.helpers_dicom import CLASSIC_MR_SOP_CLASS, build_enhanced_mr_dataset, save_dataset


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


class ConverterTests(unittest.TestCase):
    def test_enhanced_container_tags_stripped_in_both_builders(self):
        frame_specs = [
            {
                "position": (0.0, 0.0, 0.0),
                "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                "stack_id": "1",
                "in_stack_position": 1,
            }
        ]
        src_ds, pixels = build_enhanced_mr_dataset(frame_specs, include_enhanced_container_tags=True)

        for clean_tags in (True, False):
            cfg = _default_config(clean_tags=clean_tags)
            built = clean_and_build_dataset(
                src_ds=src_ds,
                pixel_data=pixels[0],
                instance_number=1,
                study_uid=generate_uid(),
                series_uid=generate_uid(),
                sop_class=CLASSIC_MR_SOP_CLASS,
                for_uid=generate_uid(),
                config=cfg,
            )
            for tag_tuple in ENHANCED_CONTAINER_TAGS_TUPLES:
                self.assertNotIn(tag_tuple, built, f"Tag {tag_tuple} remained when clean_tags={clean_tags}")
            if clean_tags:
                self.assertFalse(any(t.is_private for t in built.keys()))
            else:
                self.assertTrue(any(t.is_private for t in built.keys()))

        # Test in-place builder strips Enhanced tags on single-frame conversion
        src_single, _ = build_enhanced_mr_dataset(frame_specs, include_enhanced_container_tags=True)
        src_single.NumberOfFrames = 1
        inplace_ds = clean_and_build_dataset_inplace(
            src_ds=src_single,
            instance_number=1,
            study_uid=generate_uid(),
            series_uid=generate_uid(),
            sop_class=CLASSIC_MR_SOP_CLASS,
            for_uid=generate_uid(),
            config=_default_config(clean_tags=False),
        )
        for tag_tuple in ENHANCED_CONTAINER_TAGS_TUPLES:
            self.assertNotIn(tag_tuple, inplace_ds)

    def test_unsplit_multiframe_inplace_preserves_container_tags(self):
        frame_specs = [
            {"position": (0.0, 0.0, 0.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)},
            {"position": (0.0, 0.0, 2.5), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)},
        ]
        src_ds, _ = build_enhanced_mr_dataset(frame_specs, include_enhanced_container_tags=True)
        inplace_ds = clean_and_build_dataset_inplace(
            src_ds=src_ds,
            instance_number=1,
            study_uid=generate_uid(),
            series_uid=generate_uid(),
            sop_class=CLASSIC_MR_SOP_CLASS,
            for_uid=generate_uid(),
            config=_default_config(split_multiframe=False, clean_tags=False),
        )
        self.assertIn((0x0020, 0x9221), inplace_ds)
        self.assertIn((0x0008, 0x9205), inplace_ds)

    def test_extract_multiframe_frames_and_ignore_gradient_directions(self):
        frame_specs = [
            {
                "position": (0.0, 0.0, 10.0),
                "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                "stack_id": "1",
                "in_stack_position": 2,
                "temporal_index": 1,
                "echo_number": 1,
                "b_value": 1000.0,
                "gradient_dir": (1.0, 0.0, 0.0),
                "frame_type": ("ORIGINAL", "PRIMARY", "DIFFUSION", "NONE"),
                "dimension_values": (1, 1, 1),
            },
            {
                "position": (0.0, 0.0, 5.0),
                "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                "stack_id": "1",
                "in_stack_position": 1,
                "temporal_index": 1,
                "echo_number": 1,
                "b_value": 1000.0,
                "gradient_dir": (0.0, 1.0, 0.0),
                "frame_type": ("ORIGINAL", "PRIMARY", "DIFFUSION", "NONE"),
                "dimension_values": (1, 1, 2),
            },
        ]
        src_ds, _ = build_enhanced_mr_dataset(
            frame_specs,
            dimension_pointers=((0x0020, 0x9056), (0x0018, 0x9087), (0x0018, 0x9089)),
        )
        frames, warnings = extract_multiframe_frames(src_ds)
        self.assertEqual(len(frames), 2)
        self.assertEqual(warnings, [])
        self.assertEqual(frames[0].b_value, 1000.0)
        self.assertEqual(frames[0].extra_dimensions, ())
        self.assertEqual(frames[0].group_key(), frames[1].group_key())
        self.assertAlmostEqual(frames[0].slice_location, 10.0, places=4)
        self.assertAlmostEqual(frames[1].slice_location, 5.0, places=4)

    def test_normal_normalization_and_degenerate_orientation(self):
        # Non-unit cosines should still yield normalized (0, 0, 1)
        normal = compute_slice_normal((2.0, 0.0, 0.0, 0.0, 3.0, 0.0))
        self.assertEqual(normal, (0.0, 0.0, 1.0))
        loc = compute_slice_location((1.0, 2.0, 12.5), (2.0, 0.0, 0.0, 0.0, 3.0, 0.0))
        self.assertAlmostEqual(loc, 12.5, places=4)

        # Degenerate (parallel) cosines should safely return None
        self.assertIsNone(compute_slice_normal((1.0, 0.0, 0.0, 1.0, 0.0, 0.0)))
        self.assertIsNone(compute_slice_location((0.0, 0.0, 10.0), (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)))

        # copy_geometry_and_rescale should fallback cleanly without ZeroDivisionError
        src_ds, pixels = build_enhanced_mr_dataset(
            [{"position": (0.0, 0.0, 10.0), "orientation": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)}]
        )
        out_ds = clean_and_build_dataset(
            src_ds, pixels[0], 1, generate_uid(), generate_uid(), CLASSIC_MR_SOP_CLASS, generate_uid(), _default_config()
        )
        copy_geometry_and_rescale(
            src_ds,
            out_ds,
            src_ds.PerFrameFunctionalGroupsSequence[0],
            src_ds.SharedFunctionalGroupsSequence[0],
            is_multiframe=True,
            frame_idx=3,
        )
        self.assertEqual(float(out_ds.SliceLocation), 3.0)

    def test_reconstructs_missing_image_position_patient_with_warning(self):
        # Trailing missing positions (anchor at frame 0)
        frame_specs = [
            {"position": (0.0, 0.0, 10.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), "spacing_between": 2.5},
            {"position": None, "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), "spacing_between": 2.5},
            {"position": None, "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), "spacing_between": 2.5},
        ]
        ds, _ = build_enhanced_mr_dataset(frame_specs)
        frames, warnings = extract_multiframe_frames(ds)
        self.assertEqual(warnings, [("reconstructed_ipp", 2)])
        self.assertEqual(frames[1].position, (0.0, 0.0, 12.5))
        self.assertEqual(frames[2].position, (0.0, 0.0, 15.0))
        self.assertAlmostEqual(frames[2].slice_location, 15.0, places=4)

        # Leading missing position (anchor at frame 1)
        frame_specs_lead = [
            {"position": None, "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), "spacing_between": 2.5},
            {"position": (0.0, 0.0, 15.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), "spacing_between": 2.5},
        ]
        ds_lead, _ = build_enhanced_mr_dataset(frame_specs_lead)
        frames_lead, warnings_lead = extract_multiframe_frames(ds_lead)
        self.assertEqual(warnings_lead, [("reconstructed_ipp", 1)])
        self.assertEqual(frames_lead[0].position, (0.0, 0.0, 12.5))

    def test_bit_depth_12_in_16_preserved_and_8_upgraded_to_16(self):
        ds12, px12 = build_enhanced_mr_dataset(
            [{"position": (0.0, 0.0, 0.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)}],
            bits_allocated=16,
            bits_stored=12,
            high_bit=11,
        )
        out12 = clean_and_build_dataset(
            ds12, px12[0], 1, generate_uid(), generate_uid(), CLASSIC_MR_SOP_CLASS, generate_uid(), _default_config()
        )
        self.assertEqual(int(out12.BitsAllocated), 16)
        self.assertEqual(int(out12.BitsStored), 12)
        self.assertEqual(int(out12.HighBit), 11)
        np.testing.assert_array_equal(np.frombuffer(out12.PixelData, dtype=np.uint16).reshape(16, 16), px12[0])

        ds8, px8 = build_enhanced_mr_dataset(
            [{"position": (0.0, 0.0, 0.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)}],
            bits_allocated=8,
            bits_stored=8,
            high_bit=7,
        )
        out8 = clean_and_build_dataset(
            ds8, px8[0], 1, generate_uid(), generate_uid(), CLASSIC_MR_SOP_CLASS, generate_uid(), _default_config()
        )
        self.assertEqual(int(out8.BitsAllocated), 16)
        self.assertEqual(int(out8.BitsStored), 16)
        self.assertEqual(int(out8.HighBit), 15)
        np.testing.assert_array_equal(
            np.frombuffer(out8.PixelData, dtype=np.uint16).reshape(16, 16), px8[0].astype(np.uint16)
        )

    def test_siemens_eof_fix_recovers_truncated_delimiter(self):
        frame_specs = [
            {"position": (0.0, 0.0, 0.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)},
        ]
        ds, pixels = build_enhanced_mr_dataset(frame_specs)
        ds.NumberOfFrames = 1
        ds.compress(pydicom.uid.RLELossless)
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_path = Path(tmpdir) / "orig.dcm"
            save_dataset(ds, orig_path)
            raw = orig_path.read_bytes()
            self.assertTrue(raw.endswith(b"\xfe\xff\xdd\xe0\x00\x00\x00\x00"))

            # Strip trailing 8-byte sequence delimiter (Siemens EOF truncation)
            trunc_path = Path(tmpdir) / "trunc.dcm"
            trunc_path.write_bytes(raw[:-8])

            recovered = safe_dcmread(trunc_path, stop_before_pixels=False)
            self.assertEqual(int(recovered.Rows), 16)
            self.assertEqual(int(recovered.Columns), 16)
            np.testing.assert_array_equal(recovered.pixel_array, pixels[0])

    def test_cyrillic_upgrades_charset_to_utf8_and_ascii_keeps_latin1(self):
        frame_specs = [
            {"position": (0.0, 0.0, 0.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)},
        ]
        ds_cyr, px_cyr = build_enhanced_mr_dataset(
            frame_specs,
            patient_name="Иванов^Иван",
            series_description="Т2_аксиал",
        )
        ds_cyr.SpecificCharacterSet = "ISO_IR 100"
        cfg = _default_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            out_mf = Path(tmpdir) / "cyr_mf.dcm"
            built = clean_and_build_dataset(
                ds_cyr, px_cyr[0], 1, generate_uid(), generate_uid(), CLASSIC_MR_SOP_CLASS, generate_uid(), cfg
            )
            save_dicom_file(out_mf, built, explicit_vr=True)
            reloaded = pydicom.dcmread(str(out_mf))
            self.assertEqual(reloaded.SpecificCharacterSet, "ISO_IR 192")
            self.assertEqual(str(reloaded.PatientName), "Иванов^Иван")
            self.assertEqual(str(reloaded.SeriesDescription), "Т2_аксиал")

            # ASCII dataset must normalize even ISO_IR 192 back to ISO_IR 100 for Monaco SCP compatibility
            ds_asc, px_asc = build_enhanced_mr_dataset(frame_specs, patient_name="Doe^John", series_description="T2_AX")
            ds_asc.SpecificCharacterSet = "ISO_IR 192"
            out_asc = Path(tmpdir) / "asc.dcm"
            built_asc = clean_and_build_dataset(
                ds_asc, px_asc[0], 1, generate_uid(), generate_uid(), CLASSIC_MR_SOP_CLASS, generate_uid(), cfg
            )
            save_dicom_file(out_asc, built_asc, explicit_vr=True)
            reloaded_asc = pydicom.dcmread(str(out_asc))
            self.assertEqual(reloaded_asc.SpecificCharacterSet, "ISO_IR 100")

    def test_spatial_and_timestamp_dimension_pointers_do_not_split_3d_series(self):
        axial = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        frame_specs = [
            {
                "position": (0.0, 0.0, 0.0),
                "orientation": axial,
                "stack_id": "1",
                "in_stack_position": 1,
                "dimension_values": (1, 1, 1),
            },
            {
                "position": (0.0, 0.0, 2.5),
                "orientation": axial,
                "stack_id": "1",
                "in_stack_position": 2,
                "dimension_values": (2, 2, 2),
            },
        ]
        # Siemens/GE may index ImagePositionPatient (0020,0032), InstanceNumber (0020,0013),
        # or FrameAcquisitionDateTime (0018,9074) inside DimensionIndexSequence
        ds, _ = build_enhanced_mr_dataset(
            frame_specs,
            dimension_pointers=((0x0020, 0x0032), (0x0020, 0x0013), (0x0018, 0x9074)),
        )
        frames, _ = extract_multiframe_frames(ds)
        self.assertEqual(frames[0].extra_dimensions, ())
        self.assertEqual(frames[1].extra_dimensions, ())
        self.assertEqual(frames[0].group_key(), frames[1].group_key())

    def test_rgb_8bit_image_preserves_8bit_and_pixels(self):
        ds, _ = build_enhanced_mr_dataset(
            [{"position": (0.0, 0.0, 0.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)}],
            bits_allocated=8,
            bits_stored=8,
            high_bit=7,
        )
        rgb = np.arange(16 * 16 * 3, dtype=np.uint8).reshape(16, 16, 3)
        ds.NumberOfFrames = 1
        ds.Modality = "US"
        ds.SamplesPerPixel = 3
        ds.PhotometricInterpretation = "RGB"
        ds.PlanarConfiguration = 0
        ds.PixelData = rgb.tobytes()
        ds["PixelData"].VR = "OB"

        cfg = _default_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "rgb.dcm"
            built = clean_and_build_dataset(
                ds, rgb, 1, generate_uid(), generate_uid(), "1.2.840.10008.5.1.4.1.1.6.1", generate_uid(), cfg
            )
            save_dicom_file(out_path, built, explicit_vr=True)
            reloaded = pydicom.dcmread(str(out_path))
            self.assertEqual(int(reloaded.BitsAllocated), 8)
            self.assertEqual(int(reloaded.SamplesPerPixel), 3)
            np.testing.assert_array_equal(reloaded.pixel_array, rgb)

            # Also verify in-place path preserves 8-bit RGB
            out_inplace = Path(tmpdir) / "rgb_inplace.dcm"
            inplace_ds = clean_and_build_dataset_inplace(
                ds, 1, generate_uid(), generate_uid(), "1.2.840.10008.5.1.4.1.1.6.1", generate_uid(), cfg
            )
            save_dicom_file(out_inplace, inplace_ds, explicit_vr=True)
            reloaded_in = pydicom.dcmread(str(out_inplace))
            self.assertEqual(int(reloaded_in.BitsAllocated), 8)
            np.testing.assert_array_equal(reloaded_in.pixel_array, rgb)

    def test_ct_table_angles_are_forced_to_zero_for_monaco(self):
        ds, px = build_enhanced_mr_dataset(
            [{"position": (0.0, 0.0, 0.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)}]
        )
        ds.Modality = "CT"
        ds.PatientSupportAngle = 15.0
        ds.TableTopPitchAngle = 2.0
        ds.TableTopRollAngle = -1.0
        out = clean_and_build_dataset(
            ds, px[0], 1, generate_uid(), generate_uid(), "1.2.840.10008.5.1.4.1.1.2", generate_uid(), _default_config()
        )
        self.assertEqual(float(out.PatientSupportAngle), 0.0)
        self.assertEqual(float(out.TableTopPitchAngle), 0.0)
        self.assertEqual(float(out.TableTopRollAngle), 0.0)

    def test_safe_dcmread_rejects_truncated_uncompressed_pixels(self):
        ds, _ = build_enhanced_mr_dataset(
            [{"position": (0.0, 0.0, 0.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)}]
        )
        ds.NumberOfFrames = 1
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = Path(tmpdir) / "orig.dcm"
            save_dataset(ds, orig)
            raw = orig.read_bytes()
            trunc = Path(tmpdir) / "trunc_uncomp.dcm"
            trunc.write_bytes(raw[:-20])
            with self.assertRaises(ValueError):
                safe_dcmread(trunc, stop_before_pixels=False)

            # Uncompressed datasets must not invoke Dataset.decompress() (avoids pydicom 2.4 NotImplementedError)
            with mock.patch("pydicom.dataset.Dataset.decompress", side_effect=NotImplementedError("not compressed")) as m_dec:
                ok_ds = safe_dcmread(orig, stop_before_pixels=False)
                m_dec.assert_not_called()
                self.assertEqual(int(ok_ds.Rows), 16)


if __name__ == "__main__":
    unittest.main()
