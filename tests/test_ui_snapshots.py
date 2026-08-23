"""The snapshot row in the Qt UI.

Driven only through HelixUsb, the way the device drives it: set_snapshot() and
set_snapshot_names() fire callbacks, the bridge turns those into Qt signals,
and the pills follow. Nothing here calls the refresh directly, so a broken
signal connection fails the test rather than hiding behind a manual call.
"""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from helix_usb import HelixUsb

CUSTOM = ['lead', 'rhytm'] + ['SNAPSHOT %d' % i for i in range(3, 9)]


def _active(pill):
    return 'font-weight: bold' in pill.styleSheet()


class SnapshotRowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            import helix_qt_ui
        except ImportError as e:
            raise unittest.SkipTest('Qt unavailable: %s' % e)
        cls.app = QApplication.instance() or QApplication([])
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
        self.helix = self.window.bridge.helix

    def test_one_pill_per_snapshot(self):
        self.assertEqual(HelixUsb.SNAPSHOT_COUNT, len(self.window.snapshot_labels))

    def test_defaults_before_any_device_data(self):
        for idx, pill in enumerate(self.window.snapshot_labels, start=1):
            self.assertIn('SNAPSHOT %d' % idx, pill.text())

    def test_names_from_the_device_replace_defaults(self):
        self.helix.set_snapshot_names(CUSTOM)
        self.assertEqual('1. lead', self.window.snapshot_labels[0].text())
        self.assertEqual('2. rhytm', self.window.snapshot_labels[1].text())

    def test_active_snapshot_is_highlighted_and_others_are_not(self):
        self.helix.set_snapshot(3)
        pills = self.window.snapshot_labels
        self.assertTrue(_active(pills[2]))
        self.assertEqual([2], [i for i, p in enumerate(pills) if _active(p)])

    def test_highlight_moves_and_releases(self):
        self.helix.set_snapshot(3)
        self.helix.set_snapshot(7)
        pills = self.window.snapshot_labels
        self.assertTrue(_active(pills[6]))
        self.assertFalse(_active(pills[2]))

    def test_full_range_is_reachable(self):
        for n in range(1, HelixUsb.SNAPSHOT_COUNT + 1):
            self.helix.set_snapshot(n)
            self.assertTrue(_active(self.window.snapshot_labels[n - 1]),
                            'snapshot %d never highlighted' % n)

    def test_out_of_range_leaves_the_row_alone(self):
        self.helix.set_snapshot(4)
        self.helix.set_snapshot(99)
        self.assertEqual([3], [i for i, p in enumerate(self.window.snapshot_labels) if _active(p)])

    def test_short_name_list_does_not_break_the_row(self):
        # A parse that recovers fewer than eight names must not blank the row.
        self.helix.set_snapshot_names(['only one'])
        pills = self.window.snapshot_labels
        self.assertEqual('1. only one', pills[0].text())
        self.assertIn('SNAPSHOT 8', pills[7].text())

    def test_pills_are_not_interactive(self):
        # Selecting a snapshot would write device state; this row only reports.
        for pill in self.window.snapshot_labels:
            self.assertFalse(hasattr(pill, 'clicked'))


if __name__ == '__main__':
    unittest.main()
