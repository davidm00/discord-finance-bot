# Discord Finance Bot — Roadmap
*Last updated: May 2026 | Informed by 125+ source research fleet (arXiv, GitHub, academic papers)*

---

## ✅ Completed

### Pipeline Foundation
- GitHub Actions cron + Discord webhook delivery
- cron-job.org external scheduler (3 jobs: pre-market 8AM ET, post-market 4:15PM ET, weekly 8AM ET Saturday)
- Discord bot token for reading channel history (previous report context)
- Local .env.local + DRY_RUN + TEST_MOCK/TEST_LIVE modes for safe local development

### Data Sources
- **Equities**: yfinance (SPY, QQQ, DIA, VIX)
- **Crypto**: CoinGecko top-20 snapshot + altcoin mover alerts (>=8% 24h)
- **News**: Finnhub + CNBC/MarketWatch/Bloomberg RSS with headline deduplication
- **Political trades**: Capitol Trades scrape (>=25K, sorted by disclosure/published date)
- **Government contracts**: USASpending.gov API (>=50M, labeled 🆕 new vs 🔁 recurring)
- **Earnings**: Finnhub calendar filtered to watchlist + major tickers
- **Macro context**: 10-Year Treasury yield (TNX), Dollar Index (DXY), Fear & Greed Index

### Analysis
- Claude Sonnet 4.6 generating plain-English pre-market and post-market briefings
- Ticker recommendations (BUY/SELL/HOLD/WATCH) with confidence levels and reasoning
- Thematic watchlist (defense, cyber, energy, tech) baked into Claude context
- Previous report context via Discord history (continuity and prediction tracking)
- Prompt caching on system prompt (cost + latency optimization)
- Correlation detection between politician trades and government contracts

### Reports
- Daily pre-market: "what to watch today" framing
- Daily post-market: "what happened and why" framing
- Weekly summary (Saturday 8AM ET): week in review, biggest story, political activity,
  bot scorecard, week ahead preview, next week watchlist

### Infrastructure
- Signal logging to CSV (date, ticker, action, confidence, price, report type, reasoning)
- Signals persisted via GitHub Actions cache + 90-day artifact upload
- Parallel async data fetching (6 sources in ~2s vs ~15s sequential)
- Verbose logging throughout for GitHub Actions debugging
- Three-tier test suite (mock, live connectivity, end-to-end pipeline)
- Discord embed character limit safety with graceful clamping

---

## 🔬 Key Research Findings
*From 7-agent research fleet across 125+ sources — informs all roadmap decisions*

- **Data quality > model quality**: FinGPT's value is data curation not model architecture.
  Our multi-source aggregation is already a competitive advantage.
- **Congressional alpha is at DISCLOSURE time**: Lazzaretto (2024, SSRN 4816497) shows
  90+ bps abnormal returns after filing date not trade date. Already implemented.
- **Always inject data, never ask LLM to recall**: FinanceBench shows GPT-4 gets 81%
  of financial QA wrong without source data. We already do this correctly.
- **API-first, self-host later**: Fine-tune only after 6-12 months of accumulated data.
  Claude outperforms most fine-tuned models on reasoning at our budget.
- **RSS feeds are declining**: Bloomberg/Reuters RSS increasingly throttled.
  Migrate toward API-based news over time.
- **Validation before trust**: Every serious implementation tracks and backtests signals.
  We are building toward this with signal logging.
- **Bull/Bear debate improves decisions**: TradingAgents (arXiv:2412.20138) shows
  forcing opposing viewpoints before a ticker call improves decision quality.

---

## 🔜 Do Now
*No data accumulation required. Pure improvements to existing pipeline.*

### Pipeline Resilience
- **requests-cache SQLite backend**: HTTP caching for all API calls. TTL strategy:
  crypto 5min, stocks 15min during market hours, after-hours 4hr, news 30min,
  congressional trades 12hr, USASpending 24hr. Stale data served with timestamp on failure.
- **tenacity retry with exponential backoff**: 3 retries, 2s initial wait, doubling.
  Wraps all fetchers. Covers transient API failures gracefully.
- **DefeatBeta as yfinance fallback**: Primary → DefeatBeta → cached stale → error message.
  yfinance has 2816+ open issues. Production systems always use 2+ sources.
- **exchange-calendars for market state**: Replace manual weekday checks with proper
  holiday-aware calendar. Add "Market Closed / Pre-Market / Open" to report header.

### Analysis Quality
- **Bull/Bear debate structure**: Add explicit Bull case / Bear case to ticker
  recommendation prompt before issuing BUY/SELL/HOLD/WATCH. Single Claude call,
  structured prompt sections. Research: TradingAgents, arXiv:2412.20138.
- **Source reliability weighting**: Wire services 1.0 → Financial media 0.8 →
  Analysis 0.6 → RSS aggregators 0.4. Pass weights to Claude as context.
  Flag multi-source convergence as high-confidence signal.
- **Event classification for news**: Classify headlines into earnings / M&A /
  regulatory / geopolitical / macro / executive before analysis.
  Different event types get different analytical framing in Claude prompt.

### Truth Social Experiment
- Best-effort RSS feed for presidential posts with direct market implications.
  Degrades gracefully if unavailable. Surface in daily report with market context.
  Test reliability before committing to it as a permanent data source.

---

## 📅 Do After 30 Days
*Requires signal log accumulation. Start clock from May 2026.*

