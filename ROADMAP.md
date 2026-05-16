# Discord Finance Bot — Roadmap
*Last updated: May 2026 | Informed by 125+ source research fleet (arXiv, GitHub, academic papers)*

---

## ✅ Completed

### Phase 1 — Pipeline Skeleton
GitHub Actions cron + Discord webhook delivery via cron-job.org external scheduler.

### Phase 2 — Market Data + AI Analysis
yfinance equity snapshots (SPY, QQQ, DIA, VIX) + Claude Sonnet 4.6 generating
plain-English pre-market and post-market briefings.

### Phase 3 — News Aggregation
Finnhub general market news + RSS feeds (CNBC, MarketWatch, Bloomberg).
Headlines fed into Claude as context for grounded analysis.

### Phase 4 — Enhanced Crypto Data
CoinGecko top-20 snapshot for BTC/ETH/SOL + altcoin mover alerts (>=8% 24h move).

### Phase 5 — Political Trades + Government Contracts + Correlation
Capitol Trades scrape for congressional stock trades (>=25K).
USASpending.gov API for major contract awards (>=50M, defense/energy/tech/cyber).
Claude flags correlations between politician trades and contract awards within 30 days.
Contracts labeled 🆕 new vs 🔁 recurring.

### Phase 6 — Polish + Intelligence Layer
- Plain-English tone rewrite (no jargon)
- Ticker recommendations (BUY / SELL / HOLD / WATCH) with confidence levels
- Previous report context via Discord history API (continuity across runs)
- Thematic watchlist (defense, cyber, energy, tech)
- Earnings calendar (Finnhub, filtered to relevant tickers)
- pip caching for faster GitHub Actions runs
- Verbose logging throughout for easy debugging
- Dry run mode + local output files for local testing
- Parser handles both daily and weekly ticker formats

### Phase 7 — Weekly Summary Report
Saturday 8:00 AM ET cron via cron-job.org.
Weekly performance (Monday open → Friday close), biggest story, political activity,
bot scorecard (scores previous BUY/SELL/HOLD/WATCH calls vs actual closes),
week ahead preview, next week watchlist.

### Infrastructure
- cron-job.org external scheduler (3 jobs: pre-market, post-market, weekly)
- GitHub Actions secrets for all API keys
- Discord bot token for reading channel history
- Local .env.local + DRY_RUN mode for testing without posting

---

## 🔬 Research Findings (May 2026 Fleet)
*Key findings from 7-agent research fleet across 125+ sources that inform the roadmap*

- **Data quality > model quality** (Reports 01, 02, 04, 07): FinGPT's value is
  data curation, not model architecture. Our multi-source aggregation is already
  a competitive advantage. Focus on pipeline resilience over model upgrades.

- **Congressional trade alpha is at DISCLOSURE time** (Lazzaretto 2024, SSRN 4816497):
  90+ bps abnormal returns occur after the filing date, not the trade date.
  Our scraper should prioritize freshly-published disclosures sorted by published date.

- **Always inject data, never ask LLM to recall** (FinanceBench, arXiv:2311.11944):
  GPT-4 gets 81% of financial QA wrong without source data. We already do this
  correctly by injecting market data into every Claude prompt.

- **API-first, self-host later** (arXiv:2311.10723): Start with zero/few-shot API
  calls. Fine-tune only after 6-12 months of accumulated training data.
  At $30-40/month Claude outperforms most fine-tuned models on reasoning tasks.

- **RSS feeds are declining** (Report 04): Bloomberg, Reuters RSS increasingly
  throttled. Migrate toward API-based news (Finnhub, FinNLP) over time.

- **Multi-source fallback is non-negotiable** (Reports 02, 05, 06): yfinance has
  2816+ open issues. Production systems always use at least 2 data sources.

- **Validation before trust** (Reports 05, 06): Every serious implementation
  includes backtesting. We are the outlier in not having signal validation.

- **Bull/Bear debate improves decisions** (TradingAgents, arXiv:2412.20138):
  Forcing consideration of opposing viewpoints before a ticker call improves
  decision quality. Achievable in a single structured Claude prompt.

---

