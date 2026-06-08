# GitHub Actions CI Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub Actions CI quality gate (ruff lint+format, mypy types, unittest + headless-Chromium smoke) running on push to `main` and every PR, Python 3.11 only.

**Architecture:** One workflow file `.github/workflows/ci.yml` with three parallel jobs (lint / typecheck / test), each set up via `astral-sh/setup-uv` + `uv sync --dev`. Tooling configured in `pyproject.toml`. A new opt-in headless-Chromium smoke test lives in `tests/integration/`, run by CI with `RUN_BROWSER_SMOKE=1`.

**Tech Stack:** uv, Python 3.11, ruff, mypy, unittest, Playwright (Chromium), GitHub Actions.

---

## File Structure

| File                                        | Responsibility                          |
|---------------------------------------------|-----------------------------------------|
| `pyproject.toml`                            | dev deps (ruff/mypy/types-PyYAML) + `[tool.ruff]` / `[tool.mypy]` config |
| `tests/integration/__init__.py`             | empty package marker so `discover` treats dir as a package |
| `tests/integration/test_browser_smoke.py`   | opt-in headless Chromium smoke test     |
| `.github/workflows/ci.yml`                  | CI workflow: 3 parallel jobs            |
| `CLAUDE.md`                                  | document lint/type/smoke commands + layout |
| existing `src/`, `tests/` files             | ruff/mypy fixes as surfaced             |

**Task order rationale:** configure tooling first (Task 1), make the repo pass it locally (Task 2), add the smoke test (Task 3), then wire CI (Task 4), then docs (Task 5). Each task ends green and committed.

---

### Task 1: Add tooling deps and configuration to `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dev dependencies**

In `pyproject.toml`, replace the `[dependency-groups]` `dev` list:

```toml
[dependency-groups]
dev = [
    "hypothesis>=6.0",
    "ruff>=0.6",
    "mypy>=1.11",
    "types-PyYAML",
]
```

- [ ] **Step 2: Append ruff config**

Add to the end of `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py311"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B"]
```

- [ ] **Step 3: Append mypy config**

Add to the end of `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.11"
files = ["src", "tests"]
warn_unused_ignores = true
warn_redundant_casts = true
disallow_untyped_defs = false
ignore_missing_imports = true
```

- [ ] **Step 4: Sync the new deps**

Run: `uv sync --dev`
Expected: resolves and installs ruff, mypy, types-PyYAML into `.venv` (no errors).

- [ ] **Step 5: Verify the tools are callable**

Run: `uv run ruff --version && uv run mypy --version`
Expected: both print a version line (no "Failed to spawn").

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add ruff and mypy with conservative config"
```

---

### Task 2: Make the existing codebase pass ruff and mypy

**Files:**
- Modify: any `src/`, `tests/` files reported by ruff/mypy

This task has no new test — the "test" is that `ruff check`, `ruff format --check`, and `mypy` all pass. The codebase has never run these tools, so expect findings.

- [ ] **Step 1: Auto-fix ruff lint findings**

Run: `uv run ruff check --fix .`
Expected: applies import-sort (I) and other safe fixes; prints remaining unfixable issues, if any.

- [ ] **Step 2: Apply ruff formatting**

Run: `uv run ruff format .`
Expected: reformats files to ruff's style; prints count of reformatted files.

- [ ] **Step 3: Resolve remaining ruff lint findings by hand**

Run: `uv run ruff check .`
Expected: eventually `All checks passed!`. For each remaining finding, fix the
code minimally. Do NOT blanket-`# noqa`; only suppress a specific rule on a
specific line when the rule is genuinely wrong for that line (e.g. an
intentional unused import in `__init__.py` re-exports → add `__all__` instead, or
`# noqa: F401` with a reason).

- [ ] **Step 4: Run mypy and resolve findings**

Run: `uv run mypy src tests`
Expected: eventually `Success: no issues found`. Config already sets
`ignore_missing_imports = true` (covers `playwright_stealth`) and
`disallow_untyped_defs = false` (tests need not be fully annotated). For real
type errors, fix the annotation/code. Use `# type: ignore[code]` with the
specific error code only where the type system genuinely cannot express the
truth (the driver already does this for `ProxySettings`).

- [ ] **Step 5: Confirm tests still pass after reformatting**

Run: `uv run python -m unittest discover -s tests`
Expected: same pass count as before this task (reformatting must not change behavior).

- [ ] **Step 6: Confirm the full local gate is green**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests`
Expected: `All checks passed!`, no format diff, `Success: no issues found`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "style: satisfy ruff lint/format and mypy across the codebase"
```

---

### Task 3: Add the opt-in headless Chromium smoke test

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_browser_smoke.py`

- [ ] **Step 1: Create the package marker**

Create `tests/integration/__init__.py` as an empty file:

```python
```

(Empty file — its presence makes `tests/integration/` an importable package so `unittest discover -s tests/integration` works.)

- [ ] **Step 2: Write the smoke test**

Create `tests/integration/test_browser_smoke.py`:

```python
"""Opt-in headless Chromium smoke test for ``BrowserDriver``.

Unlike the unit tests under ``tests/`` (which inject fakes and never launch a
real browser), this test actually starts headless Chromium and drives a page
end to end, validating that ``BrowserDriver.launch`` wires browser -> context
-> page -> stealth against the real Playwright stack.

It is skipped unless ``RUN_BROWSER_SMOKE=1`` is set, so local developers need
no Chromium install. CI sets that variable and runs
``uv run playwright install --with-deps chromium`` first.
"""

