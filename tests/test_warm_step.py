#!/usr/bin/env python3
"""Regression tests for the ui_test pre-build ("warm") step.

The warm step exists so that a cold-cache compile of a `nix run` launch is
charged to `build_timeout` rather than to the inspector's `launch_timeout`. It
used to string-rewrite `nix run X` into `nix build X`, which warms
`packages.<system>.default` — a *different* flake output from the
`apps.<system>.default` that `nix run` actually executes. For a `type: ui_qml`
module the two are disjoint closures, so the app's compile happened during the
launch anyway and blew the inspector timeout.

These tests are pure evaluation: nix instantiates the probe flakes' derivations
(writing .drv files) but never runs a builder, so they are fast, hermetic, need
no network, and cannot hang.

Run:  python3 tests/test_warm_step.py
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "doctest.py")

_spec = importlib.util.spec_from_file_location("doctest_engine", ENGINE)
dt = importlib.util.module_from_spec(_spec)
_argv, sys.argv = sys.argv, ["doctest"]
_spec.loader.exec_module(dt)
sys.argv = _argv


failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}\n         got:  {got!r}\n         want: {want!r}")
        failures.append(label)


def check_that(label, cond, detail=""):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{('  — ' + detail) if detail else ''}")
        failures.append(label)


# ── 1. Parsing real `launch:` commands ────────────────────────────────────────
#
# Every shape that appears in the Logos doc-test corpus, plus the shapes the
# warm step must decline to touch.

print("split_nix_run")

CASES = [
    ("nix run .", (".", [])),
    ("nix run ./ticker-panel --override-input tick_module path:tick-module",
     ("./ticker-panel", ["--override-input", "tick_module", "path:tick-module"])),
    ("nix run 'github:logos-co/logos-chat-ui#exchange'",
     ("github:logos-co/logos-chat-ui#exchange", [])),
    # `--` and everything after it is program arguments: `nix build`/`nix eval`
    # would choke on them, so they must be dropped.
    ("nix run github:logos-co/logos-evm-wallet-ui --no-write-lock-file -- --height 1000",
     ("github:logos-co/logos-evm-wallet-ui", ["--no-write-lock-file"])),
    ("nix run . --override-input calc_module path:../logos-calc-module",
     (".", ["--override-input", "calc_module", "path:../logos-calc-module"])),
    # Flags may precede the installable.
    ("nix run --override-input a path:./a ./app",
     ("./app", ["--override-input", "a", "path:./a"])),
    ("  nix run .  ", (".", [])),
    # Not a `nix run` at all — leave these alone.
    ("./result-bundle/bin/LogosBasecamp --user-dir ./testdata", None),
    ("nix build .", None),
    ("sh -c 'nix run .'", None),
]
for cmd, want in CASES:
    check(cmd, dt.split_nix_run(cmd), want)


# ── 2. A flake whose app and package are DIFFERENT closures ───────────────────
#
# The shape of every `type: ui_qml` module: packages.default is the plugin,
# apps.default is the standalone app that hosts it.

APP_FLAKE = """{
  description = "warm-step probe: packages.default and apps.default differ";
  outputs = { self }:
    let
      systems = [ "aarch64-darwin" "x86_64-darwin" "aarch64-linux" "x86_64-linux" ];
      forAll = f: builtins.listToAttrs (map (s: { name = s; value = f s; }) systems);
      mk = system: name: derivation {
        inherit system name;
        builder = "/bin/sh";
        args = [ "-c" "echo ${name} > $out" ];
      };
    in {
      packages = forAll (system: { default = mk system "warmprobe-plugin"; });
      apps = forAll (system: {
        default = {
          type = "app";
          program = "${mk system "warmprobe-app"}/bin/run";
        };
      });
    };
}
"""

PKG_ONLY_FLAKE = """{
  description = "warm-step probe: no apps output at all";
  outputs = { self }:
    let
      systems = [ "aarch64-darwin" "x86_64-darwin" "aarch64-linux" "x86_64-linux" ];
      forAll = f: builtins.listToAttrs (map (s: { name = s; value = f s; }) systems);
    in {
      packages = forAll (system: {
        default = derivation {
          inherit system;
          name = "warmprobe-pkgonly";
          builder = "/bin/sh";
          args = [ "-c" "echo hi > $out" ];
        };
      });
    };
}
"""


def probe(contents):
    d = tempfile.mkdtemp(prefix="doctest-warm-probe-")
    with open(os.path.join(d, "flake.nix"), "w") as f:
        f.write(contents)
    return d


if shutil.which("nix") is None:
    print("\nnix not on PATH — skipping the flake-resolution tests")
else:
    print("\nnix_run_warm_command — flake WITH an apps.<system>.default")
    d = probe(APP_FLAKE)
    try:
        sysd = subprocess.run(
            ["nix", "eval", "--impure", "--raw", "--expr", "builtins.currentSystem"],
            stdout=subprocess.PIPE, text=True).stdout.strip()
        plug = subprocess.run(
            ["nix", "eval", "--raw", f"{d}#packages.{sysd}.default",
             "--apply", "p: p.drvPath"],
            stdout=subprocess.PIPE, text=True).stdout.strip()
        warm = dt.nix_run_warm_command("nix run .", d) or ""
        print(f"       package drv: {plug}")
        print(f"       warm:        {warm}")
        check_that("warms the app derivation", "warmprobe-app.drv" in warm, warm)
        # The whole point: the package build is NOT what gets launched. The old
        # `nix run X` -> `nix build X` rewrite fails exactly here.
        check_that("does not settle for the packages.default rewrite",
                   warm != "nix build . -L" and plug and plug not in warm,
                   f"{plug} vs {warm}")
        check_that("realises the derivation's outputs (^*)", ".drv^*" in warm, warm)
        check_that("does not execute anything", " run " not in f" {warm} ", warm)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("\nnix_run_warm_command — flake with NO apps output (the common case)")
    d = probe(PKG_ONLY_FLAKE)
    try:
        warm = dt.nix_run_warm_command("nix run .", d)
        print(f"       warm: {warm}")
        check("falls back to the plain package build", warm, "nix build . -L")
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("\nnix_run_warm_command — a non-`nix run` launch is left alone")
    check("binary launch returns None",
          dt.nix_run_warm_command("./result/bin/App --user-dir ./d", os.getcwd()),
          None)


print()
if failures:
    print(f"{len(failures)} check(s) FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all warm-step checks passed")
