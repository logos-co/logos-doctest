#!/usr/bin/env python3
"""Execute generated drivers with Node; verify runtime evidence and failure gates."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
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
  let finds = 0, reads = 0;
  // SHOTS: comma-separated base64 images returned in order; the last repeats.
  const shots = (process.env.SHOTS || 'aW1hZ2U=').split(',');
  let shotIndex = 0;
  const app = {
    click: async (target) => log(['click', target]),
    expectTexts: async (texts) => {
      log(['texts', texts]);
      if (process.env.INTERRUPT) process.exit(0);
      if (texts.join() !== 'Ready') throw new Error('text not found');
    },
    // Polls like qt-mcp's waitFor, but counts attempts instead of sleeping.
    waitFor: async (fn, opts = {}) => {
      log(['wait', opts]);
      for (let i = Math.floor(opts.timeout / opts.interval); i > 0; i--) {
        try { return await fn(); } catch {}
      }
      return fn();
    },
    screenshot: async () => {
      log(['screenshot']);
      if (process.env.BAD_SCREENSHOT) return {};
      return { image: shots[Math.min(shotIndex++, shots.length - 1)] };
    },
    inspector: { send: async (command, args) => {
      log([command, args]);
      // MISSING_FINDS: element absent for that many lookups (view still loading).
      if (command === 'findByProperty')
        return ++finds <= Number(process.env.MISSING_FINDS || 0) ? { matches: [] } : { matches: [{ id: 1 }] };
      // SETTLE_AFTER_READS: `enabled` turns false only after that many reads.
      if (command === 'getProperties') {
        if (++reads > Number(process.env.SETTLE_AFTER_READS || Infinity)) state.enabled = false;
        return { properties: Object.entries(state).map(([name, value]) => ({name, value})) };
      }
      if (command === 'setProperty') {
        if (process.env.RPC_ERROR) return { error: 'write rejected' };
        state[args.property] = args.value;
      }
      if (command === 'click' && process.env.RPC_ERROR) return { error: 'click rejected' };
      // TYPED_PARAMS: callMethod refuses arguments as Qt does for a typed parameter.
      if (command === 'callMethod' && process.env.TYPED_PARAMS) return { error: "Failed to invoke '" + args.method + "'" };
      if (command === 'evaluate' && process.env.EVAL_ERROR) return { error: 'Evaluation error: ReferenceError' };
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

    def calls_made(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_the_driver_cap_counts_the_wait_the_driver_applies(self):
        tests = [{'action': 'wait_for', 'texts': ['Ready']}]
        _, passed, note, _ = self.execute(tests)
        self.assertTrue(passed, note)
        waited = self.calls_made()[0][1]['timeout']
        self.assertEqual(dt._ui_tests_timeout({'tests': tests}), 120 + waited / 1000)

    def test_expect_property_with_timeout_polls_until_it_holds(self):
        # The element is missing at first, then its value has not settled yet.
        tests = [{'action': 'expect_property', 'find_value': 'field', 'property': 'enabled',
                  'value': False, 'timeout': 2000}]
        _, passed, note, _ = self.execute(tests, MISSING_FINDS='1', SETTLE_AFTER_READS='2')
        self.assertTrue(passed, note)
        calls = self.calls_made()
        self.assertEqual((calls[0][0], calls[0][1]['timeout'], calls[0][1]['interval']),
                         ('wait', 2000, 500))
        self.assertEqual([c[0] for c in calls].count('getProperties'), 3)

    def test_expect_property_without_timeout_reads_once(self):
        tests = [{'action': 'expect_property', 'find_value': 'field', 'property': 'enabled',
                  'value': False}]
        _, passed, _, actions = self.execute(tests, SETTLE_AFTER_READS='1')
        self.assertFalse(passed)
        self.assertIn('expected false got true', actions[0]['error'])
        self.assertEqual([c[0] for c in self.calls_made()], ['findByProperty', 'getProperties'])

    def test_expect_property_timeout_reports_the_last_mismatch(self):
        tests = [{'action': 'expect_property', 'find_value': 'field', 'property': 'enabled',
                  'value': False, 'timeout': 1000}]
        _, passed, _, actions = self.execute(tests)
        self.assertFalse(passed)
        self.assertIn('expected false got true', actions[0]['error'])
        # Two polls in 1000 ms at 500 ms, then the final read that reports.
        self.assertEqual([c[0] for c in self.calls_made()].count('getProperties'), 3)

    def test_screenshot_failure_fails_its_action(self):
        _, passed, _, actions = self.execute(
            [{'action': 'sleep', 'ms': 1, 'screenshot': 'missing.png'}], BAD_SCREENSHOT='1')
        self.assertFalse(passed)
        self.assertEqual(actions[0]['status'], 'fail')
        self.assertIn('no image', actions[0]['error'])

    def shot_calls(self):
        return [c for c in map(json.loads, self.calls.read_text().splitlines())
                if c[0] == 'screenshot']

    def test_repeated_screenshot_is_retaken_until_it_changes(self):
        # 'image', then a stale 'image' once more, then 'other'.
        proc, passed, note, actions = self.execute([
            {'action': 'sleep', 'ms': 1, 'screenshot': 'first.png'},
            {'action': 'click', 'target': 'Next', 'screenshot': 'second.png'},
        ], SHOTS='aW1hZ2U=,aW1hZ2U=,b3RoZXI=')
        self.assertTrue(passed, note)
        self.assertEqual(len(self.shot_calls()), 3)
        self.assertEqual((self.root / 'second.png').read_bytes(), b'other')
        self.assertIn('second.png: matched first.png, re-took it 1x', proc.stdout)

    def test_screenshot_identical_to_the_previous_one_fails(self):
        _, passed, _, actions = self.execute([
            {'action': 'sleep', 'ms': 1, 'screenshot': 'first.png'},
            {'action': 'click', 'target': 'Next', 'screenshot': 'second.png'},
            {'action': 'sleep', 'ms': 1},
        ])
        self.assertFalse(passed)
        self.assertEqual([a['status'] for a in actions], ['pass', 'fail', 'not_run'])
        self.assertIn('second.png: identical to first.png', actions[1]['error'])
        self.assertGreater(len(self.shot_calls()), 2)
        self.assertFalse((self.root / 'second.png').exists())

    def test_allowed_unchanged_screenshot_passes_without_retakes(self):
        _, passed, note, _ = self.execute([
            {'action': 'sleep', 'ms': 1, 'screenshot': 'first.png'},
            {'action': 'click', 'target': 'Next', 'screenshot': 'again.png',
             'allow_unchanged_screenshot': True},
        ])
        self.assertTrue(passed, note)
        self.assertEqual(len(self.shot_calls()), 2)
        self.assertEqual((self.root / 'again.png').read_bytes(), b'image')

    def test_repeat_with_no_ui_action_between_is_not_compared(self):
        _, passed, note, _ = self.execute([
            {'action': 'click', 'target': 'Open', 'screenshot': 'first.png'},
            {'action': 'wait_for', 'texts': ['Ready']},
            {'action': 'expect_property', 'find_value': 'field', 'property': 'enabled',
             'value': True},
            {'action': 'sleep', 'ms': 1, 'screenshot': 'settled.png'},
        ])
        self.assertTrue(passed, note)
        self.assertEqual(len(self.shot_calls()), 2)

    def test_inspector_rejection_is_not_reported_as_success(self):
        for action in ('set_text', 'set_property', 'click_object'):
            with self.subTest(action=action):
                _, passed, _, actions = self.execute([
                    {'action': action, 'find_by': 'objectName', 'find_value': 'field',
                     'property': 'enabled', 'value': False}], RPC_ERROR='1')
                self.assertFalse(passed)
                self.assertEqual(actions[0]['status'], 'fail')
                self.assertIn('rejected', actions[0]['error'])

    def test_call_method_with_typed_parameters_emits_through_evaluate(self):
        tests = [{'action': 'call_method', 'find_value': 'view', 'method': 'unloadRequested',
                  'args': ['package_downloader', 2]}]
        _, passed, note, _ = self.execute(tests, TYPED_PARAMS='1')
        self.assertTrue(passed, note)
        calls = self.calls_made()
        self.assertEqual([c[0] for c in calls], ['findByProperty', 'callMethod', 'evaluate'])
        self.assertEqual(calls[2][1], {'objectId': 1,
                                       'expression': 'unloadRequested("package_downloader", 2)'})

    def test_call_method_fails_when_evaluate_fails_too(self):
        tests = [{'action': 'call_method', 'find_value': 'view', 'method': 'unloadRequested',
                  'args': ['x']}]
        _, passed, _, actions = self.execute(tests, TYPED_PARAMS='1', EVAL_ERROR='1')
        self.assertFalse(passed)
        self.assertIn('call_method unloadRequested: Evaluation error', actions[0]['error'])

    def test_call_method_without_arguments_does_not_fall_back(self):
        tests = [{'action': 'call_method', 'find_value': 'view', 'method': 'openDetails',
                  'args': []}]
        _, passed, _, actions = self.execute(tests, TYPED_PARAMS='1')
        self.assertFalse(passed)
        self.assertIn("Failed to invoke 'openDetails'", actions[0]['error'])
        self.assertNotIn('evaluate', [c[0] for c in self.calls_made()])

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


PORT_FRAMEWORK = '''
import { appendFileSync } from 'node:fs';
let callback;
export function test(name, fn) { callback = fn; }
export async function run() {
  appendFileSync(process.env.CALLS, JSON.stringify(['port', process.env.QML_INSPECTOR_PORT]) + '\\n');
  try { await callback({}); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
'''

# Listens on QML_INSPECTOR_PORT and logs what qt-mcp's inspector would.
FAKE_APP = r'''
import os, signal, socket, sys, time
mode = sys.argv[1]
port = int(os.environ["QML_INSPECTOR_PORT"])
with open("app.pid", "w") as f:
    f.write(str(os.getpid()))
if mode == "stubborn":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
server = socket.socket()
server.bind(("127.0.0.1", port))
server.listen()
listening = "[QmlInspector] Inspector server listening on port %d"
failed = "[QmlInspector] Failed to listen on port %d : The bound address is already in use"
for line in {"listening": [listening % port], "stubborn": [listening % port],
             "taken": [failed % port], "child-failed": [failed % port, listening % port],
             "other-port": [listening % (port + 1)], "silent": []}[mode]:
    print(line, flush=True)
while True:
    time.sleep(1)
'''


def _free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class InspectorPortChoice(unittest.TestCase):
    def test_the_spec_wins_then_the_environment_then_3768(self):
        with mock.patch.dict(os.environ, {'QML_INSPECTOR_PORT': '4001'}):
            self.assertEqual(dt._inspector_port({'inspector_port': 4000}), 4000)
            self.assertEqual(dt._inspector_port({}), 4001)
        with mock.patch.dict(os.environ, {'QML_INSPECTOR_PORT': 'x'}):
            self.assertEqual(dt._inspector_port({}), 3768)
        with mock.patch.dict(os.environ):
            os.environ.pop('QML_INSPECTOR_PORT', None)
            self.assertEqual(dt._inspector_port({}), 3768)


class DriverTimeout(unittest.TestCase):
    """The driver may run 120 s plus every action's own wait, unless tests_timeout is set."""

    # logos-monerod-ui's sync step: 1080 s of waits, cut short by the old flat 120 s.
    SYNC = [{'action': 'wait_for', 'texts': ['stopped'], 'timeout': 30000},
            {'action': 'click', 'target': 'Start'},
            {'action': 'wait_for', 'texts': ['running'], 'timeout': 60000},
            {'action': 'wait_for', 'texts': ['Syncing'], 'timeout': 900000},
            {'action': 'expect_property', 'find_value': 'syncPercent', 'property': 'visible',
             'value': True},
            {'action': 'click', 'target': 'Stop'},
            {'action': 'wait_for', 'texts': ['stopped'], 'timeout': 90000}]

    def test_waits_beyond_120_s_extend_the_cap(self):
        self.assertEqual(dt._ui_tests_timeout({'tests': self.SYNC}), 120 + 1080)

    def test_actions_that_do_not_wait_keep_120_s(self):
        self.assertEqual(dt._ui_tests_timeout({'tests': [
            {'action': 'click', 'target': 'Go'},
            {'action': 'expect_property', 'find_value': 'f', 'property': 'p', 'value': 1}]}), 120)

    def test_default_waits_count_too(self):
        # wait_for waits 10 s and sleep 1 s by default; expect_property polls only with a timeout.
        self.assertEqual(dt._ui_tests_timeout({'tests': [
            {'action': 'wait_for', 'texts': ['Ready']}, {'action': 'sleep'},
            {'action': 'expect_property', 'find_value': 'f', 'property': 'p', 'value': 1,
             'timeout': 2000}]}), 120 + 10 + 1 + 2)

    def test_tests_timeout_overrides_the_sum(self):
        self.assertEqual(dt._ui_tests_timeout({'tests_timeout': 30, 'tests': self.SYNC}), 30)


