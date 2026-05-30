# Chaining specs and cleaning the output tree

Real tutorials often come in parts: Part 2 builds on what Part 1 produced. This
tutorial shows how `requires:` chains specs so a prerequisite runs first in its
own directory, how `--output-dir` lays the chain out on disk, and how `doctest
clean` strips an executed tree back to checked-in source. As always, we drive
inner specs from inside this one.

**What you'll build:** A two-spec chain (a base spec and one that consumes its output), run into a directory you can inspect, then cleaned.

**What you'll learn:**

- How `requires:` declares prerequisite specs, run before the spec that needs them
- Why chained specs need a `project_name`, and how it names their subdirectory
- How a later spec references an earlier one's output (`../<project_name>/…`)
- How `--output-dir` keeps the result on disk instead of a temp dir
- How `--workdir` / `--keep-workdir` run a single spec into an existing directory
- How `doctest clean` removes build artifacts, with `--dry-run` and `--keep`

## Prerequisites

- **Nix** with flakes enabled (see the first tutorial).

---

## Step 1: A base spec to build on

Chaining is keyed on `project_name`: each spec in a chain runs in a sibling
directory named by its `project_name`. We start with a base spec that simply
produces a marker file other specs can consume.

### 1.1 Write base.test.yaml

Note the `project_name: base-project` — without it, a spec that
participates in a chain is an error.

```yaml
name: "Base project"
output: base.md
project_name: base-project

sections:
  - title: "Produce an artifact"
    step: true
    steps:
      - title: "Write a marker file"
        file:
          path: artifact.txt
          language: text
          content: |
            built-by-base-project
```

---

## Step 2: A spec that requires the base

The second spec declares `requires: [base.test.yaml]`. When you run it,
`doctest` runs the base first (in `base-project/`), then this spec (in
`consumer-project/`), so it can read the base's output through the sibling
path `../base-project/`.

### 2.1 Write consumer.test.yaml

```yaml
name: "Consumer project"
output: consumer.md
project_name: consumer-project

requires:
  - base.test.yaml

sections:
  - title: "Use the base's artifact"
    step: true
    steps:
      - title: "Read the sibling project's output"
        run: "cat ../base-project/artifact.txt"
        expect_contains:
          - "built-by-base-project"
```

`requires:` is resolved **transitively** and de-duplicated: if A requires
B and B requires C, running A runs C, then B, then A, each once.

---

## Step 3: Run the chain into a directory you keep

By default a run uses a temp directory that is deleted afterwards. With
`--output-dir DIR`, the directory is created (if missing) and **kept**, and
for a chain it becomes the chain root with one subdirectory per project.

### 3.1 Run the consumer (the base runs first)

```bash
doctest run consumer.test.yaml --output-dir ./chain-out
```

Both specs ran: the base produced its artifact (a `file` step, which
writes without asserting), then the consumer read it back across the
project boundary and asserted on it — the one `PASS` in the summary.

### 3.2 Inspect the on-disk layout

The chain root holds one directory per `project_name`, each with that
project's files:

```bash
find ./chain-out -maxdepth 2 -type f
```

---

## Step 4: Running into an existing directory (--workdir)

`--output-dir` is the chain-aware option: it *creates* the directory, keeps
it, and lays out one subdirectory per project. `--workdir` is the simpler
sibling for a **single** spec: it runs into a directory that **must already
exist**, ignores any `requires:` chain, and — unlike `--output-dir` — deletes
that directory on exit *unless* you add `--keep-workdir`.

### 4.1 Write a standalone spec

A one-step spec with no `requires:` — just produces a file:

```yaml
name: "Solo spec"
output: solo.md
sections:
  - title: "Produce a file"
    step: true
    steps:
      - title: "Write output.txt"
        file:
          path: output.txt
          language: text
          content: |
            produced-in-workdir
      - title: "Verify it"
        run: "cat output.txt"
        expect_contains:
          - "produced-in-workdir"
```

### 4.2 Run into a pre-created directory, keeping it

`--workdir` does not create the directory, so we `mkdir` it first.
`--keep-workdir` stops doctest from deleting it on exit, so we can
inspect the result:

```bash
mkdir -p ./my-workdir
doctest run solo.test.yaml --workdir ./my-workdir --keep-workdir
```

### 4.3 Confirm the directory was kept with its output

Because of `--keep-workdir`, the directory and the file the spec produced
are still there:

```bash
cat ./my-workdir/output.txt
```

Without `--keep-workdir`, doctest would have deleted `./my-workdir` (and
everything in it) when the run finished — handy for a throwaway check
against a directory you already have, but use `--output-dir` (or add
`--keep-workdir`) whenever you want to keep the result.

---

## Step 5: Clean the executed tree

An executed `--output-dir` tree mixes generated source with build artifacts
(out-links, compiled libraries, `modules/`, logs). `doctest clean` removes
the artifacts so what remains is committable source. Preview first with
`--dry-run`, and spare specific patterns with `--keep`.

### 5.1 Add some artifacts to clean

Simulate what a real build leaves behind:

```bash
touch result libdemo.so build.log   # leftover build artifacts
```

### 5.2 Preview removals with --dry-run

`--dry-run` lists what *would* be removed without touching anything:

```bash
doctest clean ./chain-out --dry-run
```

### 5.3 Clean for real, keeping logs

Now remove the artifacts but keep `*.log` files with `--keep`. The
out-link and the compiled library go; the log stays:

```bash
doctest clean ./chain-out --keep '*.log' --verbose
```

### 5.4 Confirm what survived

The generated source and the kept log remain; the build artifacts are
gone — a tree you could check in as-is:

```bash
find ./chain-out -type f
```

`result` and `libdemo.so` are no longer listed: `clean` removed them,
`--keep '*.log'` preserved `build.log`, and the real source survived.
