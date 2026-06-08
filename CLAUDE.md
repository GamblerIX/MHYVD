# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

MHYVD scrapes a miHoYo/HoYoverse game news listing in a stealth Chromium
browser, classifies articles by keyword rules, and downloads the videos behind
`videos/*` articles. The pipeline is **Fetch → Classify → Download** with a
headless→headed fallback, time budget, interrupt handling, and resume mode.

## Layout

- `src/main.py` — CLI (`run`, `list-sources`) and `main(argv) -> int`. The
  single wiring point: loads config, sets up logging, builds adapter/classifier/
  downloader from registries, drives the pipeline under a time budget.
- `src/pipeline/pipeline.py` — orchestrates the three stages + fallback. Returns
  a `PipelineResult`; reports failures via its `error` field, never by raising.
- `src/sources/` — `SourceAdapter`s (HSR-CN in `honkai_star_rail_cn.py`),
  registry, and pure helpers in `base.py`.
- `src/classifier/` — rule-based keyword classifier + registry.
- `src/downloader/` — Playwright downloader (`videos/*` only), URL resolution,
  output paths, registry.
- `src/browser/driver.py` — Playwright + stealth Chromium driver.
- `src/config/` — YAML loader (`settings.py`), defaults, proxy.
- `src/cache/` — `FetchCache` / `DownloadCache` for resume mode.
- `src/runtime.py` — time budget, shutdown controller, `choose_exit_code`.
- `src/models.py` — frozen dataclasses (`NewsItem`, `VideoItem`,
  `DownloadResult`, `PipelineResult`, `Rule`, `SourceMetadata`).
- `config/default.yaml` — mirrors `src/config/defaults.py`. Keep both in sync.
- `tests/` — `unittest`, one file per module.
- `bak/` — legacy plugin-based implementation, ported from. Reference only;
  do not edit or import.

## Commands

Dependencies are managed with **uv** (Python pinned to **3.11** via
`.python-version`). Run `uv sync` once to create `.venv`; prefix commands with
`uv run`.

```bash
uv sync                                        # create .venv + install deps
uv run python -m src.main run                  # full pipeline
uv run python -m src.main list-sources         # list Source_Keys
uv run python -m unittest discover -s tests    # run tests
```

The package is imported as `src` — run everything from the repo root. Runtime
deps (`PyYAML`, `playwright`, `playwright-stealth`) and the `hypothesis` dev
dependency live in `pyproject.toml`; keep that the single source of truth.

## Conventions

- **Frozen dataclasses.** All models in `src/models.py` are `frozen=True`.
  Produce new instances (e.g. `NewsItem.with_category`) instead of mutating.
- **Injectable seams for testing.** Browser/network touchpoints are behind
  injectable callables: `pipeline_factory` (main), `driver_factory` /
  `crash_identifier` (Pipeline), `resolve_attempt` / `download_file`
  (downloader), `playwright_factory` / `stealth` (driver). New browser/network
  code MUST stay behind such a seam so tests run without Chromium.
- **Registries.** Adapters, classifiers, downloaders are registry-backed. Add a
  component by registering it, not by editing the orchestrator.
- **Failures are reported, not raised.** The pipeline normalizes errors into
  `PipelineResult.error`. Preserve this — callers depend on it for exit codes.
- **Lazy Playwright import.** `browser/driver.py` imports Playwright only on
  launch, so the module imports cleanly without the package. Keep it lazy.
- **Requirement tags.** Docstrings reference numbered requirements/properties
  (e.g. "Requirement 4.2", "Property 10"). When changing behavior near a tag,
  keep the tag accurate or update it.

## Gotchas

- Exit-code precedence: timeout `124` > interrupt `130` > runtime failure `1` >
  success `0` (`src/runtime.py::choose_exit_code`).
- The markdown summary prints **only** when `PipelineResult.completed` is true —
  never on timeout/interrupt. Gated on completion, not exit code.
- A fetch attempt reporting **zero items** counts as a *failure* (triggers
  fallback), not an empty success.
- Downstream stages gate on the **reported** fetch count, not `len()` of the
  actual list (`should_run_downstream`).
- `--limit` is applied before recording to the Fetch_Cache so capped-out items
  stay available on a later resume run.
- Only `videos/*` categories are downloaded; other categories are classified
  and counted but skipped by the downloader.
- Unknown subcommand exits non-zero; every other argparse error exits **zero**
  (intentional, in `_CliParser`).

## Don't

- Don't add real browser/network calls outside an injectable seam.
- Don't let `config/default.yaml` and `src/config/defaults.py` drift apart.
