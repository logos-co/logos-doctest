#!/usr/bin/env python3
"""Unit tests for WHERE injected nix flags land relative to a `--`.

The bug these guard against: `nix run REF -- --height 1000` hands everything
after `--` to the LAUNCHED PROGRAM. Injection used to append unconditionally,
so `--override-input ...` reached the app instead of nix. The app rejected the
flags and exited before opening its QML inspector:

    Launching: nix run github:logos-co/logos-evm-wallet-ui/68f7c4fe \\
      --no-write-lock-file -- --height 1000 --override-input eth_rpc_module ...
    app output: LogosStandalone: Unknown options: override-input, override-input, ...
    FAIL  Launch and drive the app
          app exited (code 1) before inspector opened on port 3768

That silently broke EVERY ui_test spec whenever --workspace-pins was active,
i.e. in the workspace CI job — the one job whose entire purpose is catching
cross-repo drift. It had been red for that reason across unrelated pin PRs.

The second half of the same bug is invisible: `_parse_nix_run` stops at `--`,
so flags appended after it were also dropped from the warm pre-build, which
then pre-built the UN-overridden closure while the launch used the overridden
one. Fixing the insertion point fixes both, which is why WarmPrebuildSeesFlags
asserts on the parse rather than on the string.

These are pure string/parse tests: no nix, no network, no toolchain.

Run with:  python3 tests/test_inject_double_dash.py
"""

import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_engine():
    spec = importlib.util.spec_from_file_location(
        "doctest_engine", os.path.join(ROOT, "doctest.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dt = _load_engine()

OV = "--override-input foo github:o/r/abc"


def inject(cmd):
    """Inject spec-level overrides only (no WORKSPACE_PINS), so these tests
    stay independent of pin-map loading."""
    return dt._inject_into_block(cmd, OV, workdir=".")


class SplitAtArgSeparator(unittest.TestCase):
    def test_bare_double_dash_is_the_separator(self):
        self.assertEqual(dt._split_at_arg_separator("nix run X -- --height 2000"),
                         ("nix run X ", "-- --height 2000"))

    def test_no_separator_returns_whole_segment(self):
        self.assertEqual(dt._split_at_arg_separator("nix build .#x -o out"),
                         ("nix build .#x -o out", ""))

    def test_long_flags_are_not_separators(self):
        # `--height` starts with `--` but is not a bare `--`.
        self.assertEqual(dt._split_at_arg_separator("nix build --no-link .#x"),
                         ("nix build --no-link .#x", ""))

    def test_quoted_double_dash_is_literal(self):
        for cmd in ('echo "a -- b"', "echo 'a -- b'"):
            self.assertEqual(dt._split_at_arg_separator(cmd), (cmd, ""),
                             f"quoted -- must not split: {cmd}")

    def test_trailing_double_dash(self):
        self.assertEqual(dt._split_at_arg_separator("nix run X --"),
                         ("nix run X ", "--"))


class InjectionLandsLeftOfTheSeparator(unittest.TestCase):
    def test_ui_test_launch_shape(self):
        got = inject("nix run github:o/r --no-write-lock-file -- --height 2000")
        self.assertIn(f"--no-write-lock-file {OV} --", got)
        self.assertTrue(got.rstrip().endswith("-- --height 2000"),
                        f"app argv must stay last, got: {got}")

    def test_app_argv_is_not_polluted(self):
        got = inject("nix run github:o/r -- --height 2000 --user-dir ./session")
        app_argv = got.split(" -- ", 1)[1]
        self.assertNotIn("--override-input", app_argv,
                         "override flags must never reach the launched program")

    def test_plain_build_still_appends(self):
        got = inject("nix build .#x -o out")
        self.assertTrue(got.rstrip().endswith(OV), f"got: {got}")

    def test_separator_survives_exactly_once(self):
        got = inject("nix run github:o/r -- --height 2000")
        self.assertEqual(got.count(" -- "), 1, f"got: {got}")

    def test_backgrounded_launch_keeps_flags_on_the_command(self):
        # `&` is a segment separator, so the flags must land before it AND
        # before the `--`.
        got = inject("nix run github:o/r -- --height 2000 &")
        self.assertIn(OV, got)
        app_argv = got.split(" -- ", 1)[1]
        self.assertNotIn("--override-input", app_argv)


class WarmPrebuildSeesFlags(unittest.TestCase):
    """The invisible half: with the flags left of `--`, _parse_nix_run picks
    them up, so the pre-build warms the SAME closure the launch runs. Appended
    after `--` they were dropped here silently."""

    def test_parse_collects_injected_overrides(self):
        cmd = inject("nix run github:o/r#app --no-write-lock-file -- --height 2000")
        parsed = dt._parse_nix_run(cmd)
        self.assertIsNotNone(parsed, f"should still parse: {cmd}")
        base, fragment, flags = parsed
        self.assertEqual(base, "github:o/r")
        self.assertEqual(fragment, "app")
        self.assertIn("--override-input", flags)
        self.assertIn("github:o/r/abc", flags)

    def test_app_argv_never_becomes_a_nix_flag(self):
        cmd = inject("nix run github:o/r -- --height 2000")
        _, _, flags = dt._parse_nix_run(cmd)
        self.assertNotIn("--height", flags,
                         "the app's own argv must not be parsed as nix flags")


if __name__ == "__main__":
    unittest.main(verbosity=2)
