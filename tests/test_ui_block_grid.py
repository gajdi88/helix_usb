"""The four-row block grid.

The UI used to draw the HX Stomp's single strip of eight and was fed by
HelixUsb.set_slot_info(), which nothing ever called - so it showed nothing at
all. The grid is four rows of eight fed by set_preset_layout(), and these
tests drive it only through HelixUsb, the way the device does.
"""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from tests.replay import replay_preset_data

FIXTURE = 'tests/fixtures/presets/sl2_preset024.jsonl'


class BlockGridTest(unittest.TestCase):
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
        cls.layout = replay_preset_data(FIXTURE).hx_preset.to_layout()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, '_real_start'):
            cls.ui.HelixBridge.start = cls._real_start

    def setUp(self):
        self.window = self.ui.MainWindow()
        self.addCleanup(self.window.deleteLater)

    def _text(self, row, position):
        return self.window._block_buttons[(row, position)].text()

    def test_grid_is_four_rows_of_eight(self):
        self.assertEqual(32, len(self.window._block_buttons))
        for row in range(4):
            for position in range(1, 9):
                self.assertIn((row, position), self.window._block_buttons)

    def test_rows_are_named_for_the_lt_not_the_stomp(self):
        self.assertEqual(('Path 1 upper', 'Path 1 lower', 'Path 2 upper', 'Path 2 lower'),
                         self.ui.BLOCK_ROW_NAMES)

    def test_empty_grid_before_any_preset(self):
        for key in self.window._block_buttons:
            self.assertEqual('-', self.window._block_buttons[key].text())

    def test_empty_slots_are_blank_after_a_preset_loads(self):
        """Empty slots should recede, not read as content."""
        self.window.bridge.helix.set_preset_layout(self.layout)
        self.assertEqual('', self._text(0, 3))
        self.assertEqual('', self._text(1, 8))

    def test_blocks_appear_in_the_right_row_and_position(self):
        self.window.bridge.helix.set_preset_layout(self.layout)
        # Straight from the operator's reading of this preset.
        self.assertTrue(self._text(0, 1).startswith('Red Squeeze'))
        self.assertEqual('', self._text(0, 3))
        self.assertTrue(self._text(1, 3).startswith('Cali Q'))
        self.assertTrue(self._text(3, 4).startswith('Room'))

    def test_bypassed_blocks_are_styled_differently(self):
        self.window.bridge.helix.set_preset_layout(self.layout)
        bypassed = self.window._block_buttons[(0, 6)]      # Tile, bypassed
        active = self.window._block_buttons[(0, 1)]        # Red Squeeze, on
        self.assertIn('dashed', bypassed.styleSheet())
        self.assertIn('italic', bypassed.styleSheet())
        self.assertNotIn('dashed', active.styleSheet())

    def test_tooltip_carries_the_full_name_the_button_truncates(self):
        self.window.bridge.helix.set_preset_layout(self.layout)
        btn = self.window._block_buttons[(0, 4)]
        self.assertIn('Brit Plexi Brt', btn.toolTip())
        self.assertIn('Amp', btn.toolTip())
        self.assertGreater(len(btn.toolTip()), len(btn.text()))

    def test_routing_is_summarised_per_row(self):
        self.window.bridge.helix.set_preset_layout(self.layout)
        labels = {r: self.window._row_routing_labels[r].text() for r in range(4)}
        self.assertIn('split @5', labels[1])          # Path 1 splits at 5
        self.assertIn('Path 2A', labels[1])           # and its lower chain feeds Path 2A
        self.assertIn('split @3', labels[3])          # Path 2 splits at 3
        self.assertIn('merge @5', labels[3])          # rejoining at 5
        self.assertIn('Multi output', labels[2])      # Path 2 upper is the final output

    def test_merge_at_the_output_reads_as_out(self):
        moved = 'tests/fixtures/presets/a2_routing_moved.jsonl'
        if not os.path.exists(moved):
            self.skipTest('A2 fixture missing')
        self.window.bridge.helix.set_preset_layout(
            replay_preset_data(moved).hx_preset.to_layout())
        self.assertIn('merge @out', self.window._row_routing_labels[1].text())

    def test_clicking_a_block_reports_it_without_touching_the_device(self):
        self.window.bridge.helix.set_preset_layout(self.layout)
        self.window._on_block_clicked(0, 6)
        text = self.window.block_info_slot.text()
        self.assertIn('Tile', text)
        self.assertIn('bypassed', text)
        self.assertTrue(self.window._block_buttons[(0, 6)].isChecked())
        self.assertFalse(self.window._block_buttons[(0, 1)].isChecked())

    def test_unknown_modules_are_shown_not_swallowed(self):
        """A slot whose module id is missing from modules.py stays visible.

        id_to_names() reports an unknown id as ["NOT FOUND IN MODULES <id>",
        ""] -- message in the category slot, no name. Rendered naively that
        made an occupied slot look empty. Uses a fabricated id, so the test
        keeps working now that every captured id resolves.
        """
        layout = {
            'rows': [{'name': name,
                      'blocks': [{'position': p, 'name': None, 'category': None,
                                  'bypassed': False, 'dual': False}
                                 for p in range(1, 9)]}
                     for name in self.ui.BLOCK_ROW_NAMES],
            'routing': [], 'snapshot_names': [],
        }
        layout['rows'][0]['blocks'][2].update(
            {'name': '?cdffff', 'category': 'Unknown', 'unknown_id': 'cdffff'})
        self.window.bridge.helix.set_preset_layout(layout)
        btn = self.window._block_buttons[(0, 3)]
        self.assertNotEqual('', btn.text())
        self.assertIn('cdffff', btn.text())
        self.assertIn('cdffff', btn.toolTip())

    def test_selection_sends_nothing(self):
        """The old strip called highlight_slot(), which writes to the device."""
        sent = []
        self.window.bridge.helix.endpoint_0x1_out = lambda *a, **k: sent.append(a)
        self.window.bridge.helix.set_preset_layout(self.layout)
        self.window._on_block_clicked(2, 8)
        self.assertEqual([], sent)


