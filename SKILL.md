# twitter-scrape

Twitter/X GraphQL scraper + pain miner. Self-hosted, Cloudflare-bypass (rnet),
auto-cookie-refresh via CDP, multi-account. No API keys — uses your Chrome
session.

## Quick start

```bash
x status                          # health check
x user elonmusk 20                # scrape profile + tweets
x search "OpenAI" 50              # keyword search
x pain "CRM" --lang en --min-likes 5   # mine customer pain signals
x tweet "hello"                   # post
x grok "what is 5x5"              # chat with Grok via CDP
```

## Setup (one of two paths)

**Path A — one-liner:**
```bash
curl -fsSL https://raw.githubusercontent.com/dommurphy155/Twitter-scraper/main/install.sh | bash
```

**Path B — manual:**
```bash
git clone https://github.com/dommurphy155/Twitter-scraper.git
cd Twitter-scraper
python3 scripts/setup_wizard.py      # venv, deps, Chrome, login, systemd
```

### What the user must do

1. **Log into x.com.** Cookies are grabbed via CDP from your browser — no API key,
   no password stored. If Chrome isn't logged in, the wizard opens the login
   tab and waits.
2. **Keep Chrome alive.** Session persists in `scripts/.chrome-profile/`.
   Server re-attaches on boot; spawns headless Chromium if Chrome dies.
3. **Accounts (optional):** edit `scripts/.env`:
   ```
   ACCOUNT_1_USERNAME=@yourhandle
   ACCOUNT_2_USERNAME=@secondaccount
   ```
   For Grok rate-limit rotation.
4. **Overrides:** `TWITTER_SCRAPE_HOST` / `TWITTER_SCRAPE_PORT` (default
   `127.0.0.1:8765`). `TWITTER_SCRAPE_NO_AUTO_CHROME=1` disables auto-spawn.

Verify: `x status` → should show `ready`.

## Commands (`x`)

| Command | What it does |
|---|---|
| `status` | Server, Chrome, cookie health |
| `user <handle> [n]` | Scrape profile + tweets (max 200) |
| `search "<q>" [n]` | Keyword search with filters |
| `pain "<kw>" [n]` | Mine pain signals (WTP-scored) |
| `tweet "<text>"` | Post a tweet |
| `tweet-media "<text>" <file>` | Post with image/video |
| `reply "<text>" <id>` | Reply to a tweet |
| `like <id>` / `delete <id>` | Engage / delete |
| `login` | Re-authenticate via browser |
| `accounts` | Multi-account status |
| `grok "<msg>"` | Chat with Grok via CDP |
| `session` / `refresh` | Cookie re-grab |

## Search filters

Native (server-side): `--lang`, `--product Latest\|Top`, `--min-likes`,
`--min-retweets`, `--verified`, `--media-only`, `--exclude-replies`,
`--exclude-retweets`, `--since`, `--until`.

Post-filter (fetches 3x then trims): `--min-followers`, `--location`.

Limit syntax: `x search "q" 20` (positional) or `x search "q" --limit 20`.

## HTTP API

Default `http://127.0.0.1:8765` (override via env vars).

| Method | Path | Body |
|---|---|---|
| GET | `/health` | — |
| GET | `/session` | — |
| GET | `/account/status` | — |
| POST | `/user` | `{username, limit}` |
| POST | `/search` | `{query, limit, product, lang?, min_faves?, min_retweets?, min_followers?, location?, since?, until?, exclude_replies?, exclude_retweets?, verified_only?, media_only?}` |
| POST | `/tweet` | `{text, reply_to?, media_ids?}` |
| POST | `/media` | `{file_path, media_type}` |
| POST | `/like` | `{tweet_id}` |
| POST | `/delete` | `{tweet_id}` |
| POST | `/pain` | `{keyword, limit?, min_score?, lang?, min_faves?, min_retweets?, min_followers?, location?, since?, until?}` |
| POST | `/refresh` | — |
| POST | `/login` | — |
| POST | `/account/switch` | `{username}` |

## Python SDK

```python
from twx import Twitter
t = Twitter()
t.search("I hate my CRM", limit=50)
t.pain_mine("CRM", min_score=5)
t.user("elonmusk", limit=20)
t.tweet("hello world")
t.healthy()
```

## Files

- `install.sh` — one-line curl installer
- `scripts/setup_wizard.py` — first-run: venv, deps, Chrome, login, systemd
- `scripts/server.py` — HTTP API + self-healing cookies
- `scripts/rnet_twitter.py` — async GraphQL (Cloudflare bypass via rnet)
- `scripts/cookie_refresh.py` — 3-tier auth: CDP → Playwright → login flow
- `scripts/account_manager.py` — multi-account state, round-robin, cooldowns
- `scripts/pain_miner.py` — pain mining (18 templates, 3-tier WTP scoring)
- `twx.py` — Python SDK
- `x` — stdlib CLI (no deps)

## Auth flow (never fails)

1. Grab fresh cookies from live Chrome via CDP
2. If Chrome down, spawn headless Chromium + re-auth
3. If no credentials, return 401 with `POST /login` instruction — server never crashes

## Service (Linux)

```bash
systemctl restart twitter-scrape
journalctl -u twitter-scrape -f
```