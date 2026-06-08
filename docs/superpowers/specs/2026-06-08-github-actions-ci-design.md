# GitHub Actions CI Integration — Design

**Date:** 2026-06-08
**Status:** Approved

## Goal

Add a GitHub Actions CI quality gate for MHYVD: lint + format, static type
check, and the test suite (including a real headless-Chromium smoke test). The
gate runs on push to `main` and on every pull request, on Python 3.11 only.

Out of scope: scheduled scrape runs, multi-version matrix, artifact uploads.

## Tooling Decisions

| Concern        | Tool                         | Notes                                        |
|----------------|------------------------------|----------------------------------------------|
| Lint + format  | **Ruff**                     | Single fast tool; replaces flake8/black.     |
| Type check     | **mypy**                     | Mature; matches typed dataclasses/seams.     |
| Tests          | **unittest** (existing)      | Plus a new headless-Chromium smoke test.     |
| Dep management | **uv** (existing)            | Python pinned 3.11 via `.python-version`.    |

## Workflow Structure

File: `.github/workflows/ci.yml`

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
  lint:       # ruff check + ruff format --check
  typecheck:  # mypy src tests
  test:       # playwright install chromium + unittest discover
```

- **Three parallel jobs** — fast failure localization, no cross-blocking.
- All jobs `runs-on: ubuntu-latest`.
- **Shared setup steps** per job: `actions/checkout` → `astral-sh/setup-uv@v4`
  (pinned uv version, built-in cache) → `uv sync --dev`.
- `setup-uv` reads `.python-version` automatically — no `matrix`, single 3.11.
- `concurrency` cancels superseded runs on the same ref to save minutes.

## Job Details

**lint**
```
uv sync --dev
uv run ruff check .
uv run ruff format --check .
```
`check` catches lint violations; `format --check` reports formatting drift
without modifying files.

**typecheck**
```
uv sync --dev
uv run mypy src tests
```

**test**
```
uv sync --dev
uv run playwright install --with-deps chromium
RUN_BROWSER_SMOKE=1 uv run python -m unittest discover -s tests
RUN_BROWSER_SMOKE=1 uv run python -m unittest discover -s tests/integration
```
`--with-deps` installs Chromium plus the Linux system libraries it needs on
`ubuntu-latest`. Two `discover` invocations: the regular suite (root `tests/`,
which does not recurse into `tests/integration/`), then the integration
directory explicitly. `RUN_BROWSER_SMOKE=1` enables the otherwise-skipped smoke
test.

## Tool Configuration (`pyproject.toml`)

Dev dependencies add `ruff`, `mypy`, `types-PyYAML`:

```toml
dev = [
    "hypothesis>=6.0",
    "ruff>=0.6",
    "mypy>=1.11",
    "types-PyYAML",
]
```

Ruff — conservative rule set to avoid an initial flood of errors:

```toml
[tool.ruff]
target-version = "py311"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B"]
```

mypy — medium strictness matching existing annotations:

```toml
[tool.mypy]
python_version = "3.11"
files = ["src", "tests"]
warn_unused_ignores = true
warn_redundant_casts = true
disallow_untyped_defs = false
ignore_missing_imports = true
```

**First-run risk:** the codebase has never run ruff/mypy. During implementation,
run both locally first, apply `ruff check --fix`, and resolve remaining issues
by hand so CI is green on first push. Strictness starts low and can be tightened
later.

## Smoke Test

New package directory `tests/integration/` (with empty `__init__.py`).

`tests/integration/test_browser_smoke.py`:

```python
import os
import unittest

from src.browser.driver import BrowserDriver, MODE_HEADLESS


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

- Really launches headless Chromium and validates `launch()` end to end,
  including stealth application.
- `IsolatedAsyncioTestCase` drives the async driver.
- **Skipped by default** so local developers need no Chromium install; CI sets
  `RUN_BROWSER_SMOKE=1`.
- `about:blank` touches no network — pure "the browser stack starts" check.
- Lives in a separate directory so the root `discover` never picks it up; CI
  runs it via an explicit second `discover`.

## Documentation Updates

`CLAUDE.md`:

- **Commands** section — add lint, type-check, and smoke-test commands.
- **Layout** section — mention `.github/workflows/ci.yml` and `tests/integration/`.

## Files Touched

| File                                        | Change                          |
|---------------------------------------------|---------------------------------|
| `.github/workflows/ci.yml`                  | new — CI workflow               |
| `pyproject.toml`                            | edit — dev deps + ruff/mypy cfg |
| `tests/integration/__init__.py`             | new — empty package marker      |
| `tests/integration/test_browser_smoke.py`   | new — headless Chromium smoke   |
| `CLAUDE.md`                                  | edit — commands + layout notes  |
| existing `src/`, `tests/` files             | edit as needed — ruff/mypy fixes|
