# Running doc-tests in CI and publishing reports to GitHub Pages

The previous tutorial wrapped a repo's specs in a `run.sh`. This one takes the
same two calls — `doctest run` and `doctest generate` — and wires them into
**GitHub Actions**, then publishes the two-column HTML **report** to **GitHub
Pages** with a clickable link on every pull request. The result is the workflow
shared, almost verbatim, by
[`logos-package-manager`](https://github.com/logos-co/logos-package-manager/blob/master/.github/workflows/doctests.yml),
[`logos-liblogos`](https://github.com/logos-co/logos-liblogos/blob/master/.github/workflows/doctests.yml),
and [`logos-tutorial`](https://github.com/logos-co/logos-tutorial/blob/master/.github/workflows/ci.yml).

We can't launch GitHub Actions from inside a doc-test, so the workflow YAML here
is a **reference you write to disk and inspect** rather than an executed job. But
the command at the heart of it — the one that produces the publishable
`index.html` report — *is* run for real, against an inner spec, so you see the
exact artifact CI uploads.

**What you'll build:** The report-producing command CI runs (executed for real) plus a complete, annotated GitHub Actions workflow that publishes the report to GitHub Pages.

**What you'll learn:**

- Which single `doctest run … --report index.html` command CI uses, and why
- Why all specs go through one `run` invocation (one combined report, one dropdown)
- How `--release-for $SHA` makes CI test the commit under test, not latest master
- The two-job workflow shape — test (matrix) then publish — and what each does
- How `peaceiris/actions-gh-pages` publishes per-PR report directories to Pages
- The one-time repo setting that turns on the gh-pages site, and the fork caveat

## Prerequisites

- **Nix** with flakes enabled (see the first tutorial). The executed section
needs only the `doctest` flake; the workflow section is reference YAML.

- A repo with a `doctests/` directory of `*.test.yaml` specs (Tutorial 6) whose
GitHub Actions you can enable.

---

## Step 1: The command CI actually runs

Strip the workflow down and one command does the real work: a **single**
`doctest run` over *all* specs, writing a combined HTML report named
`index.html`. Passing every spec to one invocation is deliberate — the report
gets a top dropdown that switches between specs; running one spec per
invocation would emit a separate file each and lose the dropdown. Naming it
`index.html` means the published directory URL renders it directly.

### 1.1 Write a spec for CI to run

A tiny spec so the report has real content:

```yaml
name: "CI demo"
output: ci-demo.md
sections:
  - title: "A step CI will report on"
    step: true
    steps:
      - title: "Emit a line and assert on it"
        run: "echo built-in-ci"
        expect_contains:
          - "built-in-ci"
```

### 1.2 Produce the combined report exactly as CI does

This is the workflow's core step, verbatim except for the report path:
one `run`, every `*.test.yaml`, `--continue-on-fail` so the report
captures the whole run, and `--report …/index.html`. (`--release-for` is
added in the real workflow; we cover it below.)

```bash
mkdir -p "${{ runner.temp }}/reports"
nix run github:logos-co/logos-doctest -- run \
  doctests/*.test.yaml \
  --verbose \
  --continue-on-fail \
  --release-for "myrepo=${{ steps.commit.outputs.sha }}" \
  --report "${{ runner.temp }}/reports/index.html"
```

`--continue-on-fail` makes the run walk every step so the published report
is complete; the command still exits non-zero if any step failed, which is
what fails the CI job. The displayed command shows the production form —
`doctests/*.test.yaml` and the `--release-for` pin explained below.

### 1.3 Confirm the publishable report exists

### 1.4 It is the self-contained two-column report

The same report Tutorial 2 introduced: rendered docs on the left, the
commands actually run and their output on the right — a single HTML file,
ready to upload as-is:

```bash
grep 'Tutorial Execution Report' reports/index.html
```

---

## Step 2: Testing the commit under test (--release-for)

A repo whose specs build *itself* (`nix build 'github:logos-co/<repo>'`)
hits the same issue Tutorial 6 raised: that URL resolves to **latest
master**, not the commit CI is testing. The workflow resolves the commit and
passes `--release-for <repo>=$SHA` so the doc-tests build exactly that commit
while every other URL stays on its release. One subtlety makes it robust on
forks:

### 2.1 The commit-resolution step (reference)

A PR's head commit lives in the contributor's fork, not in
`logos-co/<repo>`, so `github:logos-co/<repo>/<fork-sha>` can't be
fetched. The step blanks the SHA for fork PRs, which pins that repo to
*latest* — the doc-tests still run, just against master:

```yaml
- name: Resolve commit under test
  id: commit
  shell: bash
  run: |
    if [ "${{ github.event_name }}" = "pull_request" ] && \
       [ "${{ github.event.pull_request.head.repo.fork }}" = "true" ]; then
      echo "sha=" >> "$GITHUB_OUTPUT"
      echo "Fork PR — doc-tests will run against latest master."
    else
      echo "sha=${{ github.event.pull_request.head.sha || github.sha }}" >> "$GITHUB_OUTPUT"
    fi
```

`steps.commit.outputs.sha` is then threaded into the `--release-for` flag
of both the `run` and the `generate` calls. Tutorial 4 covers
`--release-for` (and the empty-ref fork fallback) in full.

---

## Step 3: The full workflow

Putting it together: a `test` job (matrixed over Linux and macOS) runs the
report command above and uploads the `index.html` as an artifact, then a
`publish-report` job arranges those artifacts into a site directory and
pushes it to the `gh-pages` branch with
[`peaceiris/actions-gh-pages`](https://github.com/peaceiris/actions-gh-pages),
commenting the links on the PR. We write the whole file to disk so you can
read it end-to-end, then assert the publishing-critical lines are present.

### 3.1 Write .github/workflows/doctests.yml

Replace `myrepo` with your repo's GitHub name (it appears only in the
`--release-for` pin and the artifact/report titles). Everything else is
repo-agnostic:

```yaml
name: Doc-Tests

# Runs the executable doc-tests (doctests/*.test.yaml) via the shared
# doctest CLI and publishes the HTML report to GitHub Pages.
#
# ────────────────────────────────────────────────────────────────────
# One-time setup for the clickable report links to work:
#
#   Repo Settings → Pages → "Build and deployment" → Source:
#   "Deploy from a branch", Branch: `gh-pages` / `(root)`.
#   (The publish-report job creates the gh-pages branch on first run.)
#
# Each run publishes the report to:
#   https://<owner>.github.io/<repo>/pr-<N>/<os>/   (pull requests)
#   https://<owner>.github.io/<repo>/main/<os>/     (pushes to main)
# and (for PRs) posts/updates a comment with the links.
#
# Fork PRs get a read-only GITHUB_TOKEN, so the Pages push and PR
# comment are skipped for them — the downloadable artifact still uploads.
# ────────────────────────────────────────────────────────────────────

on:
  pull_request:
    branches: [master, main]
  push:
    branches: [master, main]

concurrency:
  group: doctests-${{ github.ref }}
  cancel-in-progress: true

jobs:
  doctests:
    name: Run doc-tests (${{ matrix.os }})
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
    runs-on: ${{ matrix.os }}
    timeout-minutes: 60

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Install Nix
        uses: DeterminateSystems/nix-installer-action@main

      - name: Setup Cachix
        uses: cachix/cachix-action@v15
        with:
          name: logos-co
          authToken: '${{ secrets.CACHIX_AUTH_TOKEN }}'

      # Resolve the commit under test (PR head, or pushed commit).
      # Blank it for fork PRs so the inner build falls back to latest.
      - name: Resolve commit under test
        id: commit
        shell: bash
        run: |
          if [ "${{ github.event_name }}" = "pull_request" ] && \
             [ "${{ github.event.pull_request.head.repo.fork }}" = "true" ]; then
            echo "sha=" >> "$GITHUB_OUTPUT"
            echo "Fork PR — doc-tests will run against latest master."
          else
            echo "sha=${{ github.event.pull_request.head.sha || github.sha }}" >> "$GITHUB_OUTPUT"
          fi

      # One `run` over every spec → one combined report (index.html)
      # whose dropdown switches between specs. --continue-on-fail keeps
      # the report complete; the job still fails if any step did.
      - name: Run every doc-test
        run: |
          mkdir -p "${{ runner.temp }}/reports"
          nix run github:logos-co/logos-doctest -- run \
            doctests/*.test.yaml \
            --verbose \
            --continue-on-fail \
            --release-for "myrepo=${{ steps.commit.outputs.sha }}" \
            --report "${{ runner.temp }}/reports/index.html"

      - name: Verify markdown generation
        run: |
          for spec in doctests/*.test.yaml; do
            name="$(basename "${spec%.test.yaml}")"
            nix run github:logos-co/logos-doctest -- generate "$spec" \
              --release-for "myrepo=${{ steps.commit.outputs.sha }}" \
              -o "/tmp/${name}.md"
            test -s "/tmp/${name}.md"
          done

      - name: Upload execution report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: doctest-reports-${{ matrix.os }}
          path: ${{ runner.temp }}/reports/
          if-no-files-found: warn

  publish-report:
    name: Publish reports to GitHub Pages
    needs: doctests
    # Run even on failure — that's when you most want the report. Skip
    # forks, where GITHUB_TOKEN can't push to gh-pages or comment.
    if: ${{ always() && github.event.pull_request.head.repo.fork != true }}
    runs-on: ubuntu-latest

    permissions:
      contents: write          # push to the gh-pages branch
      pull-requests: write      # post/update the PR comment

    # Serialize Pages pushes so two refs can't race on gh-pages.
    concurrency:
      group: gh-pages-publish
      cancel-in-progress: false

    steps:
      - name: Download all reports
        uses: actions/download-artifact@v4
        with:
          path: artifacts

      - name: Arrange site directory
        id: arrange
        shell: bash
        run: |
          set -euo pipefail
          if [ "${{ github.event_name }}" = "pull_request" ]; then
            BASE="pr-${{ github.event.pull_request.number }}"
          else
            BASE="main"
          fi
          echo "base=$BASE" >> "$GITHUB_OUTPUT"

          mkdir -p "site/$BASE"
          found=""
          for os in ubuntu-latest macos-latest; do
            src="artifacts/doctest-reports-$os"
            # Each OS produces one combined index.html — publish as-is.
            if [ -f "$src/index.html" ]; then
              mkdir -p "site/$BASE/$os"
              cp "$src/index.html" "site/$BASE/$os/index.html"
              found="$found $os"
            fi
          done
          echo "found=$found" >> "$GITHUB_OUTPUT"

          # Landing page for this ref linking to each OS report.
          {
            echo "<!doctype html><meta charset=utf-8>"
            echo "<title>doc-test reports — $BASE</title>"
            echo "<h1>doc-test reports</h1>"
            echo "<p><strong>$BASE</strong> · <code>${GITHUB_SHA::7}</code></p><ul>"
            for os in ubuntu-latest macos-latest; do
              if [ -d "site/$BASE/$os" ]; then
                echo "<li><a href=\"./$os/\">$os</a></li>"
              fi
            done
            echo "</ul>"
          } > "site/$BASE/index.html"

      - name: Deploy to gh-pages
        if: steps.arrange.outputs.found != ''
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./site
          keep_files: true          # don't wipe other PRs' directories
          commit_message: "Publish doc-test reports for ${{ steps.arrange.outputs.base }}"

      - name: Comment on PR with report links
        if: ${{ github.event_name == 'pull_request' && steps.arrange.outputs.found != '' }}
        uses: actions/github-script@v7
        with:
          script: |
            const base = "${{ steps.arrange.outputs.base }}";
            const { owner, repo } = context.repo;
            const root = `https://${owner}.github.io/${repo}/${base}`;
            const oses = "${{ steps.arrange.outputs.found }}".trim().split(/\s+/).filter(Boolean);
            const links = oses.map(os => `- [\`${os}\` report](${root}/${os}/)`).join("\n");
            const marker = "<!-- doctest-report-links -->";
            const body =
              `${marker}\n### 📊 doc-test reports\n\n` +
              `Rendered docs alongside the commands actually run and their output:\n\n` +
              `${links}\n\n_Pages can take a minute to update._`;
            const { data: comments } = await github.rest.issues.listComments({
              owner, repo, issue_number: context.issue.number, per_page: 100,
            });
            const existing = comments.find(c => c.body && c.body.includes(marker));
            if (existing) {
              await github.rest.issues.updateComment({ owner, repo, comment_id: existing.id, body });
            } else {
              await github.rest.issues.createComment({ owner, repo, issue_number: context.issue.number, body });
            }
```

### 3.2 Assert the publishing-critical pieces are present

We can't run Actions here, but we can verify the file we just wrote
carries the parts that make publishing work — the combined-report `run`,
the Pages deploy action, and the gh-pages permission:

```bash
grep -E 'actions-gh-pages|--report|contents: write' .github/workflows/doctests.yml
```

Those three lines are the spine of the workflow: `--report` produces the
artifact, `contents: write` lets the publish job push to `gh-pages`, and
`actions-gh-pages` does the push.

---

## Turning on GitHub Pages (one-time)

The workflow creates the `gh-pages` branch on its first successful run, but
GitHub only *serves* it once Pages is pointed at that branch. Do this once
per repo:

1. **Settings → Pages → Build and deployment → Source:** "Deploy from a
   branch".
2. **Branch:** `gh-pages`, folder `/ (root)`. Save.

No secrets to configure: the built-in `GITHUB_TOKEN` already has the
`contents: write` and `pull-requests: write` permissions the publish job
grants. After the first run, each push and same-repo PR publishes to:

```
https://<owner>.github.io/<repo>/main/<os>/     # pushes to main/master
https://<owner>.github.io/<repo>/pr-<N>/<os>/   # pull requests
```

and `keep_files: true` means each PR's directory coexists with the others
instead of overwriting them.

## The fork caveat

One limitation is worth stating plainly, because it shapes the whole
workflow. Pull requests opened **from forks** get a **read-only**
`GITHUB_TOKEN`: such a job cannot push to `gh-pages` or post a PR comment.
The workflow handles this in two places, both seen above:

- The `publish-report` job is guarded by
  `github.event.pull_request.head.repo.fork != true`, so it simply does not
  run for fork PRs — the per-OS **artifact** is still uploaded and
  downloadable from the run's summary page.
- The commit-resolution step blanks the SHA for forks, so the doc-tests build
  against latest master rather than an unfetchable fork commit (Tutorial 4's
  empty-ref fallback).

Same-repo branch PRs and pushes to `main`/`master` get the full experience:
published Pages report and an auto-updating PR comment with the links. That
is the same workflow `logos-package-manager`, `logos-liblogos`, and
`logos-tutorial` run today — the end of the arc that began with a single
spec: docs that verify themselves on every commit and publish the proof.
