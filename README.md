# Discord Finance Bot

A scheduled Discord bot that delivers pre-market and post-market financial reports.

## Setup

Add `DISCORD_WEBHOOK_URL` as a GitHub Actions secret in your repository settings.

## Phases

- Phase 1 (current): Pipeline skeleton - Discord webhook delivery via GitHub Actions
- Phase 2: Market data (yfinance + Alpaca)
- Phase 3: News aggregation (Finnhub + RSS)
- Phase 4: Crypto data (CoinGecko + Binance)
- Phase 5: Politician trade disclosures (Capitol Trades)
- Phase 6: Polish, caching, error handling