if __name__ == '__main__':
    unittest.main()


class SignalFlowTest(unittest.TestCase):
    """A row that carries signal has to look like it does.

    Feedback from using the GUI: with every row drawn identically it was
    impossible to tell where the sound actually goes. Path 1 upper always
    carries signal even when its slots are empty; a lower row only does if the
    path splits into it or an upstream path fans out to it.
    """

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

    def _live(self, row):
        links = self.window._row_connectors[row]
        self.assertTrue(links)
        return all(self.ui.MainWindow.LINK_LIVE == l.styleSheet() for l in links)

    def test_upper_rows_always_carry_signal(self):
        layout = replay_preset_data(FIXTURE).hx_preset.to_layout()
        self.window.bridge.helix.set_preset_layout(layout)
        self.assertTrue(self._live(0))
        self.assertTrue(self._live(2))

    def test_lower_row_is_live_only_when_the_path_splits(self):
        layout = replay_preset_data(FIXTURE).hx_preset.to_layout()
        self.window.bridge.helix.set_preset_layout(layout)
        # Preset 7A splits on both paths, so both lower rows carry signal.
        self.assertTrue(self._live(1))
        self.assertTrue(self._live(3))

    def test_unsplit_lower_rows_are_dead(self):
        serial = 'tests/fixtures/presets/sl2_preset036.jsonl'
        if not os.path.exists(serial):
            self.skipTest('serial fixture missing')
        self.window.bridge.helix.set_preset_layout(
            replay_preset_data(serial).hx_preset.to_layout())
        self.assertTrue(self._live(0))
        self.assertFalse(self._live(1))
        self.assertFalse(self._live(3))

    def test_a_row_fed_from_upstream_is_live_without_a_split(self):
        """The fan-out case: Path 2 has no split but is fed by Path 1."""
        fanout = 'tests/fixtures/presets/a2_routing_fanout.jsonl'
        if not os.path.exists(fanout):
            self.skipTest('fan-out fixture missing')
        layout = replay_preset_data(fanout).hx_preset.to_layout()
        self.window.bridge.helix.set_preset_layout(layout)
        p2 = next(r for r in layout['routing'] if r['path'] == 2)
        self.assertIsNone(p2['split_position'])
        self.assertTrue(self._live(3))

    def test_row_caption_dims_on_a_dead_row(self):
        serial = 'tests/fixtures/presets/sl2_preset036.jsonl'
        if not os.path.exists(serial):
            self.skipTest('serial fixture missing')
        self.window.bridge.helix.set_preset_layout(
            replay_preset_data(serial).hx_preset.to_layout())
        self.assertIn('#c8ccd2', self.window._row_captions[0].styleSheet())
        self.assertIn('#5a6068', self.window._row_captions[1].styleSheet())

    def test_block_font_is_small_enough_to_read(self):
        layout = replay_preset_data(FIXTURE).hx_preset.to_layout()
        self.window.bridge.helix.set_preset_layout(layout)
        style = self.window._block_buttons[(0, 1)].styleSheet()
        self.assertIn('font-size: 10px', style)
