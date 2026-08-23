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

    def test_blocks_appear_in_the_right_row_and_position(self):
        self.window.bridge.helix.set_preset_layout(self.layout)
        # Straight from the operator's reading of this preset.
        self.assertTrue(self._text(0, 1).startswith('Red Squeeze'))
        self.assertEqual('-', self._text(0, 3))
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
        """A slot whose module id is missing from modules.py is still occupied.

        id_to_names() reports an unknown id as ["NOT FOUND IN MODULES <id>",
        ""] -- message in the category slot, no name. Rendered naively that
        made an occupied slot look empty, hiding five real blocks across the
        fixtures.
        """
        other = 'tests/fixtures/presets/sl2_preset125.jsonl'
        if not os.path.exists(other):
            self.skipTest('fixture missing')
        layout = replay_preset_data(other).hx_preset.to_layout()
        self.window.bridge.helix.set_preset_layout(layout)
        btn = self.window._block_buttons[(0, 5)]
        self.assertNotEqual('-', btn.text())
        self.assertIn('cd02b8', btn.text())
        self.assertIn('cd02b8', btn.toolTip())

    def test_selection_sends_nothing(self):
        """The old strip called highlight_slot(), which writes to the device."""
        sent = []
        self.window.bridge.helix.endpoint_0x1_out = lambda *a, **k: sent.append(a)
        self.window.bridge.helix.set_preset_layout(self.layout)
        self.window._on_block_clicked(2, 8)
        self.assertEqual([], sent)


if __name__ == '__main__':
    unittest.main()