### VectorBT Backtesting
- Run VectorBT backtest on accumulated signal CSV.
- Sweep confidence thresholds 50-95%, measure win rate, Sharpe ratio, max drawdown.
- Generate QuantStats HTML performance report.
- Questions to answer: Do HIGH confidence calls outperform MEDIUM/LOW? Which sectors
  are the bot's strongest signals? Are WATCH calls more reliable than BUY calls?
- **Prerequisite**: 30+ days of signal logs with enough trades to be statistically meaningful.

### Signal-Informed Prompt Tuning
- Use backtest results to iteratively improve Claude prompts.
- If WATCH signals consistently outperform BUY signals, adjust thresholds.
- If certain sectors consistently wrong, add sector-specific context.
- If HIGH confidence consistently wrong, recalibrate confidence criteria.

---

## 📅 Do After Backtesting Validates Signals
*Don't paper trade signals we haven't validated.*

### Alpaca Paper Trading
- Connect Alpaca free paper trading API.
- Bot's validated BUY/SELL/WATCH calls executed as paper trades automatically.
- Weekly scorecard tracks paper portfolio performance vs SPY as benchmark.
- **Prerequisite**: Positive Sharpe ratio on backtested signals over 30+ days.

### Weekly Bot Scorecard (Meaningful Version)
- Right now the scorecard is limited by Discord history window.
- Once signals are logged to CSV and backtested, the scorecard becomes a real
  performance tracking tool with full history.
- **Prerequisite**: Signal CSV with 30+ days of data.

---

## 📅 Do When Scale Justifies It
*Currently Claude API costs ~$0.90/month. These make sense at higher volume.*

### FinBERT Sentiment Preprocessing
- Use ProsusAI/finbert (HuggingFace free tier) to pre-classify headlines
  as positive/negative/neutral before sending to Claude.
- Reduces Claude token usage 50-80% for news processing.
- F1 score 0.880 on financial sentiment — comparable to GPT-4 zero-shot.
- **Trigger**: Claude API costs consistently exceed $5/month, OR
  running more than 4 reports/day.

### discord.py Upgrade + Watchlist Command
- Upgrade from webhook-only to full discord.py bot.
- `/watch TICKER` adds ticker to personal watchlist included in daily analysis.
- `/portfolio add TICKER shares` with P&L tracking in post-market report.
- Requires persistent hosting (Railway or Render free tier ~$5/month).
- **Trigger**: When you want interactive commands, not just scheduled reports.

### Sector Rotation Signals
- Track sector ETFs (XLE, XLK, XLF, XLV, XLI) week-over-week.
- Surface rotation signals in weekly summary.
- **Trigger**: After watchlist/portfolio features are live.

### Fed Calendar + Macro Events
- FRED API for Fed meeting dates and major economic data releases.
- Countdown alerts: "CPI in 2 days", "Fed decision Thursday".
- **Trigger**: Natural addition once macro context is well-established.

---

## 🔭 Long-Term / Exploratory
*6-12 months out. Requires significant data accumulation or infrastructure.*

### Local LLM for Preprocessing
- Ollama + Mistral or LLaMA for headline classification and data preprocessing.
- Hybrid: local model filters/scores, Claude generates final report.
- **Prerequisites**: 6-12 months of accumulated training data, GPU hardware,
  Claude API costs high enough to justify infrastructure investment.
- Research: arXiv:2311.10723 — API-first until task-specific performance inadequate.

### Autopilot Trading
- Execute real trades through brokerage API based on validated signals.
- **Hard prerequisites**: 6+ months paper trading with positive Sharpe ratio,
  position sizing rules, stop losses, daily loss limits, human confirmation gates.
- Not until backtesting AND paper trading both prove signal reliability.

### Custom Thematic Portfolios
- Claude proposes thematic baskets (defense+cyber, energy transition, AI infrastructure)
  using contract data, politician trades, and news as inputs.
- Alpaca paper-trades the basket automatically.
- **Prerequisite**: Autopilot trading infrastructure in place.

### Decision Memory / Reflection Loop
- Store past analyses with outcomes, feed relevant past decisions into future prompts.
- Creates a learning loop without fine-tuning.
- Research: FinAgent dual-level reflection, 36% average profit improvement (arXiv:2402.18485).
- **Prerequisite**: 6+ months of signal logs with outcome tracking.

---

## 💡 Known Limitations / Tech Debt

| Issue | Impact | Plan |
|-------|--------|------|
| Capitol Trades scraping fragile, may violate ToS | Political trades section could break | Monitor; upgrade to Quiver Quant API (~$30/mo) if scraper breaks |
| yfinance unofficial, 2816+ open issues | Market data fetch failures | Add DefeatBeta fallback (Do Now) |
| RSS feeds declining in reliability | News quality degrading over time | Migrate to Finnhub API-based news |
| No signal validation yet | Can't measure if signals work | Signal logging done; backtest at 30 days |
| GitHub Actions cache expires after 7 days of inactivity | Signal CSV could reset | Acceptable given twice-daily runs; upgrade to Supabase if needed |
| Discord embed character limits truncate long analyses | Report sometimes cut off | Graceful clamping in place; monitor |
| Bot scorecard limited by Discord history window | Weekly scorecard incomplete | Resolved when signal CSV has full history |
| Fear & Greed uses Alternative.me (crypto-focused) not CNN | Slightly different methodology | Monitor; restore CNN endpoint if it comes back |
