# doctest, doctested: writing and running your first spec

This is `doctest` testing **itself**. Every command below is executed by the
outer `doctest run` against this file, and inside those commands we author a
*second* spec and run it with `doctest` — documentation all the way down.

By the end you will have written a minimal spec, executed it, watched its
assertions pass, and rendered it to Markdown — the core `run` / `generate`
loop that every other tutorial builds on.

> **The mental model.** A spec (`*.test.yaml`) is the single source of truth
> for a piece of documentation. `doctest run` *executes* it (writing files,
> running commands, checking output) so the docs are verified; `doctest
> generate` *renders* the same spec to a Markdown tutorial that is guaranteed
> to match what actually ran.

**What you'll build:** A tiny inner spec that you run and render with `doctest` itself.

**What you'll learn:**

- How to invoke the `doctest` CLI (via the published flake)
- The three core step types — `file`, `run`, and `check_file`
- How `expect_contains` turns a command's output into a pass/fail assertion
- How `doctest run` reports results, and what its exit code means
- How `doctest generate` renders the very same spec to Markdown

## Prerequisites

- **Nix** with flakes enabled. Install from [nixos.org](https://nixos.org/download.html), then enable flakes:

```bash
mkdir -p ~/.config/nix
echo 'experimental-features = nix-command flakes' >> ~/.config/nix/nix.conf
```

Verify: `nix flake --help >/dev/null 2>&1 && echo "Flakes enabled"`

- That is the *only* prerequisite. `doctest` itself is a single Python module;
the flake bundles Python + PyYAML, so you do not install anything else.

---

## Step 1: Meet the CLI

`doctest` has three subcommands: `run` (execute a spec), `generate` (render
it to Markdown), and `clean` (strip an executed tree back to source). You
invoke it through its flake — nothing to install.

### 1.1 Confirm doctest is reachable

Run the CLI with no arguments. It prints usage and exits non-zero, so we
append `|| true` to let the doc-test continue and assert on the banner:

```bash
doctest
```

Throughout this tutorial, `doctest …` in the rendered commands means
`nix run github:logos-co/logos-doctest -- …`.

---

## Step 2: Write your first spec

A spec is YAML with a top-level `name`, an `output` filename (used by
`generate`), and an ordered list of `sections`, each holding ordered
`steps`. We will write the smallest useful spec: it creates a file, reads
it back, and asserts on the output.

### 2.1 Create greeting.test.yaml

The `file` step writes a file during `run` (and shows it as a code block
when rendered). The `run` step executes a command; its `expect_contains`
list asserts that each string appears in the command's output. The
`check_file` step asserts a path exists.

```yaml
name: "A greeting"
output: greeting.md

intro: |
  The smallest useful spec: write a file, read it back, assert on it.

sections:
  - title: "Write and verify a greeting"
    step: true
    steps:
      - title: "Write greeting.txt"
        file:
          path: greeting.txt
          language: text
          content: |
            Hello from an inner spec!

      - title: "Read it back and assert"
        run: "cat greeting.txt"
        expect_contains:
          - "Hello from an inner spec!"

      - title: "Confirm the file exists"
        check_file: "greeting.txt"
```

Three step types, three jobs: `file` produces an artifact, `run`
exercises it, `check_file` confirms it. That is the whole core loop.

---

## Step 3: Run the spec

`doctest run` executes the spec in an isolated temporary directory, walking
sections and steps top to bottom and checking every assertion as it goes.

### 3.1 Execute it with --verbose

`--verbose` echoes each command as it runs. Watch for the `PASS` lines
and the final results summary:

```bash
doctest run greeting.test.yaml --verbose
```

Two steps asserted (the `run` and the `check_file`); the `file` step
writes without asserting. A run where every assertion holds exits `0`;
any failure makes `doctest run` exit non-zero, which is what lets CI
fail when the docs drift from reality.

---

## Step 4: Render the spec

The same spec that just *ran* can be *rendered* to a Markdown tutorial with
`doctest generate`. Because it is the identical file, the prose and the
commands in the docs cannot disagree with what executes.

### 4.1 Generate Markdown

Render `greeting.test.yaml` to `greeting.md`:

```bash
doctest generate greeting.test.yaml -o greeting.md
```

### 4.2 Confirm the Markdown was written

### 4.3 Inspect the rendered tutorial

The rendered file carries the spec's `name` as its title and the file's
contents as a fenced code block — the documentation, generated from the
thing that was just verified:

```bash
cat greeting.md
```

You have now closed the loop: one YAML file, executed for correctness
and rendered for humans. Every other `doctest` feature — chaining,
reports, the live TUI, release pinning — builds on exactly this.
