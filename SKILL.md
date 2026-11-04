# Twitter Scraper

Twitter/X GraphQL scraper + pain miner. Self-hosted, Cloudflare-bypass (rnet), auto-cookie-refresh via CDP, multi-account.

**Server:** systemd `twitter-scraper.service` on `127.0.0.1:8765`
**Restart:** `systemctl restart twitter-scraper`
**Logs:** `journalctl -u twitter-scraper -f`

## Quick start

```bash
x status                          # health check
x user elonmusk 20                # scrape profile + tweets
x search "OpenAI" 50              # keyword search
x search "AI" --lang zh --min-followers 1000 --limit 10   # Chinese AI tweets from big accounts
x search "startup" --location London --exclude-replies    # London founders
x search "python" --verified --media-only 5               # verified accounts with media
x pain "CRM" --lang en --min-likes 5                      # English CRM pain signals
```

## Search filters (new in v4)

| Flag | Type | Detail |
|---|---|---|
| `--lang CODE` | Native | ISO 639-1: en, zh, ja, ko, fr, de, es, ar, ru, pt |
| `--product Latest\|Top` | Native | Sort order (default: Latest) |
| `--min-likes N` | Native | Minimum favorites |
| `--min-retweets N` | Native | Minimum retweets |
| `--verified` | Native | Blue-check accounts only |
| `--media-only` | Native | Tweets with images/video only |
| `--exclude-replies` | Native | No reply tweets |
| `--exclude-retweets` | Native | No retweets |
| `--since YYYY-MM-DD` | Native | Date range start |
| `--until YYYY-MM-DD` | Native | Date range end |
| `--min-followers N` | Post-filter | Minimum author follower count |
| `--location CITY` | Post-filter | Profile location substring match (case-insensitive) |

Post-filters (`min-followers`, `location`) fetch 3x the requested count then filter down — Twitter GraphQL doesn't support these natively.

**Limit syntax:** `x search "query" 20` (positional) or `x search "query" --limit 20` (flag). When mixing with other flags, use `--limit`.

## Endpoints (HTTP API)

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Liveness + cookie status |
| GET | `/session` | Re-grab live cookies from Chrome |
| GET | `/account/status` | Per-account cooldown status |
| POST | `/user` | `{username, limit}` |
| POST | `/search` | `{query, limit, product, lang?, min_faves?, min_retweets?, min_followers?, location?, since?, until?, exclude_replies?, exclude_retweets?, verified_only?, media_only?}` |
| POST | `/tweet` | `{text, reply_to?, media_ids?}` |
| POST | `/media` | `{file_path, media_type}` |
| POST | `/like` | `{tweet_id}` |
| POST | `/delete` | `{tweet_id}` |
| POST | `/pain` | `{keyword, limit?, min_score?, lang?, min_faves?, min_retweets?, min_followers?, location?, since?, until?}` |
| POST | `/refresh` | Force cookie re-grab |
| POST | `/login` | Open login UI |
| POST | `/account/switch` | `{username}` |

Default: `http://127.0.0.1:8765`. Override with `TWITTER_SCRAPE_HOST` / `TWITTER_SCRAPE_PORT`.

## Files

- `x` — CLI wrapper (v4, argparse-based, symlinked to `~/.local/bin/x`)
- `twx.py` — Python SDK (`from twx import Twitter`)
- `scripts/server.py` — HTTP API + self-healing cookie/session
- `scripts/rnet_twitter.py` — Async GraphQL client (Cloudflare bypass via rnet)
- `scripts/pain_miner.py` — Pain mining engine (18 query templates, 3-tier WTP scoring)
- `scripts/cookie_refresh.py` — 3-tier auth: CDP grab → Playwright auto-login → login flow
- `scripts/account_manager.py` — Multi-account state, round-robin, persistent cooldowns
- `scripts/.env` — Account config (ACCOUNT_1_USERNAME=@handle)
- `scripts/twitter_cookies.json` — Cached auth_token + ct0 (chmod 600)
- `storage/twitter/` — Scraped data dumps
