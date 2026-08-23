"""Module ids added for the Helix LT.

The catalogue shipped with upstream is HX Stomp-era and lacks blocks the LT
has. Seven ids appeared in the captures as "NOT FOUND IN MODULES"; the
operator read each one off the device on 2026-08-23, one slot at a time, each
anchored against a known neighbouring block so a wrong preset would have been
obvious.
"""
import unittest

from modules import modules
from tests.replay import preset_fixture_paths, replay_preset_data

ADDED = {
    'cd0291': ('Reverb', 'Dynamic Room'),
    'cd027c': ('Reverb', 'Dynamic Plate'),
    'cd02c9': ('Reverb', 'Dynamic Ambience'),
    'cd02bb': ('Cab', '1x12 Grammatico'),
    'cd02cd': ('Cab', '1x10 US Princess'),
    'cd02b8': ('Cab', '4x12 Uber T75'),
    'cd02c4': ('Impulse Response', 'Impulse Response'),
}


class AddedModulesTest(unittest.TestCase):
    def test_all_seven_are_present(self):
        for module_id, (category, name) in ADDED.items():
            with self.subTest(module_id=module_id):
                self.assertIn(module_id, modules)
                self.assertEqual(category, modules[module_id][0])
                self.assertIn(name, modules[module_id][1])

    def test_no_id_was_redefined(self):
        """The additions must not have shadowed an existing entry."""
        text = open('modules.py', encoding='utf-8').read()
        for module_id in ADDED:
            with self.subTest(module_id=module_id):
                self.assertEqual(1, text.count("'%s':" % module_id))

    def test_catalogue_has_no_duplicate_keys(self):
        import re
        text = open('modules.py', encoding='utf-8').read()
        keys = re.findall(r"^\s*'([0-9a-f]+)':", text, re.M)
        dupes = {k for k in keys if keys.count(k) > 1}
        self.assertEqual(set(), dupes)


class NoUnresolvedModulesTest(unittest.TestCase):
    def test_every_captured_block_resolves(self):
        """The point of the exercise: nothing renders as ?cd....

        If a future capture introduces a new unknown id this fails, which is
        the intended signal to go and read it off the device rather than let
        the UI show a hex code.
        """
        unresolved = []
        for path in preset_fixture_paths():
            layout = replay_preset_data(path).hx_preset.to_layout()
            for row in layout['rows']:
                for block in row['blocks']:
                    if block.get('unknown_id'):
                        unresolved.append((path, row['name'], block['position'],
                                           block['unknown_id']))
        self.assertEqual([], unresolved)


if __name__ == '__main__':
    unittest.main()