class InspectorPortGuard(unittest.TestCase):
    """doctest run launches onto a free inspector port, and drives only an app listening there."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'test-framework').mkdir()
        (self.root / 'test-framework' / 'framework.mjs').write_text(PORT_FRAMEWORK)
        (self.root / 'fake_app.py').write_text(FAKE_APP)
        self.calls = self.root / 'calls.jsonl'
        self.port = _free_port()
        for name in ('_INSPECTOR_LOG_GRACE', '_APP_STOP_GRACE'):
            patcher = mock.patch.object(dt, name, 0.5)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_step(self, mode, tests=None, **ui):
        step = {'title': 'Drive the fake app', 'ui_test': {
            'launch': f'{shlex.quote(sys.executable)} fake_app.py {mode}',
            'qt_mcp': str(self.root), 'inspector_port': self.port, 'launch_timeout': 10,
            'tests': tests or [{'action': 'sleep', 'ms': 1}], **ui}}
        results = dt.Results(fail_fast=False)
        collector = dt.ReportCollector()
        with mock.patch.object(dt, '_REPORT', collector), \
                mock.patch.dict(os.environ, {'CALLS': str(self.calls)}):
            dt.handle_ui_test(step, str(self.root), results, False, [], '', {})
        return results, collector.execs_for(step)[0]

    def driven_on(self):
        if not self.calls.exists():
            return None
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def assert_app_gone(self):
        pid = int((self.root / 'app.pid').read_text())
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail(f'app {pid} outlived its step')
        self.assertFalse(dt._port_open(self.port))

    def test_a_port_in_use_is_refused_before_launch(self):
        with socket.socket() as holder:
            holder.bind(('127.0.0.1', self.port))
            holder.listen()
            with mock.patch.object(dt.subprocess, 'Popen') as launch:
                results, rec = self.run_step('listening')
        launch.assert_not_called()
        self.assertEqual(results.failed, 1)
        self.assertEqual(rec['status'], 'fail')
        self.assertIn(f'inspector port {self.port} was in use before launch', rec['note'])
        self.assertEqual(rec['actions'][0]['status'], 'not_run')

    @unittest.skipIf(os.name == 'nt', 'doctest run launches the app with setsid')
    @unittest.skipUnless(shutil.which('node'), 'Node is required to execute generated UI drivers')
    def test_the_app_and_the_driver_get_the_spec_port(self):
        results, rec = self.run_step('listening')
        self.assertEqual((rec['status'], rec['note']), ('pass', ''), rec['output'])
        self.assertEqual(results.passed, 1)
        self.assertEqual(self.driven_on(), [['port', str(self.port)]])
        self.assert_app_gone()

    @unittest.skipIf(os.name == 'nt', 'doctest run launches the app with setsid')
    @unittest.skipUnless(shutil.which('node'), 'Node is required to execute generated UI drivers')
    def test_an_app_that_could_not_listen_is_not_driven(self):
        results, rec = self.run_step('taken')
        self.assertEqual(results.failed, 1)
        self.assertIn(f'could not listen on inspector port {self.port}', rec['note'])
        self.assertIsNone(self.driven_on())
        self.assertEqual(rec['actions'][0]['status'], 'not_run')
        self.assert_app_gone()

    @unittest.skipIf(os.name == 'nt', 'doctest run launches the app with setsid')
    @unittest.skipUnless(shutil.which('node'), 'Node is required to execute generated UI drivers')
    def test_a_listening_line_outweighs_a_failed_one(self):
        # A second process of the app may fail to bind the port the first one holds.
        _, rec = self.run_step('child-failed')
        self.assertEqual((rec['status'], rec['note']), ('pass', ''), rec['output'])

    @unittest.skipIf(os.name == 'nt', 'doctest run launches the app with setsid')
    @unittest.skipUnless(shutil.which('node'), 'Node is required to execute generated UI drivers')
    def test_no_line_about_the_port_is_driven_as_before(self):
        for mode in ('silent', 'other-port'):
            with self.subTest(mode=mode):
                self.calls.unlink(missing_ok=True)
                _, rec = self.run_step(mode)
                self.assertEqual((rec['status'], rec['note']), ('pass', ''), rec['output'])
                self.assert_app_gone()

    @unittest.skipIf(os.name == 'nt', 'doctest run launches the app with setsid')
    @unittest.skipUnless(shutil.which('node'), 'Node is required to execute generated UI drivers')
    def test_an_app_that_ignores_sigterm_is_killed(self):
        _, rec = self.run_step('stubborn')
        self.assertEqual(rec['status'], 'pass', rec['output'])
        self.assert_app_gone()

    @unittest.skipIf(os.name == 'nt', 'doctest run launches the app with setsid')
    @unittest.skipUnless(shutil.which('node'), 'Node is required to execute generated UI drivers')
    def test_the_driver_may_run_as_long_as_its_actions_wait(self):
        (self.root / 'test-framework' / 'framework.mjs').write_text(FRAMEWORK)
        tests = [{'action': 'wait_for', 'texts': ['Ready'], 'timeout': 900000}]
        with mock.patch.object(dt, 'run_cmd', wraps=dt.run_cmd) as run_cmd:
            _, rec = self.run_step('listening', tests)
        self.assertEqual((rec['status'], rec['note']), ('pass', ''), rec['output'])
        self.assertEqual([c.kwargs['timeout'] for c in run_cmd.call_args_list
                          if c.args[0].startswith('node ')], [120 + 900])

    @unittest.skipIf(os.name == 'nt', 'doctest run launches the app with setsid')
    @unittest.skipUnless(shutil.which('node'), 'Node is required to execute generated UI drivers')
    def test_tests_timeout_stops_the_driver(self):
        started = time.time()
        results, rec = self.run_step('listening', [{'action': 'sleep', 'ms': 10000}],
                                     tests_timeout=1)
        self.assertLess(time.time() - started, 10)
        self.assertEqual(results.failed, 1)
        self.assertIn('command timed out after 1s', rec['output'])
        self.assertEqual(rec['actions'][0]['status'], 'running')
        self.assert_app_gone()


if __name__ == '__main__':
    unittest.main()
