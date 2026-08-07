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

Two invariants are guarded, and they pull in opposite directions:

  * a launch shape that CAN resolve must keep resolving. Every fallback is a
    silent return to the original wrong-target bug, so a guard that pushes
    valid specs into it is the bug wearing a different hat.
  * a resolve is only trusted when it comes back as a derivation. Trusting a
    non-derivation warms something unbuildable, which is worse than the
    fallback it displaces (see ResolvedTargetMustBeADerivation).

Run with:  nix develop .# --command python3 tests/test_app_warm.py
"""

import importlib.util
import os
import shlex
import shutil
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
        # A named app, the `nix run REF#group` shape the chat-ui specs use.
        alt = {
          type = "app";
          program = "${mk system "warm-fixture-alt"}/bin/run-alt";
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


class FlakeFixtureMixin:
    """Writes fixture flakes into temp dirs that are removed after each test."""

    def _write_flake(self, text):
        # realpath: on macOS /tmp is a symlink, and `path:` flake refs reject
        # those ("error: path '//tmp' is a symlink").
        d = os.path.realpath(tempfile.mkdtemp(prefix="doctest-warm-"))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
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


class ResolveAppWarmTargets(FlakeFixtureMixin, unittest.TestCase):
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
        d = self._write_flake(FLAKE_WITH_APP)
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
        d = self._write_flake(FLAKE_WITH_APP)
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
        d = self._write_flake(FLAKE_PACKAGE_ONLY)
        self.assertIsNone(
            dt._app_warm_installables(f"nix run path:{d}", os.getcwd()))

    def test_unparseable_launch_falls_back(self):
        d = self._write_flake(FLAKE_WITH_APP)
        self.assertIsNone(
            dt._app_warm_installables(f"cd x && nix run path:{d}", os.getcwd()))


class LaunchFlagsSurviveTheShell(FlakeFixtureMixin, unittest.TestCase):
    """The launch command's own flags reach nix as the words it meant.

    The resolve runs through a shell, but `flags` arrive already split by
    shlex. Re-joining them raw lets one flag value become several argv
    entries; nix then rejects the surplus positional, the resolve fails, and
    the caller degrades to the plain `nix build` rewrite — which is exactly
    the wrong-target bug this whole module exists to prevent.

    That degradation is easy to miss rather than invisible: it still prints a
    `Pre-building app:` line, just naming the flake ref instead of a `.drv^*`
    and without the `(the apps output of: …)` continuation, and it only says
    why under `--verbose` (`no app attribute at …; warming the package
    instead`). Nothing fails, so a test is what actually catches it.
    """

    @classmethod
    def setUpClass(cls):
        cls.system = dt._nix_system()
        if not cls.system:
            raise unittest.SkipTest("nix not available")

    def _resolve(self, flake_dir, flags):
        return dt._app_warm_installables(
            f"nix run path:{flake_dir} {flags}", os.getcwd())

    def test_space_inside_a_flag_value(self):
        # nix's list-valued options are space separated, so this is an
        # ordinary thing for a spec to carry.
        d = self._write_flake(FLAKE_WITH_APP)
        targets = self._resolve(
            d, "--option extra-substituters "
               "'https://a.example.org https://b.example.org'")
        self.assertIsNotNone(
            targets, "a space in a flag value must not defeat the resolve")
        self.assertIn("warm-fixture-app", targets[0])

    def test_metacharacter_inside_a_flag_value(self):
        d = self._write_flake(FLAKE_WITH_APP)
        targets = self._resolve(
            d, "--option extra-substituters 'https://a.example.org;x'")
        self.assertIsNotNone(
            targets, "a ';' in a flag value must not defeat the resolve")
        self.assertIn("warm-fixture-app", targets[0])

    def test_flag_values_are_not_evaluated_by_the_shell(self):
        """A flag value is data to the resolve, and the warm does NOT expand it.

        This locks in a deliberate asymmetry with the launch, which is worth
        knowing before you write a spec that leans on it. The launch runs via
        `subprocess(..., shell=True)`, so ITS flag values still go through the
        shell; the resolve's do not. A launch flag that only means something
        after expansion — `--override-input dep 'path:$DEPDIR'`, or a `~` —
        therefore resolves to nothing (`nix eval` reports `path '…/$DEPDIR'
        does not exist`), and the warm quietly falls back to the plain `nix
        build` rewrite while the launch goes on to expand it.

        That is the intended trade: expanding here would warm a target the
        launch never named, which is a worse failure than warming the package.
        Nothing in-tree depends on it — `expand_vars` handles only {ext},
        {shared_flags} and {release}, and no `nix run` launch line in the
        workspace carries a shell variable.
        """
        d = self._write_flake(FLAKE_WITH_APP)
        marker = os.path.join(d, "SUBSTITUTED")
        targets = self._resolve(
            d, f"--option extra-substituters '$(touch {shlex.quote(marker)})'")
        self.assertFalse(
            os.path.exists(marker),
            "the flag value was expanded by the shell instead of passed through")
        self.assertIsNotNone(targets)
        self.assertIn("warm-fixture-app", targets[0])


class ResolvedTargetMustBeADerivation(FlakeFixtureMixin, unittest.TestCase):
    """The resolve is only trusted when it comes back as a derivation.

    `builtins.getContext` keys the derivations a string depends on, so a
    successful resolve is all `.drv` and nothing else. A plain store path
    coming back means the eval never ran our `--apply` and we are staring at
    the raw program — which happens whenever a flag ahead of it swallows
    `--apply` as one of its own values.

    That result is truthy, so without a check the caller SKIPS the fallback and
    warms a program path. On a cold store — the case this whole resolver exists
    for — that path is not buildable at all ("don't know how to build these
    paths"), so the warm does nothing and the launch pays the whole compile:
    strictly worse than the fallback it displaced. What the log shows is a
    `Pre-building app:` line naming something that is not a `.drv` followed by
    `pre-build returned non-zero; launching anyway`, which reads like an
    ordinary best-effort miss. (On a warm store it "succeeds" as a no-op and
    there is no warning at all.)

    Defence in depth rather than a live bug: every flag truncation that
    produces this also makes the launch itself fail (`error: flag '--option'
    requires 2 argument(s), but only 0 were given`), so no spec can reach it
    today. The point is that the check is structural — it does not depend on
    anyone having enumerated the flag that swallowed the `--apply`.
    """

    @classmethod
    def setUpClass(cls):
        cls.system = dt._nix_system()
        if not cls.system:
            raise unittest.SkipTest("nix not available")

    # `--option` takes two values; with none supplied it eats `--apply` and the
    # expression, nix shrugs ("warning: unknown setting '--apply'"), and the
    # eval succeeds without ever applying the function.
    TRUNCATED = "--option"

    def test_the_truncated_flag_really_does_defeat_the_apply(self):
        """Not a tautology: the bad resolve exists and is a program path."""
        d = self._write_flake(FLAKE_WITH_APP)
        out = subprocess.run(
            ["nix", "eval", "--raw",
             f"path:{d}#apps.{self.system}.default.program",
             self.TRUNCATED, "--apply", dt._APP_PROGRAM_CTX],
            capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, "the eval is expected to SUCCEED")
        got = out.stdout.strip()
        self.assertTrue(got.startswith("/nix/store/"), got)
        self.assertFalse(got.endswith(".drv"), f"expected a program path: {got}")
        self.assertTrue(got.endswith("/bin/run-app"), got)

    def test_that_program_path_is_not_buildable(self):
        """...and warming it would have been a no-op, not a cheaper warm."""
        d = self._write_flake(FLAKE_WITH_APP)
        program = subprocess.run(
            ["nix", "eval", "--raw",
             f"path:{d}#apps.{self.system}.default.program"],
            capture_output=True, text=True).stdout.strip()
        # `substituters ''` keeps this hermetic and instant; the fixture
        # derivation is never built, so the path cannot exist.
        out = subprocess.run(
            ["nix", "build", "--no-link", "--option", "substituters", "", program],
            capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0, "expected an unbuildable path")
        self.assertIn("don't know how to build", out.stderr)

    def test_a_non_derivation_resolve_falls_back(self):
        """The guard: fall back, rather than warm something unbuildable."""
        d = self._write_flake(FLAKE_WITH_APP)
        self.assertIsNone(
            dt._app_warm_installables(
                f"nix run path:{d} {self.TRUNCATED}", os.getcwd()),
            "a resolve that did not yield a derivation must fall back")

    def test_every_resolved_target_is_a_derivation(self):
        """The invariant, across the launch shapes real specs actually use."""
        d = self._write_flake(FLAKE_WITH_APP)
        for suffix in ("",                                  # nix run .
                       "#alt",                              # nix run .#name
                       f"#apps.{self.system}.default",      # explicit attr path
                       " -- --height 1000",                 # app argv
                       " --no-write-lock-file -- --height 2000",
                       " -o result"):                       # build-only flag
            with self.subTest(suffix=suffix):
                sep = "" if suffix.startswith("#") else " "
                targets = dt._app_warm_installables(
                    f"nix run path:{d}{sep}{suffix}".strip(), os.getcwd())
                self.assertIsNotNone(targets, "this shape must still resolve")
                for t in targets:
                    self.assertTrue(t.endswith(".drv^*"), t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
