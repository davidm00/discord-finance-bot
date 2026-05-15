# Discord Finance Bot

A scheduled GitHub Actions-driven finance report bot that posts a rich Discord **embed** twice per trading day (pre-market + post-market) and can also be run locally for testing.

It fetches market/crypto/news/political/contract data, asks Claude to write a plain-English briefing, parses a small "Tickers to Watch" section, and sends everything to Discord.

## What it posts (Discord embed)

Each run posts an embed containing:

- 🇺🇸 **Equities**: SPY / QQQ / DIA / VIX snapshot
- ₿ **Crypto**: BTC / ETH / SOL + notable movers
- 📰 **Top Headlines**: Finnhub + RSS sources
- 🏛️ **Political Trades**: CapitolTrades scrape (best-effort)
- 📋 **Gov Contracts**: USASpending.gov awards (best-effort)
- 📅 **Upcoming Earnings**: Finnhub earnings calendar (filtered)
- 🎯 **Tickers to Watch**: parsed from Claude response

All timestamps are labeled **ET** (Eastern Time). The report always includes a disclaimer.

## How it runs (GitHub Actions)

Workflow: `.github/workflows/report.yml`

Triggers:
- **schedule**: 8:45 AM ET and 4:15 PM ET (Mon–Fri)
  - Note: GitHub Actions cron is **UTC** and doesn't support DST properly.
  - This repo schedules **both** the EDT and EST UTC equivalents and uses a workflow-level guard step so only the correct season (EDT vs EST) runs.
- **workflow_dispatch**: manual runs from the Actions tab

The workflow installs dependencies from `requirements.txt` and caches pip (`~/.cache/pip`) between runs.

## Required GitHub Secrets

Configure these in repo settings → Actions → Secrets:

- `DISCORD_WEBHOOK_URL` (required)
- `ANTHROPIC_API_KEY` (for Claude analysis)
- `FINNHUB_API_KEY` (news + earnings calendar)
- `DISCORD_BOT_TOKEN` (for fetching prior reports/history)
- `DISCORD_CHANNEL_ID` (for fetching prior reports/history)

Secrets are only read via environment variables (never hardcoded).

## Local testing (no key leaks)

Local runs use a gitignored `.env.local` file in the repo root.

### 1) Install deps

```bash
python -m pip install -r requirements.txt
```

### 2) Create `.env.local` (repo root; gitignored)

```env
DISCORD_WEBHOOK_URL=...
ANTHROPIC_API_KEY=...
FINNHUB_API_KEY=...
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=...
```

### 3) Run in DRY_RUN mode (recommended)

DRY_RUN runs the full pipeline (fetches data, calls Claude, builds the embed) **but does not post to Discord**.

PowerShell:
```powershell
$env:DRY_RUN="1"
python bot\report.py
```

CMD:
```bat
set DRY_RUN=1
python bot\report.py
```

### Local output files

When `DRY_RUN=1` is set, the run writes:

- `local-output/latest_report.md` — a Discord-style embed preview
- `local-output/latest_claude_response.md` — the full Claude response text (useful for debugging parsing)

`local-output/` is gitignored.

### Optional debug flags

- `PARSER_DEBUG=1` — prints extra info about how the "Tickers to Watch" section was found/parsed.

## Data sources (current)

- Equities: `yfinance`
- Crypto: CoinGecko API
- News: Finnhub general news + RSS feeds
- Political trades: CapitolTrades (HTML scrape; best-effort)
- Gov contracts: USASpending.gov (best-effort)
- Earnings: Finnhub earnings calendar endpoint
- Analysis: Anthropic Claude (model `claude-sonnet-4-6`)

## Notes / Design principles

- Degrades gracefully: a single API outage should not crash the whole report.
- Verbose logs: everything prints to stdout for easy debugging in Actions logs.
- Discord limits: embed payload is clamped to Discord size limits to avoid webhook 400s.
