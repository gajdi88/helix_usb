"""The setlist display in the UI.

Intended as a picker for browsing all 8 x 128 presets. It is populated and
shows which setlist the device is on, but is **deliberately left disabled**:
the device serves the preset-name list only once per connection, so a second
enumeration returns nothing. Offering a choice that cannot work would be
worse than not offering it. See BACKLOG.md.

The selection machinery is kept and tested so it works the moment
re-enumeration does.
"""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

NAMES = ['FACTORY 1', 'FACTORY 2', 'USER 1', 'USER 2',
         'Send1', 'ExtCab', 'USER 5', 'TEMPLATES']


class SetlistPickerTest(unittest.TestCase):
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
        cls.ui = helix_qt_ui

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, '_real_start'):
            cls.ui.HelixBridge.start = cls._real_start

    def setUp(self):
        self.window = self.ui.MainWindow()
        self.addCleanup(self.window.deleteLater)
        self.helix = self.window.bridge.helix
        self.requested = []
        self.window.bridge.request_preset_names = \
            lambda setlist=None: self.requested.append(setlist)

    def test_empty_until_names_arrive(self):
        self.assertFalse(self.window.setlist_picker.isEnabled())
        self.assertEqual(0, self.window.setlist_picker.count())

    def test_stays_disabled_because_re_enumeration_does_not_work(self):
        """Verified on hardware: a second enumeration returns nothing, for any
        setlist, even after a 40s wait. A control that cannot work should not
        look like it can."""
        self.helix.set_setlist_names(NAMES)
        self.assertFalse(self.window.setlist_picker.isEnabled())
        self.assertIn('once per connection', self.window.setlist_picker.toolTip())

    def test_lists_every_setlist_by_name_and_shown_number(self):
        self.helix.set_setlist_names(NAMES)
        picker = self.window.setlist_picker
        self.assertEqual(8, picker.count())
        self.assertEqual('1  FACTORY 1', picker.itemText(0))
        self.assertEqual('7  USER 5', picker.itemText(6))
        self.assertEqual([picker.itemData(i) for i in range(8)], list(range(8)))

    def test_opens_on_the_setlist_the_device_is_playing(self):
        self.helix.set_current_setlist(2)
        self.helix.set_setlist_names(NAMES)
        self.assertEqual(2, self.window.setlist_picker.currentIndex())
        self.assertIn('USER 1', self.window.preset_header.text())

    def test_populating_the_picker_does_not_request_anything(self):
        """Filling the combo must not look like a user choice."""
        self.helix.set_current_setlist(2)
        self.helix.set_setlist_names(NAMES)
        self.assertEqual([], self.requested)

    def test_choosing_a_setlist_would_re_enumerate_it(self):
        """Machinery test: the picker is disabled in the UI, so this drives
        the handler directly. It documents what happens once the device can
        serve a second enumeration."""
        self.helix.set_current_setlist(2)
        self.helix.set_setlist_names(NAMES)
        self.window.setlist_picker.setCurrentIndex(6)
        self.assertEqual([6], self.requested)

    def test_browsing_is_flagged_as_not_the_active_setlist(self):
        self.helix.set_current_setlist(2)
        self.helix.set_setlist_names(NAMES)
        self.window.setlist_picker.setCurrentIndex(6)
        header = self.window.preset_header.text()
        self.assertIn('USER 5', header)
        self.assertIn('not the active setlist', header)

    def test_returning_to_the_active_setlist_clears_the_flag(self):
        self.helix.set_current_setlist(2)
        self.helix.set_setlist_names(NAMES)
        self.window.setlist_picker.setCurrentIndex(6)
        self.window.setlist_picker.setCurrentIndex(2)
        self.assertNotIn('not the active setlist', self.window.preset_header.text())

    def test_browsing_sends_nothing_to_the_device(self):
        """Looking at a setlist must not change what is playing."""
        sent = []
        self.helix.endpoint_0x1_out = lambda *a, **k: sent.append(a)
        self.helix.set_current_setlist(2)
        self.helix.set_setlist_names(NAMES)
        self.window.setlist_picker.setCurrentIndex(4)
        self.assertEqual([], sent)


class BrowseSetlistOverrideTest(unittest.TestCase):
    """browse_setlist overrides the device's own, HELIX_SETLIST overrides both."""

    def setUp(self):
        from tests.replay import ReplayHelixUsb
        from modes.request_preset_names import RequestPresetNames
        self.helix = ReplayHelixUsb()
        self.mode = RequestPresetNames(self.helix)
        self._env = os.environ.pop('HELIX_SETLIST', None)

    def tearDown(self):
        if self._env is not None:
            os.environ['HELIX_SETLIST'] = self._env
        else:
            os.environ.pop('HELIX_SETLIST', None)

    def test_defaults_to_zero_when_nothing_is_known(self):
        self.assertEqual(0, self.mode._choose_setlist())

    def test_follows_the_device(self):
        self.helix.set_current_setlist(5)
        self.assertEqual(5, self.mode._choose_setlist())

    def test_browsing_wins_over_the_device(self):
        self.helix.set_current_setlist(5)
        self.helix.browse_setlist = 1
        self.assertEqual(1, self.mode._choose_setlist())

    def test_env_var_wins_over_everything(self):
        self.helix.set_current_setlist(5)
        self.helix.browse_setlist = 1
        os.environ['HELIX_SETLIST'] = '7'
        self.assertEqual(7, self.mode._choose_setlist())

    def test_bad_env_var_is_ignored(self):
        self.helix.set_current_setlist(5)
        os.environ['HELIX_SETLIST'] = 'nonsense'
        self.assertEqual(5, self.mode._choose_setlist())


if __name__ == '__main__':
    unittest.main()
