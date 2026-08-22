"""The preset list must show every preset the device reported.

The UI kept its own PRESET_LIST_COUNT = 125 while the rest of the fork moved
to the Helix LT's 128, so presets 125-127 were parsed, stored, and then
silently dropped on the way to the list widget. These tests drive the real
QListWidget, not just the helper, because the defect was in the wiring.
"""
import os
import unittest

# Must be set before any QApplication exists.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from helix_usb import HelixUsb
from helix_qt_ui import normalize_preset_names

COUNT = HelixUsb.PRESET_LIST_COUNT


def _names(n):
    return ['Preset%d' % i for i in range(n)]


class NormalizePresetNamesTest(unittest.TestCase):
    def test_uses_the_device_preset_count(self):
        self.assertEqual(128, COUNT, 'a Helix/LT setlist holds 128 presets')

    def test_full_list_is_not_truncated(self):
        names = _names(COUNT)
        self.assertEqual(names, normalize_preset_names(names))

    def test_short_list_is_padded(self):
        out = normalize_preset_names(_names(3))
        self.assertEqual(COUNT, len(out))
        self.assertEqual('Preset2', out[2])
        self.assertEqual(HelixUsb.PRESET_PLACEHOLDER_NAME, out[3])

    def test_over_long_list_is_trimmed_and_warns(self):
        with self.assertLogs('helix_qt_ui', level='WARNING') as captured:
            out = normalize_preset_names(_names(COUNT + 5))
        self.assertEqual(COUNT, len(out))
        self.assertIn('longer than 128', captured.output[0])


class PresetListWidgetTest(unittest.TestCase):
    """Builds the real MainWindow offscreen, with the USB bridge stubbed out."""

    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            import helix_qt_ui
        except ImportError as e:
            raise unittest.SkipTest('Qt unavailable: %s' % e)

        cls.app = QApplication.instance() or QApplication([])
        # MainWindow.__init__ calls bridge.start(), which spins up the USB
        # monitor. A unit test must not go looking for hardware.
        cls._real_start = helix_qt_ui.HelixBridge.start
        helix_qt_ui.HelixBridge.start = lambda self: None
        cls.helix_qt_ui = helix_qt_ui

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, '_real_start'):
            cls.helix_qt_ui.HelixBridge.start = cls._real_start

    def setUp(self):
        self.window = self.helix_qt_ui.MainWindow()
        self.addCleanup(self.window.deleteLater)

    def test_all_presets_reach_the_list(self):
        names = _names(COUNT)
        names[127] = 'Voice'
        self.window._on_preset_names_changed(names)

        self.assertEqual(COUNT, self.window.preset_list.count())

    def test_last_preset_is_present_and_correctly_numbered(self):
        names = _names(COUNT)
        names[125], names[126], names[127] = 'OneTwoFive', 'OneTwoSix', 'Voice'
        self.window._on_preset_names_changed(names)

        last = self.window.preset_list.item(COUNT - 1)
        self.assertEqual('127: Voice', last.text())
        self.assertEqual(127, last.data(self.helix_qt_ui.Qt.ItemDataRole.UserRole))
        # The three the old code dropped.
        self.assertEqual('125: OneTwoFive', self.window.preset_list.item(125).text())
        self.assertEqual('126: OneTwoSix', self.window.preset_list.item(126).text())

    def test_every_row_carries_its_program_number(self):
        self.window._on_preset_names_changed(_names(COUNT))
        rows = [self.window.preset_list.item(i).data(self.helix_qt_ui.Qt.ItemDataRole.UserRole)
                for i in range(self.window.preset_list.count())]
        self.assertEqual(list(range(COUNT)), rows)


if __name__ == '__main__':
    unittest.main()
