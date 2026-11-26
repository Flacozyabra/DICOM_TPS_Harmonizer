import hashlib
import json
import os
import ssl
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.utils.qt_compat import init_qt_backend

init_qt_backend()

from PyQt6.QtWidgets import QApplication, QWidget

from src.gui.app import (
    DEFAULT_CHECKBOX_SETTINGS,
    DicomSplitterApp,
    load_checkbox_settings,
    save_user_config,
)
from src.gui.widgets import DicomViewerPanel, HUVerticalSlider
from src.utils.updater import _open_url_with_tls_fallback, verify_file_sha256
from tests.helpers_dicom import build_enhanced_mr_dataset


class GuiAndUpdaterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_unused_threads_module_removed(self):
        threads_path = Path(__file__).resolve().parents[1] / "src" / "gui" / "threads.py"
        self.assertFalse(threads_path.exists())

    def test_checkbox_settings_persist_and_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "config.json"

            # Missing config returns all defaults True
            self.assertEqual(load_checkbox_settings(cfg_path), DEFAULT_CHECKBOX_SETTINGS)

            custom_settings = dict(DEFAULT_CHECKBOX_SETTINGS)
            custom_settings["new_uids"] = False
            custom_settings["explicit_vr"] = False
            custom_settings["exclude_localizers"] = False
            save_user_config(cfg_path, {"processing_settings": custom_settings, "theme": "cyber"})

            loaded = load_checkbox_settings(cfg_path)
            self.assertFalse(loaded["new_uids"])
            self.assertFalse(loaded["explicit_vr"])
            self.assertFalse(loaded["exclude_localizers"])
            self.assertTrue(loaded["split_multiframe"])

            # Corrupt JSON falls back cleanly to defaults
            cfg_path.write_text("{not valid json", encoding="utf-8")
            self.assertEqual(load_checkbox_settings(cfg_path), DEFAULT_CHECKBOX_SETTINGS)

    def test_viewer_preserves_frame_idx_zero_width_and_slider_bounds(self):
        class _DummyParent(QWidget):
            project_root = Path(__file__).resolve().parents[1]

            def loc(self, key, *args):
                return key

        dummy = _DummyParent()
        panel = DicomViewerPanel(dummy)
        ds, _ = build_enhanced_mr_dataset(
            [
                {"position": (0.0, 0.0, 0.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)},
                {"position": (0.0, 0.0, 5.0), "orientation": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)},
            ]
        )
        panel.sorted_files = [("dummy.dcm", 0), ("dummy.dcm", 1)]
        panel.current_index = 1
        panel.viewer.current_dataset = ds
        panel.window_width = 0.0  # must not raise ZeroDivisionError
        panel.window_center = 100.0

        with mock.patch.object(panel, "dicom_to_pixmap", wraps=panel.dicom_to_pixmap) as spy:
            panel.update_current_slice_pixels()
            spy.assert_called_once()
            self.assertEqual(spy.call_args[0][3], 1)

        pix = panel.dicom_to_pixmap(ds, 0.0, 100.0, frame_idx=1)
        self.assertIsNotNone(pix)

        slider = HUVerticalSlider()
        slider.set_range(-1000.0, 6000.0)
        slider.set_values(500.0, 5500.0)
        self.assertEqual(slider.upper_val, 5500.0)

    def test_app_persists_checkbox_toggle_to_config_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "config.json"
            with mock.patch.object(DicomSplitterApp, "get_config_path", return_value=cfg_path), \
                 mock.patch.object(DicomSplitterApp, "check_updates", return_value=None):
                win = DicomSplitterApp()
                self.assertTrue(win.cb_new_uids.isChecked())
                win.cb_new_uids.setChecked(False)
                win.cb_split_series.setChecked(False)

                saved = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertFalse(saved["processing_settings"]["new_uids"])
                self.assertFalse(saved["processing_settings"]["split_series"])
                self.assertTrue(saved["processing_settings"]["split_multiframe"])
                win.close()

    def test_progress_bar_indeterminate_until_positive_progress(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "config.json"
            with mock.patch.object(DicomSplitterApp, "get_config_path", return_value=cfg_path), \
                 mock.patch.object(DicomSplitterApp, "check_updates", return_value=None):
                win = DicomSplitterApp()
                win.is_processing = True
                win._set_start_button_mode(True)
                win.progress_bar.setRange(0, 0)

                self.assertEqual(win.start_btn.objectName(), "stopBtn")
                self.assertEqual(win.progress_bar.minimum(), 0)
                self.assertEqual(win.progress_bar.maximum(), 0)

                # Zero progress keeps indeterminate marquee active while running
                win.update_progress(0, 40)
                self.assertEqual(win.progress_bar.maximum(), 0)

                # First positive update switches to deterministic percentage mode
                win.update_progress(10, 40)
                self.assertEqual(win.progress_bar.minimum(), 0)
                self.assertEqual(win.progress_bar.maximum(), 100)
                self.assertEqual(win.progress_bar.value(), 25)

                # Early abort while still indeterminate resets bar back to 0..100
                win.progress_bar.setRange(0, 0)
                win.on_processing_finished()
                self.assertFalse(win.is_processing)
                self.assertEqual(win.start_btn.objectName(), "startBtn")
                self.assertEqual(win.progress_bar.minimum(), 0)
                self.assertEqual(win.progress_bar.maximum(), 100)
                self.assertEqual(win.progress_bar.value(), 0)
                win.close()

    def test_updater_sha256_and_tls_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sample = Path(tmpdir) / "update.tmp"
            payload = b"test binary payload"
            sample.write_bytes(payload)
            good_hash = hashlib.sha256(payload).hexdigest()
            self.assertTrue(verify_file_sha256(str(sample), good_hash))
            self.assertFalse(verify_file_sha256(str(sample), "0" * 64))

        req = mock.MagicMock()
        ok_resp = mock.MagicMock()

        # Falls back to CERT_NONE only when strict TLS raises SSLError
        with mock.patch("urllib.request.urlopen", side_effect=[ssl.SSLError("self signed"), ok_resp]) as m_open:
            resp = _open_url_with_tls_fallback(req, timeout=5)
            self.assertIs(resp, ok_resp)
            self.assertEqual(m_open.call_count, 2)
            self.assertIn("context", m_open.call_args_list[1][1])

        # Non-SSL URLError must propagate without disabling TLS verification
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("DNS error")) as m_open:
            with self.assertRaises(urllib.error.URLError):
                _open_url_with_tls_fallback(req, timeout=5)
            self.assertEqual(m_open.call_count, 1)


if __name__ == "__main__":
    unittest.main()
