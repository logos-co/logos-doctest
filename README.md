# logos-doctest

Executable documentation for the Logos projects — and any other project.

A `doctest` spec is a single YAML file (`*.test.yaml`) that is the **single source
of truth** for a piece of documentation. The same spec can be:

- **executed** (`doctest run`) — write files, run commands, assert on their output,
build, inspect, and test, all in an isolated working directory, so the docs are
*verified*, not just written; It can also interact with UI apps and record screenshots later used for the rendered documentation.
- **rendered** (`doctest generate`) — turned into a Markdown tutorial that is
guaranteed to match what actually runs;
- **cleaned** (`doctest clean`) — an executed output tree stripped of build
artifacts so only the generated source remains, ready to check in.

  
See `[docs/spec.md](docs/spec.md)` for the full spec format reference.

## Quick start

```bash
# Run the bundled, dependency-free example end-to-end (writes a file, runs a
# command, asserts on its output, checks a file exists).
nix run github:logos-co/logos-doctest -- run examples/hello.test.yaml --verbose

# Render the same spec to Markdown.
nix run github:logos-co/logos-doctest -- generate examples/hello.test.yaml -o hello.md

# Auto-advancing: steps run one after another.
doctest run examples/hello.test.yaml --tui

# Iterative: press the down/right arrow (or space) to execute each next step.
doctest run examples/hello.test.yaml --tui --iterative

# Create report showing side by side rendered markdown and what command was run in that step
doctest run examples/hello.test.yaml --report
```

Or, inside a checkout:

```bash
nix run .# -- run examples/hello.test.yaml --verbose
./bin/doctest run examples/hello.test.yaml --verbose      # nix-shell fallback wrapper
python3 doctest.py run examples/hello.test.yaml --verbose # direct, if PyYAML is installed
```

## Commands

```bash
doctest run <spec.yaml>... [OPTIONS]      # execute one or more specs, asserting as it goes
doctest generate <spec.yaml> [-o out.md]  # render Markdown from a spec
doctest clean <dir> [OPTIONS]             # strip build artifacts from an output tree
```

`run` accepts **multiple specs**: they execute back-to-back into a single
`--report`, which gets one dropdown entry per spec. This is how a repo with
several `*.test.yaml` files publishes one combined CI report instead of a
separate file per spec:

```bash
doctest run doctests/*.test.yaml --continue-on-fail --report report.html
```

(`--output-dir` and `--tui` operate on a single spec — pass just one.)

Run `doctest <command> --help` for the full option list. The most useful `run`
flags:


| Flag                    | Effect                                                                                                                                                                             |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--output-dir DIR`      | Run into `DIR` and **keep it** (created if missing, never auto-deleted). Chained specs land in `DIR/<project_name>/`. Use this when you want to inspect or reuse the built result. |
| `--workdir DIR`         | Run **standalone** into an existing directory (no `requires:` chain). Deleted on exit unless `--keep-workdir`.                                                                     |
| `--keep-workdir`        | Don't delete the temp/work directory after the run.                                                                                                                                |
| `--report PATH`         | Write a self-contained two-column HTML report (rendered docs ⟷ commands run and their output).                                                                                     |
| `--tui` / `--iterative` | Live two-column terminal view; `--iterative` advances one step per keypress. Needs `rich`.                                                                                         |
| `--release TAG`         | Pin every `{release}` placeholder in GitHub URLs to a git tag.                                                                                                                     |
| `--release-for REPO=REF`| Pin one repo's `{release}` to a git tag or commit hash (repeatable; overrides `--release` for that repo).                                                                          |
| `--continue-on-fail`    | Don't stop at the first failing step (capture the whole run).                                                                                                                      |
| `--verbose`             | Echo each command and its full output as it runs.                                                                                                                                  |


## How a spec is structured

A spec is a YAML document with an ordered list of **sections**, each containing
ordered **steps**. The engine walks them top to bottom; `run` executes each step
and `generate` renders it. A step is one of:

- `**file`** — write a file (its body is shown in the rendered tutorial as a code
block, and written to disk during `run`).
- `**run**` — execute a shell command. Optional `expect_contains` assertions check
its output; a missing string fails the step.
- `**check_file**` — assert a file exists.
- `**ui_test**` — drive a headless UI check (Logos integration; see below).

Specs can declare `requires:` to chain other specs — prerequisites run first, each
in its own sibling subdirectory, so a Part 3 tutorial can build on the modules
produced by Parts 1 and 2. The `examples/hello.test.yaml` spec is a minimal,
nix-free starting point; the `[docs/spec.md](docs/spec.md)` reference documents
every field.

## Where the results go (`run`)

If `--output-dir` is used then the results will go to the specified directory otherwise a temporary directory will be used.

- `--output-dir DIR` — run into `DIR` and **keep it** (created if missing, never
auto-deleted). This is the flag to use when you want to inspect or reuse the
built output. A spec with `requires:` treats `DIR` as the chain root and writes
each project into its own subdirectory:
  ```
  ./outputs/
  ├── project-a/    # a required prerequisite (built first)
  ├── project-b/    # another prerequisite
  └── project-c/    # the spec you ran
  ```
  A standalone spec (no `requires:`) is written directly into `DIR`.
- `--workdir DIR` — run into an **existing** directory. Unlike `--output-dir`, it
does not create the directory, it is deleted on exit unless you add
`--keep-workdir`, and it runs the spec **standalone** (prerequisite `requires:`
chains are skipped). Prefer `--output-dir` for chained specs.
- Without either flag, a temp directory is created and deleted after the run (add
`--keep-workdir` to preserve it).

## Reviewing what ran (`--report`)

`--report PATH` writes a self-contained HTML report with two columns per step:

- **left** — the rendered documentation markdown (identical to `doctest generate`),
- **right** — the command(s) actually executed at that step and their output, with
a pass/fail badge.

It covers every step type (file writes, shell commands, `check_file`, and headless
`ui_test` runs). Pair it with `--continue-on-fail` so the report captures the whole
run instead of stopping at the first failure — ideal for publishing from CI.

When a run includes multiple specs, the report's tutorial picker is deep-linkable:
append `#<tutorial-slug>` to the report URL (slug = lowercase name with non-alphanumerics
replaced by hyphens) to open a specific tutorial directly.

