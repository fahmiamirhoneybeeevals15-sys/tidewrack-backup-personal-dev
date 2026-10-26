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

    def test_unknown_prerequisite_even_when_false(self):
        errors, _ = self.check({'start': {'choices': [choice(requires={'typo': False}), choice()]}})
        self.assertTrue(any("unknown flag 'typo'" in e for e in errors))

    def test_exact_canonical_allowlist(self):
        self.assertEqual(v.ALLOWED_FLAGS, {'skeptic', 'believer', 'trusted_edith', 'radioed_tom'})
        for name in sorted(v.ALLOWED_FLAGS):
            graph = {'start': {'set_flag': {name: True}, 'choices': [choice(requires={name: True})]}}
            self.assertEqual(self.check(graph), ([], []))

    def test_unknown_setters_rejected_even_without_requirements(self):
        for graph in [
            {'start': {'next': None, 'set_flag': {'lamp_relit': True}}},
            {'start': {'choices': [choice(effects={'typo': True})]}},
            {'start': {'set_flag': {'typo': True}, 'choices': [choice(requires={'typo': True})]}},
        ]:
            self.assertTrue(any('unknown flag' in e for e in self.check(graph)[0]))

    def test_missing_producer_for_canonical_prerequisite(self):
        graph = {'start': {'choices': [choice(requires={'trusted_edith': True}), choice()]}}
        self.assertTrue(any("missing prerequisite flag 'trusted_edith'" in e for e in self.check(graph)[0]))

    def test_external_declaration_cannot_bypass_allowlist(self):
        errors, _ = self.check({'start': {'next': None}}, external={'lamp_relit': (False, True)})
        self.assertTrue(any('invalid external flag declaration' in e for e in errors))

    def test_node_effect_before_condition(self):
        errors, _ = self.check({'start': {'set_flag': {'trusted_edith': True}, 'choices': [choice(requires={'trusted_edith': True})]}})
        self.assertEqual(errors, [])

    def test_choice_cannot_unlock_itself(self):
        errors, _ = self.check({'start': {'choices': [choice('secret', {'trusted_edith': True}, {'trusted_edith': True}), choice()]}, 'secret': {'next': None}})
        self.assertTrue(any('prerequisites can never' in e for e in errors))
        self.assertTrue(any('secret: unreachable once' in e for e in errors))

    def test_cross_file_persistence(self):
        errors, _ = self.check(
            {'logbook': {'next': None, 'set_flag': {'trusted_edith': True}}},
            {'radio': {'choices': [choice('secret', {'trusted_edith': True}), choice()]}, 'secret': {'next': None}})
        self.assertEqual(errors, [])

    def test_repeated_entry_accumulates_flags(self):
        errors, _ = self.check({'start': {'choices': [choice(effects={'skeptic': True}), choice(effects={'believer': True}), choice('secret', {'skeptic': True, 'believer': True})]}, 'secret': {'next': None}})
        self.assertEqual(errors, [])

    def test_mutually_exclusive_branches_do_not_merge_flags(self):
        errors, _ = self.check({
            'start': {'set_flag': {'skeptic': False, 'believer': False}, 'choices': [choice('merge', effects={'skeptic': True}), choice('merge', effects={'believer': True})]},
            'merge': {'choices': [choice('secret', {'skeptic': True, 'believer': True}), choice()]},
            'secret': {'next': None},
        })
        self.assertTrue(any('secret: unreachable once' in e for e in errors))

    def test_absent_false_and_nonboolean_values(self):
        errors, _ = self.check({'start': {'choices': [choice('set', {'trusted_edith': False})]}, 'set': {'set_flag': {'trusted_edith': 1}, 'choices': [choice('end', {'trusted_edith': True}), choice()]}, 'end': {'next': None}})
        self.assertTrue(any('end: unreachable once' in e for e in errors))
        self.assertFalse(any('start:choice' in e for e in errors))

    def test_reachable_all_hidden_state(self):
        errors, _ = self.check({'start': {'choices': [choice('gate'), choice('gate', effects={'trusted_edith': True})]}, 'gate': {'choices': [choice(requires={'trusted_edith': True})]}})
        self.assertTrue(any('gate: reachable flag state has no eligible choices' in e for e in errors))

    def test_dead_end_cycle_despite_other_ending(self):
        errors, _ = self.check({'start': {'choices': [choice('loop'), choice()]}, 'loop': {'next': 'loop'}})
        self.assertTrue(any('loop: reachable flag state has no path to an ending' in e for e in errors))

    def test_cycle_with_exit_is_valid(self):
        self.assertEqual(self.check({'start': {'choices': [choice('start'), choice()]}}), ([], []))

    def test_explicit_external_producer(self):
        graph = {'start': {'choices': [choice('end', {'radioed_tom': True}), choice()]}, 'end': {'next': None}}
        self.assertEqual(self.check(graph, external={'radioed_tom': (False, True)}), ([], []))

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
