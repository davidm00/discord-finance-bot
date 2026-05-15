import os
import sys
import requests


def load_env_local(path: str = ".env.local") -> None:
    """Load key/value pairs from .env.local.

    For local testing, we *override* any existing environment variables so you don't
    accidentally keep using an old key from your shell/session.
    """

    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k:
                os.environ[k] = v


def main() -> int:
    load_env_local()

    token = os.getenv("FINNHUB_API_KEY")
    if not token:
        print("ERROR: FINNHUB_API_KEY not set. Put it in .env.local or set it in your shell.", file=sys.stderr)
        return 2

    if token != token.strip() or any(c.isspace() for c in token):
        print("WARNING: FINNHUB_API_KEY appears to contain whitespace. Re-paste it without spaces.", file=sys.stderr)

    print("KEY_LEN:", len(token))

    news_url = "https://finnhub.io/api/v1/news"
    quote_url = "https://finnhub.io/api/v1/quote"

    def do_request(mode: str, endpoint: str):
        if endpoint == "news":
            if mode == "query":
                return requests.get(news_url, params={"category": "general", "token": token}, timeout=15)
            if mode == "header":
                return requests.get(news_url, params={"category": "general"}, headers={"X-Finnhub-Token": token}, timeout=15)
        if endpoint == "quote":
            if mode == "query":
                return requests.get(quote_url, params={"symbol": "AAPL", "token": token}, timeout=15)
            if mode == "header":
                return requests.get(quote_url, params={"symbol": "AAPL"}, headers={"X-Finnhub-Token": token}, timeout=15)
        raise ValueError((mode, endpoint))

    def run_check(endpoint: str) -> int:
        # Try query auth first, then retry with header auth if we get a 401/403.
        last_exc = None
        r = None
        mode_used = None

        for mode in ("query", "header"):
            try:
                r = do_request(mode, endpoint)
                mode_used = mode
            except requests.RequestException as e:
                last_exc = e
                continue

            if r.status_code in (401, 403) and mode == "query":
                continue

            break

        if r is None:
            print(f"ERROR: Request failed: {last_exc}", file=sys.stderr)
            return 1

        print(f"ENDPOINT: {endpoint}")
        print("AUTH_MODE:", mode_used)
        print("HTTP_STATUS:", r.status_code)

        if r.status_code != 200:
            print("RESPONSE_TEXT:", r.text[:500])
            return 1

        if endpoint == "news":
            data = r.json()
            print("ITEMS:", len(data) if isinstance(data, list) else "(not a list)")
            if isinstance(data, list) and data:
                first = data[0]
                print("FIRST_HEADLINE:", first.get("headline"))
                print("FIRST_SOURCE:", first.get("source"))
                print("FIRST_URL:", first.get("url"))
        else:
            data = r.json()
            print("QUOTE_KEYS:", sorted(list(data.keys())))
            print("QUOTE_SAMPLE:", data)

        return 0

    rc1 = run_check("quote")
    rc2 = run_check("news")
    return 0 if (rc1 == 0 and rc2 == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
