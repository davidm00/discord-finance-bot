# Discord Finance Bot

A scheduled Discord bot that delivers pre-market and post-market financial reports.

## Setup

Add `DISCORD_WEBHOOK_URL` as a GitHub Actions secret in your repository settings.

## Local testing (no key leaks)

1) Install deps:

```bash
python -m pip install -r requirements.txt
```

2) Create a repo-root `.env.local` file (this is gitignored) and put keys there:

```env
DISCORD_WEBHOOK_URL=...
ANTHROPIC_API_KEY=...
FINNHUB_API_KEY=...
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=...
```

3) Run in dry-run mode (builds the embed but does not post to Discord):

```bash
set DRY_RUN=1
python bot/report.py
```

Remove `DRY_RUN` to actually send to your webhook.

## Phases

- Phase 1 (current): Pipeline skeleton - Discord webhook delivery via GitHub Actions
- Phase 2: Market data (yfinance + Alpaca)
- Phase 3: News aggregation (Finnhub + RSS)
- Phase 4: Crypto data (CoinGecko + Binance)
- Phase 5: Politician trade disclosures (Capitol Trades)
- Phase 6: Polish, caching, error handling