## 🔜 Near-Term (Session 1 — Next Up)

### Signal Logging to CSV
Log every BUY/SELL/HOLD/WATCH call to a gitignored CSV file:
`data/signals.csv` — columns: date_et, ticker, action, confidence, price_at_signal,
report_type (pre/post/weekly), reasoning_summary.
This is the foundation for all future validation. Zero cost, Python built-in csv module.
GitHub Actions artifact used to persist the file between runs.
**Why**: We cannot know if our signals work without tracking them.
**Research backing**: Every serious implementation tracks signals (Reports 05, 06).

### News Deduplication
Hash headlines before feeding to Claude. Same story from CNBC + MarketWatch +
Bloomberg + Finnhub currently treated as 4 independent signals.
Implementation: SHA256 hash of normalized headline text, stored in-memory per run.
**Why**: Reduces Claude token usage, prevents artificial signal amplification.
**Research backing**: Report 04 identifies deduplication as key commercial feature.

### Capitol Trades — Sort by Published Date
Change scraper to sort/filter by "Published" (disclosure/filing) date not "Traded" date.
The "Published" and "Filed After" columns are already in the Capitol Trades table.
Sort fetched results by published date descending in Python after scraping.
**Why**: Lazzaretto (2024) shows alpha is at disclosure time not trade time.
**Research backing**: Report 03, SSRN 4816497.

### TNX + DXY + Fear & Greed as Claude Context
Add three silent data inputs to market_data.py:
- ^TNX: 10-Year Treasury yield (yfinance, free)
- DX-Y.NYB: US Dollar Index (yfinance, free)
- Fear & Greed Index: CNN endpoint, no key required
Pass as context to Claude only — no new embed fields.
**Why**: Claude currently infers rate/dollar/sentiment from headlines.
Giving it actual numbers improves analysis precision.

### Prompt Caching on System Prompt
Add cache_control to the static system prompt block in claude_analysis.py.
5-minute TTL covers same-day pre/post market pair.
Small cost saving (~10%) and marginal latency improvement.
**Research backing**: Anthropic prompt caching documentation.

### Parallel Async Data Fetching
Replace sequential fetching with ThreadPoolExecutor for independent API calls.
Market data, crypto, news, political data all fetched concurrently.
Expected runtime reduction: ~15s → ~5s.
**Research backing**: Report 02, aiohttp/asyncio patterns.

---

## 📋 Near-Term (Session 2 — Pipeline Resilience)

### requests-cache SQLite Backend
Add HTTP caching layer to all API calls using requests-cache library.
TTL strategy: crypto 5min, stocks during market 15min, after-hours 4hr,
news 30min, congressional trades 12hr, USASpending 24hr.
Stale data served with timestamp annotation on API failure.
**Research backing**: Report 02, finagg pattern.

### tenacity Retry with Exponential Backoff
Wrap all fetchers with tenacity retry decorator.
3 retries, 2s initial wait, doubling. Covers transient API failures.
**Research backing**: Report 02.

### DefeatBeta as yfinance Fallback
Add DefeatBeta API as secondary source when yfinance fails.
Primary → DefeatBeta → cached stale data → error message pattern.
**Research backing**: Report 02, FinanceToolkit fallback pattern.

### exchange-calendars for Market State Detection
Replace manual weekday checks with exchange-calendars library.
Proper handling of holidays, early closes, pre/post market windows.
Add "Market Closed" / "Pre-Market" / "Open" status to report header.
**Research backing**: Report 02.

---

## 📋 Near-Term (Session 3 — Analysis Quality)

### Bull/Bear Debate Structure in Claude Prompt
Add explicit Bull case / Bear case sections to ticker recommendation prompt.
Forces Claude to consider opposing arguments before issuing BUY/SELL/HOLD/WATCH.
Implemented as structured prompt sections, not additional API calls.
**Research backing**: TradingAgents (76K stars), arXiv:2412.20138, Report 01.

### Source Reliability Weighting for News
Assign reliability tiers to news sources:
Wire services (Reuters, AP) 1.0 → Financial media (Bloomberg, WSJ) 0.8 →
Analysis (Seeking Alpha) 0.6 → RSS aggregators 0.4.
Pass weights to Claude as context. Flag multi-source convergence as high-confidence.
**Research backing**: Report 04, commercial sentiment product methodology.