import os
import unittest

from src.browser.driver import MODE_HEADLESS, BrowserDriver


@unittest.skipUnless(
    os.environ.get("RUN_BROWSER_SMOKE") == "1",
    "set RUN_BROWSER_SMOKE=1 to run (needs Chromium installed)",
)
class BrowserSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_headless_launch_opens_page(self) -> None:
        async with BrowserDriver(mode=MODE_HEADLESS) as driver:
            page = driver.page
            self.assertIsNotNone(page)
            await page.goto("about:blank")
            self.assertEqual(page.url, "about:blank")
```

- [ ] **Step 3: Verify the test is skipped without the env var**

Run: `uv run python -m unittest discover -s tests/integration -v`
Expected: `test_headless_launch_opens_page ... skipped 'set RUN_BROWSER_SMOKE=1 ...'`; overall OK.

- [ ] **Step 4: Verify it passes with Chromium installed (local optional)**

Run: `uv run playwright install chromium && RUN_BROWSER_SMOKE=1 uv run python -m unittest discover -s tests/integration -v`
Expected: `test_headless_launch_opens_page ... ok`. (If Chromium cannot be
installed locally, skip this step — CI is the source of truth. Note this in the
commit if skipped.)

- [ ] **Step 5: Confirm the root suite does NOT pick up the smoke test**

Run: `uv run python -m unittest discover -s tests 2>&1 | tail -3`
Expected: `discover -s tests` ran the existing suite only; the integration test
is not double-counted (root discover does not recurse into `tests/integration`
because it is a separate top-level package directory).

- [ ] **Step 6: Confirm ruff/mypy accept the new files**

Run: `uv run ruff check tests/integration && uv run ruff format --check tests/integration && uv run mypy tests/integration`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add tests/integration/__init__.py tests/integration/test_browser_smoke.py
git commit -m "test: add opt-in headless Chromium smoke test"
```

---

### Task 4: Add the CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
      - run: uv sync --dev
      - run: uv run ruff check .
      - run: uv run ruff format --check .

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
      - run: uv sync --dev
      - run: uv run mypy src tests

  test:
    runs-on: ubuntu-latest
    env:
      RUN_BROWSER_SMOKE: "1"
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
      - run: uv sync --dev
      - run: uv run playwright install --with-deps chromium
      - run: uv run python -m unittest discover -s tests
      - run: uv run python -m unittest discover -s tests/integration
```

Notes:
- `setup-uv` reads `.python-version` (3.11) automatically — no `python-version` input needed.
- `enable-cache: true` caches the uv download/dependency cache between runs.
- `--with-deps` installs Chromium plus the Linux system libraries it needs on `ubuntu-latest`.
- The two `discover` runs separate the existing suite from the integration suite.

- [ ] **Step 2: Validate YAML syntax locally**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no output, exit 0 (valid YAML). (PyYAML is already a runtime dep.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow (ruff, mypy, tests + smoke)"
```

- [ ] **Step 4: Push and confirm CI is green**

Run: `git push`
Expected: on GitHub, the `CI` workflow runs three jobs (lint, typecheck, test);
all pass. If a job fails, fix the underlying issue (not the workflow) and push
again. The `test` job's smoke test must show as run (not skipped) since
`RUN_BROWSER_SMOKE=1` is set.

---

### Task 5: Document the CI commands in `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Extend the Commands code block**

In `CLAUDE.md`, replace the commands code block (currently ending with the
`unittest discover -s tests` line) so it reads:

```bash
uv sync                                        # create .venv + install deps
uv run python -m src.main run                  # full pipeline
uv run python -m src.main list-sources         # list Source_Keys
uv run python -m unittest discover -s tests    # run tests
uv run ruff check . && uv run ruff format --check .   # lint + format gate
uv run mypy src tests                          # type check
RUN_BROWSER_SMOKE=1 uv run python -m unittest discover -s tests/integration  # Chromium smoke
```

- [ ] **Step 2: Add layout entries**

In the `## Layout` section of `CLAUDE.md`, add two bullets (after the `tests/` bullet):

```markdown
- `.github/workflows/ci.yml` — CI: ruff lint+format, mypy, unittest, and a
  headless-Chromium smoke test, on push to `main` and every PR (Python 3.11).
- `tests/integration/` — opt-in tests that touch a real browser; run only when
  `RUN_BROWSER_SMOKE=1` is set. Not picked up by the root `tests/` discover.
```

- [ ] **Step 3: Verify the doc edits are coherent**

Run: `uv run ruff format --check CLAUDE.md 2>/dev/null; grep -n "RUN_BROWSER_SMOKE\|ci.yml\|tests/integration" CLAUDE.md`
Expected: grep shows the new lines present. (ruff does not format markdown; the
first command is a harmless no-op and may print a warning — ignore it.)

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document CI commands and integration tests in CLAUDE.md"
```

---

## Self-Review Notes

- **Spec coverage:** workflow structure (Task 4), three parallel jobs (Task 4),
  job details incl. `--with-deps` and dual `discover` (Task 4), ruff+mypy config
  and dev deps (Task 1), first-run fixes (Task 2), smoke test with `skipUnless`
  + separate dir (Task 3), CLAUDE.md commands+layout (Task 5). All spec sections
  map to a task.
- **No placeholders:** every code/command step shows actual content.
- **Type/name consistency:** import `from src.browser.driver import MODE_HEADLESS, BrowserDriver`
  matches the module's `__all__`; env var `RUN_BROWSER_SMOKE` and value `"1"`
  used identically in the test, the workflow, and the docs.
