# Rendering, reports, and failures

The first tutorial covered the `run` / `generate` loop. This one goes deeper on
the *rendering* side: how to show readers a clean command while executing a
different one (`code_block`), how to capture an entire run as a shareable HTML
**report**, and how `--continue-on-fail` changes what happens when an assertion
fails. As before, every command here is run by the outer `doctest`, and inside
it we author and drive a second spec.

**What you'll build:** A spec with display-only command blocks, plus an HTML report of a run that contains a deliberate failure.

**What you'll learn:**

- How `code_block` shows a tidy command while `run` executes the real one
- How `post_text` adds explanation after a step's action
- How `--report` writes a self-contained two-column HTML report
- How a failing `expect_contains` is reported, and its effect on the exit code
- How `--continue-on-fail` walks the whole spec instead of stopping early
- How `--tui` / `--iterative` show the same view live in the terminal

## Prerequisites

- **Nix** with flakes enabled (see the first tutorial). The `doctest` flake
bundles everything else.

---

## Step 1: Display vs. execution with code_block (and extra_run)

During `run`, a step's `run:` value is what executes. But the command that
is convenient to *run* is not always the one that is clearest to *read* — a
run might use an absolute path, a `|| true` guard, or shell plumbing. The
`code_block:` field overrides what `generate` shows, while `run:` stays the
thing that executes. A step can also carry an `extra_run:` — a *second*
command (with its own `run` / `code_block` / `post_text`) rendered under the
same heading, ideal for a "do X, then verify X" pair.

### 1.1 Write a spec that separates display from execution

The inner step *runs* a command with extra shell noise but *renders* a
clean one, with `post_text` after it. Its `extra_run` adds a follow-up
command under the same heading — no new `### ` title.

```yaml
name: "Rendering details"
output: render.md

sections:
  - title: "A friendly command"
    step: true
    steps:
      - title: "Print the date"
        run: "date '+%Y' > /dev/null && echo 'the year is now'"
        code_block: "date '+%Y'"
        expect_contains:
          - "the year is now"
        post_text: |
          The command above is what readers see; the spec actually ran
          a slightly different line to keep this example deterministic.
        extra_run:
          run: "echo 'and the follow-up ran too'"
          expect_contains:
            - "follow-up ran too"
          post_text: |
            This second command came from `extra_run`, under the same
            step heading.
```

### 1.2 Run it (executes both the command and its extra_run)

```bash
doctest run render.test.yaml --verbose
```

The summary shows **two** passes for one step: the main `run` and the
`extra_run` (logged as `… (verify)`).

### 1.3 Generate it (shows the clean commands)

In the rendered Markdown the code block is the *display* command, the
`post_text` follows it, and the `extra_run` command appears under the
same heading — the executed plumbing never leaks into the docs:

```bash
doctest generate render.test.yaml -o render.md
```

Note that `date '+%Y' > /dev/null && echo …` (the executed line) does
**not** appear — only the `code_block` does — and the `extra_run` command
renders inline, with no separate heading of its own.

---

## Step 2: Capture a run as an HTML report

`--report PATH` writes a self-contained HTML file with two columns per step:
the rendered documentation on the left, and the commands actually executed
plus their output (with pass/fail badges) on the right. It is the artifact
CI publishes so reviewers can see exactly what ran.

### 2.1 Produce a report

```bash
doctest run render.test.yaml --report report.html
```

### 2.2 Confirm the report file exists

### 2.3 Peek at the report

The report is a standalone HTML document titled for the run:

```bash
grep 'Tutorial Execution Report' report.html
```

---

## Step 3: What happens when an assertion fails

A spec is only useful if it actually fails when reality disagrees with the
docs. Here we write a spec whose assertion is wrong on purpose, then observe
two behaviors: the default **fail-fast**, and `--continue-on-fail`.

### 3.1 Write a spec with a wrong assertion

```yaml
name: "Deliberately broken"
output: broken.md

sections:
  - title: "Mismatched expectation"
    step: true
    steps:
      - title: "Echo one thing, expect another"
        run: "echo hello"
        expect_contains:
          - "this string is not in the output"
      - title: "A second step (only reached with --continue-on-fail)"
        run: "echo second-step-ran"
        expect_contains:
          - "second-step-ran"
```

### 3.2 Run it — the failure is reported and the exit code is non-zero

We add `|| true` so this doc-test can continue past the inner failure and
assert on the `FAIL` line. The inner `doctest` still exits non-zero — that
non-zero exit is exactly what fails a CI job:

```bash
doctest run broken.test.yaml --continue-on-fail
```

With `--continue-on-fail`, the runner walked **both** inner steps: the
first failed and the second still ran and passed — the summary
`1 passed, 1 failed` proves it reached the second step. Without that
flag, `doctest run` stops at the first failure (fail-fast), the right
default for local iteration; `--continue-on-fail` is what you want in CI
so the report captures the whole run.

---

## Watching a run live (--tui / --iterative)

The `--report` HTML is written *after* a run finishes. When you want the same
two-column view **live in the terminal as it runs**, use `--tui`:

```bash
doctest run examples/hello.test.yaml --tui
```

The left pane renders the current step's documentation, the right pane shows
the command executing and its output, updating as the run proceeds. Add
`--iterative` to advance one step at a time, waiting for a keypress (the
down/right arrow, or space) before each step; press `q` to quit:

```bash
doctest run examples/hello.test.yaml --tui --iterative
```

Two things to know:

- `--tui` needs an **interactive terminal** (a TTY) and the
  [`rich`](https://github.com/Textualize/rich) package. Both are bundled in
  the doctest flake, so `nix run … -- run … --tui` works out of the box; run
  with a piped/redirected stdout (as CI does) and doctest tells you a TTY is
  required instead of drawing the UI.
- `--iterative` only applies together with `--tui` — using it alone is an
  error.

Because the TUI requires a real terminal, this section is **documentation
only**: unlike every other step in these tutorials, the commands above are
not executed by the doc-test runner (which runs head-less in CI). Everything
`--tui` shows is the exact same rendered docs and executed commands you get
from `generate` and `--report` — only the presentation is live.
