# logos-doctest

Executable documentation for the Logos projects (and any other project).

A `doctest` spec is a single YAML file (`*.test.yaml`) that is the **single
source of truth** for a piece of documentation. The same spec can be:

- **executed** (`doctest run`) — write files, run commands, assert on their
  output, build, inspect, and test, all in an isolated working directory, so the
  docs are *verified*, not just written;
- **rendered** (`doctest generate`) — turned into a Markdown tutorial;
- **cleaned** (`doctest clean`) — an output tree stripped of build artifacts so
  only the generated source remains.

The engine started life as the `logos-tutorial` tutorial runner and was extracted
here so any project can reuse it. See [`docs/spec.md`](docs/spec.md) for the full
spec format.

## Quick start

```bash
# Run the bundled, dependency-free example (writes a file, runs a command,
# asserts on output, checks a file exists)
nix run github:logos-co/logos-doctest -- run examples/hello.test.yaml --verbose

# Generate the Markdown version of a spec
nix run github:logos-co/logos-doctest -- generate examples/hello.test.yaml -o hello.md
```

Or, inside a checkout:

```bash
nix run .# -- run examples/hello.test.yaml --verbose
./bin/doctest run examples/hello.test.yaml --verbose   # nix-shell fallback wrapper
python3 doctest.py run examples/hello.test.yaml --verbose   # if PyYAML is installed
```

## Commands

```bash
doctest run <spec.yaml> [OPTIONS]        # execute a spec
doctest generate <spec.yaml> [-o out.md] # render markdown from a spec
doctest clean <dir> [OPTIONS]            # strip build artifacts from an output tree
```

Key `run` options (full list via `doctest run --help`):

| Flag | Effect |
|------|--------|
| `--output-dir DIR` | Run into `DIR` and keep it; chained specs land in `DIR/<project_name>/`. |
| `--workdir DIR` | Run standalone into an existing directory (no `requires:` chain). |
| `--keep-workdir` | Don't delete the temp working directory. |
| `--report PATH` | Write a two-column HTML report (rendered docs + commands run and their output). |
| `--tui` / `--iterative` | Live two-column terminal view; `--iterative` advances one step per keypress (needs `rich`). |
| `--release TAG` | Pin all `{release}` placeholders in GitHub URLs to a git tag. |
| `--continue-on-fail` | Don't stop at the first failure. |

`doctest clean` removes, by default, the artifacts a `run` leaves behind:
per-project `.git/`, nix out-links (`lm`, `logos`, `pm`, `result*`), installed
`modules/`, compiled libraries (`*.so`, `*.dylib`), `*.log`, machine-specific
`flake.lock`, and runner scratch `*.mjs`. Use `--keep GLOB` / `--also GLOB` to
adjust the set and `--dry-run` to preview.

## How it works

`doctest.py` walks the spec's sections and steps in order. A **step** may write a
`file`, execute a `run` command (with optional `expect_contains` assertions),
verify a `check_file`, or drive a headless `ui_test`. Specs can chain via
`requires:`, so a spec runs its prerequisites first in sibling subdirectories —
enabling cross-tutorial references.

The **core** (file/run/check_file, chaining, reporting, TUI, markdown generation)
is project-agnostic and needs only Python + PyYAML. A few **opt-in** integrations
target the Logos toolchain (`logoscore`, `basecamp`, and `ui_test` sections, nix
`build_overrides`, and the `{ext}`/`{shared_flags}`/`{release}` placeholders);
they are inert unless a spec uses them.

## Packaging

- `nix run github:logos-co/logos-doctest -- …` / `nix build .#doctest` —
  the pinned environment (Python + PyYAML + `rich` for `--tui`).
- `bin/doctest` — a fallback wrapper that runs directly when PyYAML is available,
  otherwise provides it via `nix-shell`.

The specs themselves invoke `nix`, `node`, `git`, etc. from the ambient
environment, so those are intentionally not baked into the package.

## Using it from another project

Point your project's docs tooling at the `doctest` CLI. For example,
`logos-tutorial` resolves it (env override → sibling workspace checkout →
published flake) in its `tools/run-tutorial` wrapper, then runs
`doctest run … --output-dir outputs/`, `doctest generate …`, and
`doctest clean outputs/`.
