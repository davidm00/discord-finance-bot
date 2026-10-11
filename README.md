# Discord Finance Bot

An AI-powered daily market intelligence bot that delivers pre-market briefings and post-market recaps to Discord. Built with Python, Claude AI, and GitHub Actions.

## Features

### 📊 Daily Reports (Pre-Market & Post-Market)

- **AI-Powered Analysis** — Claude Sonnet generates plain-English market narratives with bull/bear debate format for each recommended ticker
- **Multi-Source Data** — Aggregates equities, crypto, news, political trades, government contracts, and earnings into a single briefing
- **Source-Weighted News** — Headlines ranked by source reliability (Reuters > Bloomberg > CNBC > etc.) with event classification (geopolitical, earnings, M&A, regulatory, macro)
- **Signal Tracking** — Logs every ticker recommendation to CSV with price-at-signal for historical backtesting
- **Paper Portfolio** — Optional $10,000 simulated account that consumes the same logged recommendations without changing report generation

### 📈 What Each Report Contains

| Section | Source | Content |
|---------|--------|---------|
| 🇺🇸 Equities | yfinance + fallbacks | SPY, QQQ, DIA, VIX with daily % change |
| ₿ Crypto | CoinGecko | BTC, ETH, SOL + notable altcoin movers |
| 📰 Headlines | Finnhub + RSS (Reuters, Bloomberg, CNBC) | Top 5 weighted headlines with event type |
| 🏛️ Political Trades | Capitol Trades scrape | Congressional stock disclosures > $25K |
| 📋 Gov Contracts | USASpending.gov | Major federal awards with recurring flag |
| 📅 Earnings | Finnhub calendar | Upcoming reports with EPS estimates |
| 🎯 Tickers to Watch | Claude AI + parser | Bull/Bear cases, rating, confidence level |

### 📅 Weekly Summary (Saturdays)

- Weekly performance for major indices and crypto (Mon open → Fri close + weekly high/low)
- Week's dominant themes and biggest catalyst
- Bot Scorecard — how previous BUY/SELL/HOLD/WATCH calls performed
- Week Ahead outlook + fresh ticker watchlist

### 🛡️ Pipeline Resilience

- **Multi-source fallback** — yfinance → Yahoo Chart API → Finnhub for every equity fetch
- **HTTP caching** — SQLite-backed request cache with per-URL TTL rules
- **Automatic retries** — Exponential backoff (tenacity) on all API calls
- **Market calendar awareness** — Adjusts report title/behavior for pre-market, open, post-market, closed, and holidays
- **Graceful degradation** — Any single data source failure won't crash the pipeline

## Architecture

```
cron-job.org (free) → GitHub Actions workflow_dispatch
                        ↓
              .github/workflows/report.yml
                        ↓
        ┌───────────────┴───────────────┐
        │                               │
   bot/report.py                bot/weekly_report.py
   (daily pre/post)             (Saturday summary)
        │
   Parallel data fetch (6 sources)
        │
   Claude Sonnet analysis
        │
   Parse recommendations → Log signals
        │
   Discord webhook (2 embeds per report)
        │
   Optional paper portfolio step
        │
   Simulated ledger → separate portfolio card + 7-day chart
```

## Schedule

| Report | Time (ET) | Days |
|--------|-----------|------|
| Pre-Market Briefing | 8:00 AM | Mon–Fri |
| Post-Market Recap | 4:15 PM | Mon–Fri |
| Weekly Summary | 8:00 AM | Saturday |

