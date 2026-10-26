import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('validator', Path(__file__).with_name('validate_dialogue.py'))
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


def choice(target=None, requires=None, effects=None):
    result = {'text': 'Pick', 'next': target}
    if requires is not None:
        result['requires_flags'] = requires
    if effects is not None:
        result['set_flag'] = effects
    return result


class ValidatorTests(unittest.TestCase):
    def check(self, *graphs, external=None, limit=v.MAX_STATES):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for i, graph in enumerate(graphs):
                path = Path(folder) / f'{i}.json'
                path.write_text(json.dumps(graph))
                paths.append(path)
            return v.validate_paths(paths, external, limit)

    def test_legacy_and_explicit_terminal_choice(self):
        self.assertEqual(self.check({'start': {'choices': [choice()]}}), ([], []))

    def test_missing_prerequisite_even_when_false(self):
        errors, _ = self.check({'start': {'choices': [choice(requires={'typo': False}), choice()]}})
        self.assertTrue(any("missing prerequisite flag 'typo'" in e for e in errors))

    def test_node_effect_before_condition(self):
        errors, _ = self.check({'start': {'set_flag': {'key': True}, 'choices': [choice(requires={'key': True})]}})
        self.assertEqual(errors, [])

    def test_choice_cannot_unlock_itself(self):
        errors, _ = self.check({'start': {'choices': [choice('secret', {'key': True}, {'key': True}), choice()]}, 'secret': {'next': None}})
        self.assertTrue(any('prerequisites can never' in e for e in errors))
        self.assertTrue(any('secret: unreachable once' in e for e in errors))

    def test_cross_file_persistence(self):
        errors, _ = self.check(
            {'logbook': {'next': None, 'set_flag': {'key': True}}},
            {'radio': {'choices': [choice('secret', {'key': True}), choice()]}, 'secret': {'next': None}})
        self.assertEqual(errors, [])

    def test_repeated_entry_accumulates_flags(self):
        errors, _ = self.check({'start': {'choices': [choice(effects={'a': True}), choice(effects={'b': True}), choice('secret', {'a': True, 'b': True})]}, 'secret': {'next': None}})
        self.assertEqual(errors, [])

    def test_mutually_exclusive_branches_do_not_merge_flags(self):
        errors, _ = self.check({
            'start': {'set_flag': {'a': False, 'b': False}, 'choices': [choice('merge', effects={'a': True}), choice('merge', effects={'b': True})]},
            'merge': {'choices': [choice('secret', {'a': True, 'b': True}), choice()]},
            'secret': {'next': None},
        })
        self.assertTrue(any('secret: unreachable once' in e for e in errors))

    def test_absent_false_and_nonboolean_values(self):
        errors, _ = self.check({'start': {'choices': [choice('set', {'key': False})]}, 'set': {'set_flag': {'key': 1}, 'choices': [choice('end', {'key': True}), choice()]}, 'end': {'next': None}})
        self.assertTrue(any('end: unreachable once' in e for e in errors))
        self.assertFalse(any('start:choice' in e for e in errors))

    def test_reachable_all_hidden_state(self):
        errors, _ = self.check({'start': {'choices': [choice('gate'), choice('gate', effects={'key': True})]}, 'gate': {'choices': [choice(requires={'key': True})]}})
        self.assertTrue(any('gate: reachable flag state has no eligible choices' in e for e in errors))

    def test_dead_end_cycle_despite_other_ending(self):
        errors, _ = self.check({'start': {'choices': [choice('loop'), choice()]}, 'loop': {'next': 'loop'}})
        self.assertTrue(any('loop: reachable flag state has no path to an ending' in e for e in errors))

    def test_cycle_with_exit_is_valid(self):
        self.assertEqual(self.check({'start': {'choices': [choice('start'), choice()]}}), ([], []))

    def test_explicit_external_producer(self):
        graph = {'start': {'choices': [choice('end', {'lamp_relit': True}), choice()]}, 'end': {'next': None}}
        self.assertEqual(self.check(graph, external={'lamp_relit': (False, True)}), ([], []))

    def test_orphan_and_journal_entry(self):
        errors, warnings = self.check({'entry_log': {'next': None}, 'orphan': {'next': None}})
        self.assertEqual(errors, [])
        self.assertTrue(any('orphan' in w for w in warnings))

    def test_schema_rejections_do_not_crash(self):
        bad = [[], {}, {'start': 3}, {'start': {'next': 42}}, {'start': {'choices': [3]}}, {'start': {'choices': [{'text': 'x'}]}}, {'start': {'choices': [choice(requires={'x': 1})]}}, {'start': {'choices': []}}, {'start': {'next': None, 'set_flag': []}}, {'start': {'next': None, 'requires_flags': {}}}]
        for graph in bad:
            with self.subTest(graph=graph):
                self.assertTrue(self.check(graph)[0])

    def test_no_entry_fails_instead_of_skipping_conditions(self):
        self.assertTrue(any('no known entry' in e for e in self.check({'unknown': {'next': None}})[0]))

    def test_state_limit_fails_closed(self):
        self.assertTrue(any('analysis incomplete' in e for e in self.check({'start': {'next': 'end'}, 'end': {'next': None}}, limit=1)[0]))

    def test_no_argument_main_and_invalid_json(self):
        old_root, old_dir = v.ROOT, v.DIALOGUE_DIR
        with tempfile.TemporaryDirectory() as folder:
            v.ROOT = Path(folder)
            v.DIALOGUE_DIR = Path(folder) / 'data' / 'dialogue'
            v.DIALOGUE_DIR.mkdir(parents=True)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(v.main(), 1)
                    path = v.DIALOGUE_DIR / 'sample.json'
                    path.write_text('{broken')
                    self.assertEqual(v.main(), 1)
                    path.write_text(json.dumps({'start': {'next': None}}))
                    self.assertEqual(v.main(), 0)
            finally:
                v.ROOT, v.DIALOGUE_DIR = old_root, old_dir


if __name__ == '__main__':
    unittest.main()
