# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Vibe-Research is a self-hosted personal AI investment research dashboard for A股 / 美股 / 港股. It bundles **data (only)** — market quotes, filings, financials, news, capital-flow, hot-money tape — and exposes a pluggable AI layer so **the user's own model** provides analysis. The product is deliberately data-only and neutral: no stock picks, no predictions, no buy/sell UI. Uphold that stance when adding features.

## Repo Layout

```
Vibe-Research/
├── a-stock-data/       Self-contained A-share data toolkit (10 layers, 40 endpoints, v3.3). SKILL.md has copy-paste code per endpoint.
├── global-stock-data/  Self-contained US/HK data toolkit (v1.0.1).
├── backend/            FastAPI on :8900 — HTTP API + MCP server, ports the two data toolkits above.
├── frontend/           Vite + React 19 + TS + Tailwind on :5899 — proxies /api → :8900.
├── newinfo710/         (scratch / experimental data)
├── docs/               Screenshots and product docs.
└── start.sh / start.command   One-shot launcher (venv + npm install first run, then backend + frontend + browser).
```

The `a-stock-data/` and `global-stock-data/` directories are **vendored frozen snapshots** of their upstream repos (simonlin1212/a-stock-data, simonlin1212/global-stock-data). The backend's `astock.py` / `gstock.py` are ports of the same code — treat the toolkit dirs as the reference, not as a dependency to import from.

## Running the App

```bash
# One-shot: creates venv + npm install on first run, launches both, opens the browser
./start.sh

# Manual backend (:8900)
cd backend && python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8900 --reload

# Manual frontend (:5899)
cd frontend && npm install && npm run dev

# Frontend build / preview
cd frontend && npm run build      # tsc -b && vite build
cd frontend && npm run preview
```

The frontend Vite dev server proxies `/api` → `http://127.0.0.1:8900` (see `frontend/vite.config.ts` — uses `127.0.0.1`, not `localhost`, to avoid IPv6 resolution issues on macOS).

## Tests

```bash
cd backend && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -m "not live"        # offline unit + API tests (fast, deterministic)
.venv/bin/pytest -m live              # live network checks — data-source shape probes; run before release
.venv/bin/pytest tests/test_api.py    # single file
.venv/bin/pytest tests/test_api.py::test_name    # single test
```

The `live` marker is registered in `backend/conftest.py`; default runs skip it via `-m "not live"`. Frontend has no test suite — verify UI changes by running the app in a browser.

## Backend Architecture

Entry point: `backend/app.py` — FastAPI. Every route is under `/api/*`, read-only, stateless, keyed by user-supplied stock code. The app validates codes as `^\d{6}$` before hitting data layers.

Module responsibilities:

- `astock.py` — A-share data (five layers: quote via Tencent stdlib → reports/announcements via requests+东财 → consensus/news via akshare → K-line/financials via mootdx → F10). **Lazy imports for `akshare` / `mootdx`**: when missing, the endpoint returns HTTP 501 with an install hint rather than crashing the app. Preserve this pattern for new data layers.
- `gstock.py` — US/HK/KR data. Reuses `astock.em_get` for 东财 access so it goes direct instead of through a VPN proxy.
- `newsradar.py` + `news_sources.json` — 12-track / 108-source RSS pipeline (stdlib only, compliance-filtered word list).
- `market.py` — index / breadth / sector-flow / global-indices aggregation for the daily-review page.
- `portfolio.py`, `myreports.py`, `reviewpool.py`, `samples.py`, `screener.py`, `storage.py` — local-only state (positions, uploaded reports, review pool, shadow-sample scheduler, screening, disk cache). All persist to `backend/.cache/*.json` — gitignored, never uploaded.
- `chat.py` — system-AI chat with OpenAI-compatible function-calling; the LLM picks data tools. The frontend sends `{baseURL, apiKey, model}` in each request; the backend **does not persist keys**.
- `cli_runtime.py` — “subscription mode” — spawns a locally-installed CLI (Claude Code / Codex / Qwen / DeepSeek) with the full prompt in-band. Single-shot, no multi-turn tool calls — use it for review/summary flows where data is already gathered.
- `mcp_server.py` — MCP server exposing four core tools (`query_quote / query_valuation / query_reports / query_news`) for external agents like Claude Code.