Scheduling via [cron-job.org](https://cron-job.org) triggering GitHub Actions `workflow_dispatch`.

## Data Sources

| Data | Source | Fallback |
|------|--------|----------|
| Equities | yfinance | Yahoo Chart API → Finnhub |
| Crypto | CoinGecko API | — |
| News | Finnhub + RSS (CNBC, Bloomberg, MarketWatch) | — |
| Political trades | Capitol Trades (HTML scrape) | — |
| Gov contracts | USASpending.gov API | — |
| Earnings | Finnhub calendar | — |
| Macro context | TNX, DXY, Fear & Greed Index | — |
| Analysis | Claude Sonnet 4.6 (Anthropic API) | — |

## Setup

### Required GitHub Secrets

Configure in repo Settings → Secrets and variables → Actions:

| Secret | Purpose |
|--------|---------|
| `DISCORD_WEBHOOK_URL` | Posts reports to Discord |
| `ANTHROPIC_API_KEY` | Claude AI analysis |
| `FINNHUB_API_KEY` | News + earnings calendar |
| `DISCORD_BOT_TOKEN` | Fetches previous reports for continuity |
| `DISCORD_CHANNEL_ID` | Channel to read history from |

### Paper Portfolio

Paper trading is disabled by default. It uses the existing free yfinance data,
GitHub Actions cache/artifacts, and Discord webhook; no brokerage account or
additional paid API is required.

Set the repository Actions variable `PAPER_TRADING_ENABLED=true` after completing
a dry-run validation. A manual workflow run can override this with the
`paper_trading_enabled` input.

The version 1 policy is intentionally constrained:

- starts a clean forward account with $10,000;
- trades equities only; crypto remains in signal outcome tracking;
- MEDIUM/HIGH BUY opens a 20% position, subject to an 80% gross exposure cap;
- SELL exits an existing long; naked SELL calls do not open shorts;
- HOLD/WATCH do not transact;
- fills at the next eligible market open with 5 bps adverse slippage;
- rejects fills more than 2% from the signal price;
- applies a 4% stop and 10-trading-session safety exit;
- suppresses repeated entries and never pyramids an open position.

The post-market run sends a separate daily portfolio card. The weekly run sends
a fuller card. Both show simulated account performance, cash, positions,
purchase dates, fractional shares, and a trailing seven-day chart. The original
market-report messages are not modified, and a portfolio failure cannot block
an already-generated report. Forward state is persisted in a dedicated cache
and a 90-day artifact; the workflow restores the artifact if the cache is
missing. Successful production runs also commit signal and portfolio data to
the dedicated `data-backups` branch, providing permanent Git history without
adding generated-data commits to `main`.

Useful manual workflows:

- **Paper Portfolio Backtest** replays the May-present signal history into a
  separate backtest account.
- **Paper Portfolio Review** creates a recommend-only review artifact. It
  requires at least 10 newly closed forward trades before suggesting strategy
  changes and never modifies prompts or parameters itself. Trigger it every two
  weeks through cron-job.org; low-activity runs explicitly defer changes.
- **Durable Finance Data Backup** initializes or manually refreshes the
  `data-backups` branch from the latest production artifacts and account state.

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env.local (gitignored)
cat > .env.local << EOF
DISCORD_WEBHOOK_URL=...
ANTHROPIC_API_KEY=...
FINNHUB_API_KEY=...
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=...
EOF

# Run in DRY_RUN mode (full pipeline, no Discord post)
DRY_RUN=1 python bot/report.py

# Or on Windows PowerShell:
$env:DRY_RUN="1"; python bot\report.py
```

DRY_RUN outputs to `local-output/latest_report.md` and `local-output/latest_claude_response.md`.

### Running Tests

```bash
TEST_MOCK=1 python bot/test_runner.py    # Offline mock tests (25 tests)
TEST_LIVE=1 python bot/test_runner.py    # Live API connectivity tests
```

Portfolio-only local previews can be generated without mutating forward state or
posting to Discord:

```bash
PAPER_TRADING_ENABLED=true DRY_RUN=1 python bot/portfolio_job.py --report-type weekly
python bot/paper_portfolio.py --backtest
```

## Security

- **Pre-commit hooks**: detect-secrets + gitleaks + private key detection
- **CI scanning**: gitleaks + pip-audit on every push/PR (`.github/workflows/security.yml`)
- **No secrets in code**: All credentials via environment variables / GitHub Secrets
- **`.env.local` gitignored**: Never committed

## Cost

| Service | Cost |
|---------|------|
| GitHub Actions | Free (public repo) |
| cron-job.org | Free |
| Claude API | ~$3-5/month (2 reports/day × 30 days) |
| All data APIs | Free tier |
| **Total** | **~$3-5/month** |

## Design Principles

- **Degrades gracefully** — Any single API outage won't crash the report
- **Verbose logging** — Every step prints to stdout for GitHub Actions debugging
- **Discord-aware** — Embeds split across messages to respect 6000 char limit
- **Deterministic parsing** — Bull/Bear/Rating/Confidence extracted with fallback patterns
- **Historical continuity** — Reads previous Discord reports to reference past calls
