# Combined reports and release pinning

The final tutorial covers the two features you reach for when wiring `doctest`
into a real project's CI: running **several specs into one report** (so a repo
with many `*.test.yaml` files publishes a single artifact with a dropdown), and
the **`{release}` placeholder** that lets one spec target either bleeding-edge
or a pinned release of the repos it builds. We demonstrate both from inside this
spec.

**What you'll build:** Two inner specs rendered into a single combined HTML report, plus a spec that pins a GitHub URL via {release}.

**What you'll learn:**

- How `doctest run a.yaml b.yaml --report r.html` combines specs into one report
- Why the combined report has a per-spec dropdown (one entry per spec)
- How the `{release}` placeholder expands in `run` commands and rendered docs
- How `--release TAG` overrides the spec's `release:` field at the CLI
- How `--release-for REPO=REF` pins a single repo to a tag or commit
- The recommended `tests/` + `outputs/` project layout for keeping docs honest

## Prerequisites

- **Nix** with flakes enabled (see the first tutorial).

---

## Step 1: Two specs, one report

A repo usually has more than one spec. Passing them all to a single `doctest
run` executes them back-to-back into one `--report`, whose top-right dropdown
switches between them — far tidier than one HTML file per spec.

### 1.1 Write two small specs

Two independent specs, each a single passing assertion:

```yaml
name: "Alpha"
output: alpha.md
sections:
  - title: "Alpha check"
    step: true
    steps:
      - title: "Echo alpha"
        run: "echo alpha-ok"
        expect_contains:
          - "alpha-ok"
```

### 1.2 Write the second spec

```yaml
name: "Beta"
output: beta.md
sections:
  - title: "Beta check"
    step: true
    steps:
      - title: "Echo beta"
        run: "echo beta-ok"
        expect_contains:
          - "beta-ok"
```

### 1.3 Run both into a single report

Pass both specs to one `run`. They execute in order and share one report
file. `--continue-on-fail` is the CI-friendly choice so the report is
complete even if a spec fails:

```bash
doctest run alpha.test.yaml beta.test.yaml --continue-on-fail --report combined.html
```

### 1.4 Confirm the combined report exists

### 1.5 Both specs are in the dropdown

The report's spec picker is populated from the embedded run data — one
entry per spec. Both names are present in the single file:

```bash
grep -o 'Alpha\|Beta' combined.html | sort -u
```

One report, two dropdown entries. (`--output-dir` and `--tui`, by
contrast, operate on a single spec — pass just one to those.)

---

## Step 2: Pinning versions with the {release} placeholder

Specs that build GitHub repos often want to target a specific release rather
than the latest commit. Anywhere a `run` command, `code_block`, or file body
contains the release placeholder, `doctest` expands it — to `/TAG` when a
release is set, or to nothing when it is empty — so one spec can render either
bleeding-edge or pinned instructions without editing URLs by hand.

A spec author writes a flake reference such as
`github:logos-co/logos-module-builder` followed by the placeholder and
`#with-external-lib`. With no release it stays bare; with `--release demo-v1`
it becomes `github:logos-co/logos-module-builder/demo-v1#with-external-lib`.
Below we prove both, from inside this spec.

### 2.1 Write an inner spec that uses the placeholder

We generate the inner spec with a heredoc rather than a `file` step. Why?
This outer step is *itself* placeholder-expanded, so a literal token typed
here would be substituted by the **outer** run before the inner spec ever
saw it. Assembling the braces from a shell variable (`LB='{'`) sidesteps
that: the written file ends up with a real placeholder for the **inner**
run to expand.

```bash
# Write pinned.test.yaml. LB/RB assemble the brace token so the OUTER
# run leaves it intact; the written file gets a real placeholder for the
# inner run to expand. We reference two repos so the per-repo pin below
# has something to distinguish.
LB='{'; RB='}'
cat > pinned.test.yaml <<EOF
# ...
run: "echo 'github:logos-co/logos-module-builder${LB}release${RB}#with-external-lib
             github:logos-co/logos-liblogos${LB}release${RB}'"
# ...
EOF
```

The written `pinned.test.yaml` now holds a real release placeholder in its
`run:` command for **two** repos — put there without the outer run
substituting them.

### 2.2 Confirm the inner spec was written

### 2.3 Run the inner spec with no release

With no release set, the placeholder expands to an empty string and the
URL points at the default branch:

```bash
doctest run pinned.test.yaml --verbose
```

### 2.4 Run the inner spec with --release

`--release TAG` overrides the spec's `release:` field for the whole run,
so **every** placeholder now expands to `/TAG` — both repos move together:

```bash
doctest run pinned.test.yaml --release demo-v1 --verbose
```

Both URLs picked up `/demo-v1` from the single `--release` flag.

### 2.5 Pin one repo to a commit with --release-for

Often you want most repos at a release but **one** at a specific commit —
for example, a repo's own CI building the exact commit under test while
everything else stays on the published release. `--release-for REPO=REF`
does that: `REF` is a git tag **or a commit hash**, it is repeatable, and
it overrides `--release` for that one repo only. Here `logos-module-builder`
is pinned to a commit while `logos-liblogos` keeps the global `demo-v1`:

```bash
doctest run pinned.test.yaml --release demo-v1 --release-for logos-module-builder=abc123def --verbose
```

One spec, per-repo control: `logos-module-builder` resolved to the commit
`abc123def`, while `logos-liblogos` stayed on `demo-v1`. This is exactly
how a repo's CI tests *its* commit against the rest of the released stack
(`--release-for <that-repo>=$GITHUB_SHA`); an empty ref —
`--release-for REPO=` — forces a single repo back to latest even when a
global `--release` is set.

---

## Putting it together in a project

The pattern these four tutorials demonstrate is exactly how a real repo wires
`doctest` into CI:

- Keep specs in a `doctests/` (or `tests/`) directory, one `*.test.yaml` per
  topic, each both runnable and renderable.
- In CI, run them all into one report:
  `doctest run doctests/*.test.yaml --continue-on-fail --report report.html`,
  publish the HTML, and let the non-zero exit fail the job when the docs
  drift from the code.
- Render the committed Markdown with `doctest generate`, and strip executed
  output trees with `doctest clean` before checking them in.

This very directory is that pattern applied to `doctest` itself: the specs
here are run by `doctest` in CI, and the tool's own documentation is verified
by the tool. Inception complete.
