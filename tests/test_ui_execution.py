#!/usr/bin/env python3
"""Execute generated drivers with Node; verify runtime evidence and failure gates."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('doctest_engine', ROOT / 'doctest.py')
dt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dt)

FRAMEWORK = '''
import { appendFileSync } from 'node:fs';
const log = (event) => appendFileSync(process.env.CALLS, JSON.stringify(event) + '\\n');
let callback;
export function test(name, fn) { callback = fn; }
export async function run() {
  const state = { text: 'initial', enabled: true };
  const app = {
    click: async (target) => log(['click', target]),
    expectTexts: async (texts) => {
      log(['texts', texts]);
      if (process.env.INTERRUPT) process.exit(0);
      if (texts.join() !== 'Ready') throw new Error('text not found');
    },
    waitFor: async (fn) => { log(['wait']); await fn(); },
    screenshot: async () => {
      log(['screenshot']);
      return process.env.BAD_SCREENSHOT ? {} : { image: 'aW1hZ2U=' };
    },
    inspector: { send: async (command, args) => {
      log([command, args]);
      if (command === 'findByProperty') return { matches: [{ id: 1 }] };
      if (command === 'getProperties') return {
        properties: Object.entries(state).map(([name, value]) => ({name, value}))
      };
      if (command === 'setProperty') {
        if (process.env.RPC_ERROR) return { error: 'write rejected' };
        state[args.property] = args.value;
      }
      if (command === 'click' && process.env.RPC_ERROR) return { error: 'click rejected' };
      return {};
    }}
  };
  try { await callback(app); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
'''


@unittest.skipUnless(shutil.which('node'), 'Node is required to execute generated UI drivers')
class UIExecution(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        framework = self.root / 'test-framework'
        framework.mkdir()
        (framework / 'framework.mjs').write_text(FRAMEWORK)
        self.driver = self.root / 'test.mjs'
        self.trace = self.root / 'actions.json'
        self.calls = self.root / 'calls.jsonl'

    def execute(self, tests, **env):
        import os
        dt.generate_mjs_tests(tests, str(self.root), 'quoted "test"', str(self.driver),
                              images_dir=str(self.root), trace_path=str(self.trace))
        proc = subprocess.run(['node', str(self.driver)], capture_output=True, text=True,
                              env={**os.environ, 'CALLS': str(self.calls), **env})
        passed, note, actions = dt._ui_run_outcome(proc.returncode, tests, str(self.trace))
        return proc, passed, note, actions

    def test_all_supported_actions_really_execute_and_screenshot_completes(self):
        tests = [
            {'action': 'click', 'target': 'button "one"'},
            {'action': 'wait_for', 'texts': ['Ready'], 'name': 'Wait "here"'},
            {'action': 'expect_texts', 'texts': ['Ready']},
            {'action': 'set_text', 'find_by': 'objectName', 'find_value': 'field', 'value': 'new "text"'},
            {'action': 'set_property', 'find_value': 'field', 'property': 'enabled', 'value': False},
            {'action': 'expect_property', 'find_value': 'field', 'property': 'enabled', 'value': False},
            {'action': 'call_method', 'find_value': 'root', 'method': 'open', 'args': ['mainnet']},
            {'action': 'click_object', 'find_value': 'button'},
            {'action': 'sleep', 'ms': 1, 'screenshot': 'completed.png'},
        ]
        proc, passed, note, actions = self.execute(tests)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(passed, note)
        self.assertEqual([a['status'] for a in actions], ['pass'] * len(tests))
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual([c[0] for c in calls], [
            'click', 'wait', 'texts', 'texts', 'findByProperty', 'setProperty',
            'findByProperty', 'setProperty', 'findByProperty', 'getProperties',
            'findByProperty', 'callMethod', 'findByProperty', 'click', 'screenshot'])
        self.assertEqual((self.root / 'completed.png').read_bytes(), b'image')
        self.assertTrue(all(a['duration_ms'] >= 0 for a in actions))

    def test_false_assertion_fails_and_later_actions_are_not_run(self):
        tests = [
            {'action': 'sleep', 'ms': 1},
            {'action': 'expect_property', 'find_value': 'field', 'property': 'enabled', 'value': False},
            {'action': 'set_property', 'find_value': 'field', 'property': 'text', 'value': 'never'},
        ]
        # A previous successful journal must not mask the failing current run.
        self.trace.write_text(json.dumps([{'index': i, 'status': 'pass'} for i in range(3)]))
        proc, passed, _, actions = self.execute(tests)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(passed)
        self.assertEqual([a['status'] for a in actions], ['pass', 'fail', 'not_run'])
        self.assertIn('expected false got true', actions[1]['error'])
        self.assertNotIn('setProperty', self.calls.read_text())

    def test_screenshot_failure_fails_its_action(self):
        _, passed, _, actions = self.execute(
            [{'action': 'sleep', 'ms': 1, 'screenshot': 'missing.png'}], BAD_SCREENSHOT='1')
        self.assertFalse(passed)
        self.assertEqual(actions[0]['status'], 'fail')
        self.assertIn('no image', actions[0]['error'])

    def test_inspector_rejection_is_not_reported_as_success(self):
        for action in ('set_text', 'set_property', 'click_object'):
            with self.subTest(action=action):
                _, passed, _, actions = self.execute([
                    {'action': action, 'find_by': 'objectName', 'find_value': 'field',
                     'property': 'enabled', 'value': False}], RPC_ERROR='1')
                self.assertFalse(passed)
                self.assertEqual(actions[0]['status'], 'fail')
                self.assertIn('rejected', actions[0]['error'])

    def test_zero_exit_mid_action_does_not_pass(self):
        proc, passed, _, actions = self.execute([
            {'action': 'expect_texts', 'texts': ['Ready']},
            {'action': 'sleep', 'ms': 1}], INTERRUPT='1')
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(passed)
        self.assertEqual([a['status'] for a in actions], ['running', 'not_run'])

    def test_unknown_action_is_rejected_before_driver_is_written(self):
        with self.assertRaisesRegex(ValueError, 'UI action 1: unsupported'):
            dt.generate_mjs_tests([{'action': 'expect_proprety'}], str(self.root),
                                  'invalid', str(self.driver))
        self.assertFalse(self.driver.exists())

    def test_unknown_action_is_recorded_as_failure_without_launching(self):
        step = {'ui_test': {'launch': 'must-not-launch', 'qt_mcp': str(self.root),
                            'tests': [{'action': 'expect_proprety'}]}}
        results = dt.Results(fail_fast=False)
        collector = dt.ReportCollector()
        with mock.patch.object(dt, '_REPORT', collector), \
                mock.patch.object(dt.subprocess, 'Popen') as launch:
            dt.handle_ui_test(step, str(self.root), results, False, [], '', {})
        launch.assert_not_called()
        self.assertEqual(results.failed, 1)
        rec = collector.execs_for(step)[0]
        self.assertEqual(rec['status'], 'fail')
        self.assertIn('unsupported action', rec['note'])
        self.assertEqual(rec['actions'][0]['status'], 'not_run')

    def test_missing_or_invalid_journal_cannot_pass(self):
        tests = [{'action': 'sleep', 'ms': 1}]
        passed, note, actions = dt._ui_run_outcome(0, tests, str(self.trace))
        self.assertFalse(passed)
        self.assertIn('evidence unavailable', note)
        self.assertEqual(actions[0]['status'], 'not_run')
        for journal in ({}, [{'index': 3, 'status': 'pass'}], [{'index': 0, 'status': 'skip'}]):
            with self.subTest(journal=journal):
                self.trace.write_text(json.dumps(journal))
                self.assertFalse(dt._ui_run_outcome(0, tests, str(self.trace))[0])

    def test_report_keeps_commands_separate_from_runtime_action_results(self):
        tests = [{'action': 'sleep', 'ms': 1}]
        _, passed, _, actions = self.execute(tests)
        self.assertTrue(passed)
        collector = dt.ReportCollector()
        step = {}
        old_report = dt._REPORT
        try:
            dt._REPORT = collector
            dt._rec_ui(step, 'launch-app', tests, 'pass', '', 'framework output',
                       actions, 'node test.mjs --verbose')
        finally:
            dt._REPORT = old_report
        rec = collector.execs_for(step)[0]
        self.assertEqual(rec['cmd'], 'launch-app')
        self.assertEqual(rec['runner_cmd'], 'node test.mjs --verbose')
        self.assertEqual(rec['actions'][0]['status'], 'pass')
        self.assertNotIn('# test actions:', rec['cmd'])


if __name__ == '__main__':
    unittest.main()