Two background schedulers boot with the app (see `app.py`): `pf.start_scheduler(1800)` for positions refresh, `samples.start_scheduler()` for post-close shadow-sample archiving. Keep those responsibilities in the scheduler owners, not sprinkled into request handlers.

### Optional environment variables (backend)

- `VR_ALLOW_ORIGINS` — comma-separated CORS whitelist. Defaults to `*` (fine for local self-host; tighten for public deploys).
- `VR_API_KEY` — when set, every `/api/*` request (except `/api/health`) must send `Authorization: Bearer <key>`. Unset = open (local-only mode).

## Frontend Architecture

Vite + React 19 + TS + Tailwind, single-page router (`src/router.tsx`) with 11 pages under one `Layout`:

`/daily-review` (`DailyReview`) · `/intel` · `/sectors` + `/sectors/:key` · `/portfolio` · `/stock-data` · `/watchlist` · `/review-pool` · `/my-reports` · `/notes` · `/settings`.

Notable dirs:

- `src/pages/*.tsx` — one file per route.
- `src/features/review/` — Review Pool feature split into `PoolView`, `ScanView`, `StatsView`, `DetailDrawer`, `MiniKline`, `shared` (a refactor pulled these out of a 1317-line monolith — keep new review-pool code in this split).
- `src/lib/` — API client (`api.ts`), LLM plumbing (`llm.ts`, `ai-models.ts`), local storage helpers (`watchlist.ts`, `notes.ts`).
- `src/data/`, `src/hooks/`, `src/components/` — data adapters, hooks, and shared UI.

Path alias: `@` → `src/` (see `vite.config.ts` and `tsconfig.json`). Manual chunks split `react` and `echarts` (heavy) — respect that when adding large deps.

**AI keys / watchlist / positions / uploaded reports live in `localStorage` or `backend/.cache/`, never in the repo.** Do not add any code path that ships them to a remote service.

## Compliance Rules (Non-negotiable)

The product is positioned as a data dashboard, not an advisor. When editing prompts, chat system messages, endpoint copy, or UI:

- Never add stock recommendations, price predictions, buy/sell timing hints, subjective ratings, or profit promises.
- The chat system prompt in `chat.py` includes explicit "no recommendation" red lines — don't weaken them.
- Objective public rankings (连板股 / 成交额榜 / 龙虎榜 / 融资融券 etc.) present the facts as-is; do not append commentary/predictions on top of them.
- Valuation percentile shows position only — no buy/sell threshold lines.
- Any conclusion belongs to the **user's** configured model, not to the product.

## Adding a New Data Endpoint

1. Add the fetcher to `astock.py` (or `gstock.py`) following the layered pattern; use `em_get` for 东财 to inherit rate-limit / anti-ban handling.
2. If the fetcher needs `akshare` / `mootdx`, do a **lazy import inside the function** and raise `DependencyMissing` (defined in `astock.py`) so the FastAPI handler can convert to a 501 with an install hint.
3. Expose a `/api/...` route in `app.py`. Validate any code param via `_validate(code)`.
4. Add a test in `backend/tests/` (offline via `TestClient` + monkeypatched fetcher for the default suite; add a `@pytest.mark.live` counterpart if you want a real-network probe).
5. Wire the endpoint into `frontend/src/lib/api.ts` and the relevant page/feature.

## Data-only stance in prompts / copy

When touching AI-facing strings (system prompts, chat.py, MCP tool descriptions, UI microcopy that instructs the model): keep the "只提供数据，不给结论 / no recommendations, no predictions" framing intact. Framework-style guidance (估值 / 资金面 / 财报质量 / 行业景气 / 事件催化与风险) tells the model **how to read the data**, not what to conclude.
