# The rest of the spec format: binary files, comparison, and Logos hooks

The first four tutorials cover the features you reach for daily. This one is a
guided tour of the **remaining** spec fields: binary `file` content via
`encoding: base64`, the top-level `comparison` block (this very tutorial uses
one — see just below its learning objectives), the `release_overrides` spec
field, and the opt-in Logos integrations. Of those, `build_overrides` *is*
exercised for real (its flag-injection needs no toolchain); `ui_test` needs a
running Qt app, so it appears as a clearly-labelled reference snippet rather
than an executed example.

**What you'll build:** A spec that round-trips a binary file and one that proves build_overrides injects a Nix flag, plus a reference for ui_test.

**What you'll learn:**

- {'How `encoding': 'base64` writes binary files and renders them as a note'}
- What the top-level `comparison` field is for (you are reading one)
- How the `release_overrides` spec field mirrors `--release-for`
- How `build_overrides` injects `--override-input` into `nix build` commands
- What a `ui_test` step looks like for headless Qt UI checks (reference only)

**Why a `comparison` block?** It is a free-form Markdown region rendered right
after *What you'll learn*, before the first section — handy for a table or a
paragraph that frames the tutorial (for instance, contrasting two approaches).
This paragraph is itself the `comparison:` field of this spec.

## Prerequisites

- **Nix** with flakes enabled (see the first tutorial). The binary-file section
runs anywhere; the Logos sections are reference-only.

---

## Step 1: Binary files with encoding: base64

A `file` step usually carries plain-text `content`. For binary artifacts
(images, compiled blobs, fixtures) set `encoding: base64` and put the
base64 of the bytes in `content`. On `run`, doctest decodes it to disk; on
`generate`, instead of dumping bytes it renders a `*Binary file: \`path\`*`
note.

### 1.1 Write a spec that emits a binary file

The base64 below decodes to the ASCII bytes `doctest-binary-ok`. The
inner spec writes them, then reads them back to prove the round-trip:

```yaml
name: "Binary file demo"
output: binary.md
sections:
  - title: "Round-trip a binary blob"
    step: true
    steps:
      - title: "Write blob.bin from base64"
        file:
          path: blob.bin
          encoding: base64
          content: |
            ZG9jdGVzdC1iaW5hcnktb2s=
      - title: "Read the decoded bytes back"
        run: "cat blob.bin"
        expect_contains:
          - "doctest-binary-ok"
```

### 1.2 Run it — the bytes round-trip

The inner spec decodes `blob.bin` and reads it back; its `expect_contains`
asserts the decoded text, so a passing summary means the round-trip held:

```bash
doctest run binary.test.yaml --verbose
```

### 1.3 Generate it — the binary renders as a note

`generate` never dumps raw bytes into the Markdown; it emits a short
note pointing at the file instead:

```bash
doctest generate binary.test.yaml -o binary.md
```

So a spec stays readable even when it ships fixtures — the bytes live in
`content`, the docs show a tidy reference.

---

## Step 2: Per-repo release pins in the spec (release_overrides)

Tutorial 4 pinned a single repo from the CLI with `--release-for
REPO=REF`. The same thing can live **in the spec** under a top-level
`release_overrides:` map, so a spec carries its own per-repo defaults; a CLI
`--release-for` still wins on conflicts. We confirm doctest accepts the
field by generating a spec that declares it.

### 2.1 Write a spec carrying release_overrides

```yaml
name: "Override demo"
output: overrides.md
release: "demo-v1"
release_overrides:
  logos-module-builder: "abc123def"
sections:
  - title: "Just framing"
    step: true
    steps:
      - title: "A note"
        text: "This spec pins logos-module-builder to a commit by default."
```

### 2.2 Generate it (the field is accepted and the doc renders)

```bash
doctest generate overrides.test.yaml -o overrides.md
```

At run time, any `github:logos-co/logos-module-builder` URL in
that spec would resolve to `/abc123def`, while every other repo would use
the spec's global `release: demo-v1` — exactly like passing
`--release-for logos-module-builder=abc123def --release demo-v1` on the
command line.

---

## Step 3: build_overrides: inject Nix --override-input flags

`build_overrides` is a top-level map that injects `--override-input` flags
into every command containing `nix build`, so a tutorial can build against a
local checkout instead of the pinned flake input. Keys are input names,
values are paths relative to the spec. It only affects **execution**;
`generate` ignores it, so the published docs keep the clean commands.

Unlike `ui_test` below, this *is* executable without the Logos toolchain —
the injection is pure string rewriting — so we prove it for real. We point
an override at a local directory and assert that the flag is spliced into a
`nix build` command.

### 3.1 Create the directory the override points at

The override path must exist on disk, or the runner emits a warning and
skips it. A bare directory is enough for this demonstration:

```bash
mkdir -p ./fake-sdk
```

### 3.2 Write a spec that declares build_overrides

```yaml
name: "build_overrides demo"
output: ob.md
build_overrides:
  logos-cpp-sdk: ./fake-sdk
sections:
  - title: "A build command"
    step: true
    steps:
      - title: "Run a nix build (echoed, not really built)"
        run: "echo 'nix build .#demo'"
        expect_contains:
          - "--override-input logos-cpp-sdk"
```

### 3.3 Run it — the override flag is injected

The inner spec's command is `echo 'nix build .#demo'`. Because it
contains `nix build`, the runner appends the override flag before
executing — and the inner `expect_contains` asserts the flag is present,
so a passing summary proves the injection happened:

```bash
doctest run overrides-build.test.yaml --verbose
```

The executed command became
`echo 'nix build .#demo' --override-input logos-cpp-sdk path:…/fake-sdk`.
In a real tutorial the value would be a sibling checkout
(e.g. `../logos-cpp-sdk`) so `nix build` resolves against your local
code; `generate` would still render the plain `nix build .#demo`.

---

## ui_test: headless Qt UI checks (reference only)

The last feature, `ui_test`, drives a **real Qt application** through
[logos-qt-mcp](https://github.com/logos-co/logos-qt-mcp): it launches the app
with `QT_QPA_PLATFORM=offscreen`, connects to the QML inspector, performs UI
actions (`click`, `wait_for`, `expect_texts`, `set_text`, `sleep`), and can
capture a `screenshot` that the generated docs embed inline.

Because it needs a built Qt app and the qt-mcp package, it **cannot run in
this generic, toolchain-free self-test** — so unlike `build_overrides` above,
the block below is a **reference snippet, not an executed example**. It is the
shape of a real `ui_test` step (taken from the `logos-tutorial` QML app
tutorial); for a version that actually runs, see that repo's specs and the
full action reference in `docs/spec.md`.

```yaml
- ui_test:
    launch: "nix run ."
    setup:
      - "nix build 'github:logos-co/logos-qt-mcp' -o result-mcp"
    qt_mcp: "result-mcp"
    tests:
      - name: "Window opens"
        action: wait_for
        texts: ["Logos Calculator"]
        timeout: 15000
      - name: "Click Add"
        action: click
        target: "Add"
        screenshot: "after-add.png"
```

Everything else across these five tutorials needs only Python + PyYAML and
runs anywhere; `ui_test` is the one feature that requires the Logos UI stack.