## Watching it live (`--tui`)

`--tui` runs the same two-column view live in your terminal instead of writing a
file: the left pane shows the rendered docs for the current step, the right pane
shows the command being run and its output, updating as the run proceeds.

```bash
# Auto-advancing: steps run one after another.
doctest run examples/hello.test.yaml --tui

# Iterative: press the down/right arrow (or space) to execute each next step.
doctest run examples/hello.test.yaml --tui --iterative
```

Press `q` to quit at any time. `--tui` needs an interactive terminal and the
`[rich](https://github.com/Textualize/rich)` package — both are bundled in the
doctest flake, so no extra install is needed when running via `nix`.

## Pinning releases (`--release`)

`--release TAG` (or a `release:` field in the spec) pins every `{release}`
placeholder in GitHub URLs to a git tag, so `github:logos-co/repo{release}#output`
becomes `github:logos-co/repo/<TAG>#output`. Set it to `""` or omit it for the
latest. This lets one spec render either bleeding-edge or pinned-to-a-release
instructions without editing the URLs by hand.

### Pinning a single repo (`--release-for`)

`--release-for REPO=REF` overrides the `{release}` ref for **one** GitHub repo,
where `REF` is a git tag **or a commit hash**. It's repeatable and wins over
`--release` (and the spec's `release:`) for that repo only; every other URL still
uses the global release. An empty ref (`--release-for REPO=`) forces that repo to
latest even when a global release is set.

```bash
# Everything from tutorial-v2, but build logos-logoscore-cli at a specific commit
doctest run spec.yaml --release tutorial-v2 \
  --release-for logos-logoscore-cli=abc123def

# Pin two repos to different refs, no global release
doctest run spec.yaml \
  --release-for logos-logoscore-cli=abc123def \
  --release-for logos-basecamp=my-branch
```

The canonical use case is CI: when testing a single repo's PR against the rest of
the released stack, pass `--release-for <that-repo>=$GITHUB_SHA` so the spec
builds the commit under test while every other URL stays pinned to the release.

Per-repo pins can also live in the spec under `release_overrides:` (a
`{repo: ref}` map); CLI `--release-for` flags override the spec on conflicts:

```yaml
release: tutorial-v2
release_overrides:
  logos-logoscore-cli: abc123def
```

## Cleaning an output tree (`clean`)

`doctest clean <dir>` strips the artifacts a `run` leaves behind, so an executed
`--output-dir` tree can be committed as clean source. By default it removes:

- per-project `.git/` directories (specs that `git init` their project),
- nix out-links (`lm`, `logos`, `pm`, `result`, `result-*`),
- installed `modules/` directories,
- compiled libraries (`*.so`, `*.dylib`) and `*.log` files,
- machine-specific `flake.lock` files,
- runner scratch (`*.mjs`).

Adjust the set and preview before deleting:

```bash
doctest clean ./outputs --dry-run      # show what would be removed
doctest clean ./outputs --keep '*.log' # keep logs
doctest clean ./outputs --also '*.tmp' # also remove an extra glob
doctest clean ./outputs --verbose      # list each removal
```

This makes the "produce a clean, checked-in output tree" workflow reusable by any
project — see the `logos-tutorial` `run.sh` for an end-to-end example
(`run` → `generate` → `clean`).

## What's generic vs. Logos-specific

The **core** is project-agnostic and needs only Python + PyYAML:

- the `file` / `run` / `check_file` steps and their assertions,
- `requires:` chaining and `--output-dir` layout,
- Markdown generation, the HTML `--report`, and the `--tui`,
- `clean`.

A few **opt-in** integrations target the Logos toolchain and are **inert unless a
spec uses them**:

- `logoscore:` / `basecamp:` sections (drive the Logos module runtime and app),
- `ui_test:` steps (headless UI checks via logos-qt-mcp),
- nix `build_overrides:` (injected as `--override-input` flags),
- the `{ext}` / `{shared_flags}` / `{release}` placeholders.

A spec that uses none of these is fully portable; the core engine never references
them.

## Packaging

- `nix run github:logos-co/logos-doctest -- …` / `nix build .#doctest` — the pinned
environment (Python + PyYAML + `rich` for `--tui`). This is the recommended way
to invoke it; nothing else needs installing.
- `bin/doctest` — a fallback wrapper that runs `doctest.py` directly when PyYAML is
importable, otherwise provides it via `nix-shell`. Handy when you don't want to
go through the flake.
- `python3 doctest.py …` — the engine itself, if you already have PyYAML (and,
optionally, `rich`) on your `PATH`.

The specs themselves invoke `nix`, `node`, `git`, etc. from the ambient
environment, so those are intentionally **not** baked into the package — `doctest`
provides the runner, not your toolchain.

## Using it from another project

Point your project's docs tooling at the `doctest` CLI. The recommended pattern is
a tiny wrapper that resolves the CLI in priority order so it works for both local
development (a sibling checkout) and CI (the published flake):

1. `$LOGOS_DOCTEST` — an explicit override (path or command),
2. a sibling workspace checkout (`../logos-doctest`, run via `python3 doctest.py`
  if PyYAML is present, else `bin/doctest`),
3. the published flake — `nix run github:logos-co/logos-doctest -- …`.

`logos-tutorial` does exactly this in its `tools/run-tutorial` wrapper, then calls:

```bash
run-tutorial run    tests/<spec>.test.yaml --output-dir outputs/ --continue-on-fail
run-tutorial generate tests/<spec>.test.yaml -o outputs/<spec>.md
doctest      clean  outputs/
```

Keep your specs in a `tests/` (or `docs/`) directory, the rendered Markdown in
`outputs/`, and let CI run `doctest run` on every push so the docs stay honest.

## Repository layout

```
logos-doctest/
├── doctest.py                 # the engine (run / generate / clean)
├── flake.nix                  # packages.default + apps.default = the `doctest` CLI
├── bin/doctest                # nix-shell fallback wrapper
├── docs/spec.md               # canonical spec format reference
├── examples/hello.test.yaml   # minimal, nix-free example spec
├── doctests/                  # doctest documenting itself (run by CI)
│   ├── 01-getting-started.test.yaml        # the run / generate loop
│   ├── 02-generate-and-report.test.yaml    # code_block, extra_run, --report, --tui
│   ├── 03-chaining-and-clean.test.yaml     # requires:, --output-dir, --workdir, clean
│   ├── 04-multispec-and-releases.test.yaml # combined reports, {release}, --release-for
│   ├── 05-more-spec-features.test.yaml     # encoding:base64, comparison, build_overrides, ui_test
│   └── run.sh                              # run + generate the suite locally
└── .github/workflows/ci.yml   # self-test: example + the doctests/ suite
```

### Self-documenting tutorials (`doctests/`)

The specs under `doctests/` are an **inception**: `doctest` specs that teach how
to use `doctest`, executed by `doctest` itself in CI. Each is a step-by-step
tutorial that writes a smaller inner spec, runs it, and asserts on the result, so
the tool's own documentation cannot drift from its behaviour. Run the whole suite
locally with `doctests/run.sh` (or render it with `doctest generate`). They are
also the most complete worked examples of the features above.

## License

Dual-licensed under [Apache 2.0](LICENSE-APACHE-v2) or [MIT](LICENSE-MIT), at your
option.