### Event Classification for News
Classify headlines into categories before Claude analysis:
earnings / M&A / regulatory / geopolitical / macro / executive.
Simple keyword classifier handles 80% of cases.
Different event types get different analytical framing in Claude prompt.
**Research backing**: Report 04, Bloomberg/RavenPack methodology.

### VectorBT Backtesting
After 30+ days of signal logs, run VectorBT backtest.
Sweep confidence thresholds 50-95%, measure win rate, Sharpe ratio, max drawdown.
Generate QuantStats HTML performance report.
**Research backing**: Report 06, VectorBT documentation.

---

## 📋 Medium-Term

### Truth Social / Presidential News Tracking
Best-effort RSS feed for presidential posts with direct market implications.
Degrades gracefully if unavailable. Surface in daily report with market context.

### Watchlist Command (discord.py upgrade)
Upgrade from webhook-only to full discord.py bot.
`/watch TICKER` adds ticker to personal watchlist included in daily analysis.
Requires persistent hosting (Railway or Render free tier).

### Portfolio Tracking
`/portfolio add TICKER shares` command.
Post-market report includes personal P&L summary.
Lightweight storage via CSV or Supabase free tier.

### Sector Rotation Signals
Track sector ETFs (XLE, XLK, XLF, XLV, XLI) week-over-week.
Surface rotation signals in weekly summary.

### Fed Calendar + Macro Events
FRED API for Fed meeting dates and major economic data releases.
Countdown alerts in pre-market report: "CPI in 2 days", "Fed decision Thursday".

### Alpaca Paper Trading
Connect Alpaca free paper trading API.
Bot's BUY/SELL/WATCH calls executed as paper trades automatically.
Weekly scorecard tracks paper portfolio vs SPY benchmark.

### FinBERT Sentiment Pre-classification
Use ProsusAI/finbert (HuggingFace free tier) to pre-classify headlines
as positive/negative/neutral before sending to Claude.
Reduces Claude token usage 50-80% for news processing.
Only implement when Claude API costs exceed $5/month.
**Research backing**: Reports 01, 04, 07. F1 score 0.880 on financial sentiment.

---

## 🔭 Long-Term / Exploratory

### Local LLM for Preprocessing
Ollama + Mistral or LLaMA for headline classification and data preprocessing.
Hybrid approach: local model filters/scores, Claude generates final report.
Prerequisites: 6-12 months of accumulated training data, GPU hardware.
**Research backing**: Report 07, arXiv:2311.10723.

### Backtesting-Informed Prompt Tuning
Use VectorBT backtest results to iteratively improve Claude prompts.
If WATCH signals outperform BUY signals, adjust confidence thresholds.
If certain sectors consistently wrong, add sector-specific context.

### Autopilot Trading
Execute real trades through brokerage API based on validated signals.
Hard prerequisites: 6+ months paper trading, positive Sharpe ratio,
position sizing rules, stop losses, daily loss limits, human confirmation gates.
Long-term stretch goal — not until backtesting proves signal reliability.

### Custom Thematic Portfolios
Claude proposes thematic baskets (defense+cyber, energy transition, AI infrastructure)
using contract data, politician trades, and news as inputs.
Alpaca paper-trades the basket automatically.

---

## 💡 Known Limitations / Tech Debt

- Capitol Trades scraping is fragile and may violate ToS
  → Monitor reliability; upgrade to Quiver Quant API (~$30/mo) if it breaks
- yfinance is unofficial with 2816+ open issues
  → Add DefeatBeta fallback in Session 2
- RSS feeds declining in reliability
  → Migrate to Finnhub API-based news over time (Session 2+)
- No signal validation yet
  → Signal logging is Session 1 priority
- Discord embed character limits occasionally truncate long analyses
- Bot scorecard requires Discord history which only covers recent messages
- GitHub Actions cron replaced by cron-job.org due to free tier unreliability
- Capitol Trades currently sorted by trade date, should be publication date
  → Fix in Session 1
