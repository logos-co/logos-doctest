#!/usr/bin/env python3
"""Unit tests for the `nix run` pre-build (warm) resolver.

The bug these guard against: the ui_test pre-build used to string-rewrite a
spec's `nix run REF` into `nix build REF`, which builds `packages.<sys>.default`
— a DIFFERENT flake output from the `apps.<sys>.default` that `nix run`
executes. For every `type: ui_qml` Logos module those two are genuinely
different derivations (plugin vs. standalone app + plugin dir + dependency
modules), so the app's whole compile moved into the launch step, was counted
against `launch_timeout` instead of `build_timeout`, and the run failed with
"inspector not available on port 3768 after 300s".

The fixture flakes below reproduce exactly that shape with no toolchain: their
`packages.default` and `apps.default` are two different derivations. Nothing is
ever BUILT here — the resolver only has to evaluate — so these tests need nix
but no nixpkgs, no network, and no Qt.

Run with:  nix develop .# --command python3 tests/test_app_warm.py
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_engine():
    spec = importlib.util.spec_from_file_location(
        "doctest_engine", os.path.join(ROOT, "doctest.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dt = _load_engine()


# A flake with NO inputs: instant to evaluate, nothing to fetch. `packages`
# and `apps` deliberately name two different derivations, the way a ui_qml
# module's plugin and standalone app do.
FLAKE_WITH_APP = """{
  description = "warm-resolver fixture: apps.default != packages.default";
  outputs = { self }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAll = f: builtins.listToAttrs
        (map (s: { name = s; value = f s; }) systems);
      mk = system: name: derivation {
        inherit name system;
        builder = "/bin/sh";
        args = [ "-c" "echo unused > $out" ];
      };
    in {
      packages = forAll (system: { default = mk system "warm-fixture-plugin"; });
      apps = forAll (system: {
        default = {
          type = "app";
          program = "${mk system "warm-fixture-app"}/bin/run-app";
        };
      });
    };
}
"""

FLAKE_PACKAGE_ONLY = """{
  description = "warm-resolver fixture: no apps output at all";
  outputs = { self }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAll = f: builtins.listToAttrs
        (map (s: { name = s; value = f s; }) systems);
    in {
      packages = forAll (system: {
        default = derivation {
          name = "warm-fixture-plugin";
          inherit system;
          builder = "/bin/sh";
          args = [ "-c" "echo unused > $out" ];
        };
      });
    };
}
"""


def _write_flake(text):
    # realpath: on macOS /tmp is a symlink, and `path:` flake refs reject those
    # ("error: path '//tmp' is a symlink").
    d = os.path.realpath(tempfile.mkdtemp(prefix="doctest-warm-"))
    with open(os.path.join(d, "flake.nix"), "w") as f:
        f.write(text)
    return d


class ParseNixRun(unittest.TestCase):
    """Finding the installable in an arbitrary `nix run` command line."""

    def test_bare(self):
        self.assertEqual(dt._parse_nix_run("nix run ."), (".", "", []))

    def test_default_installable(self):
        self.assertEqual(dt._parse_nix_run("nix run"), (".", "", []))

    def test_override_input_is_not_mistaken_for_the_installable(self):
        # The real ui-typed-backend spec's launch line.
        self.assertEqual(
            dt._parse_nix_run(
                "nix run ./ticker-panel --override-input tick_module path:tick-module"),
            ("./ticker-panel", "",
             ["--override-input", "tick_module", "path:tick-module"]))

    def test_flags_before_the_installable(self):
        self.assertEqual(
            dt._parse_nix_run("nix run --override-input a path:b .#x"),
            (".", "x", ["--override-input", "a", "path:b"]))

    def test_app_argv_after_double_dash_is_ignored(self):
        self.assertEqual(dt._parse_nix_run("nix run .#myapp -- --port 1234"),
                         (".", "myapp", []))

    def test_build_only_flags_are_not_passed_to_eval(self):
        # `nix eval -o result` would fail, and a failed resolve silently
        # degrades to the old (wrong) warm.
        self.assertEqual(dt._parse_nix_run("nix run . -o result"), (".", "", []))

    def test_declines_commands_it_cannot_reason_about(self):
        for cmd in ("cd sub && nix run .",       # relative ref, other cwd
                    "QT_QPA_PLATFORM=x nix run .",
                    "nix build .",
                    "(cd sub; nix run .)",
                    "nix run . && echo done"):
            self.assertIsNone(dt._parse_nix_run(cmd), cmd)


class ResolveAppWarmTargets(unittest.TestCase):
    """What the pre-build actually builds, resolved through nix."""

    @classmethod
    def setUpClass(cls):
        cls.system = dt._nix_system()
        if not cls.system:
            raise unittest.SkipTest("nix not available")

    def _drv_of_package(self, flake_dir):
        out = subprocess.run(
            ["nix", "eval", "--raw",
             f"path:{flake_dir}#packages.{self.system}.default.drvPath"],
            capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def test_resolves_the_app_derivation_not_the_package(self):
        d = _write_flake(FLAKE_WITH_APP)
        targets = dt._app_warm_installables(f"nix run path:{d}", os.getcwd())
        self.assertIsNotNone(targets, "app attribute should resolve")
        self.assertEqual(len(targets), 1, targets)
        target = targets[0]

        # It is the app's derivation, buildable as-is...
        self.assertTrue(target.endswith(".drv^*"), target)
        self.assertIn("warm-fixture-app", target)
        # ...and NOT the package the old `nix run` -> `nix build` rewrite built.
        self.assertNotIn("warm-fixture-plugin", target)
        self.assertNotEqual(target[:-len("^*")], self._drv_of_package(d))

    def test_the_resolved_derivation_is_what_nix_run_would_execute(self):
        d = _write_flake(FLAKE_WITH_APP)
        target = dt._app_warm_installables(f"nix run path:{d}", os.getcwd())[0]
        program = subprocess.run(
            ["nix", "eval", "--raw",
             f"path:{d}#apps.{self.system}.default.program"],
            capture_output=True, text=True).stdout.strip()
        # The program lives inside the output of the derivation we warm.
        out_path = subprocess.run(
            ["nix", "derivation", "show", target[:-len("^*")]],
            capture_output=True, text=True).stdout
        self.assertIn(os.path.dirname(os.path.dirname(program)), out_path)

    def test_package_only_flake_falls_back(self):
        # No apps output: None tells the caller to keep the plain `nix build`
        # rewrite, which is the correct warm for those flakes.
        d = _write_flake(FLAKE_PACKAGE_ONLY)
        self.assertIsNone(
            dt._app_warm_installables(f"nix run path:{d}", os.getcwd()))

    def test_unparseable_launch_falls_back(self):
        d = _write_flake(FLAKE_WITH_APP)
        self.assertIsNone(
            dt._app_warm_installables(f"cd x && nix run path:{d}", os.getcwd()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
