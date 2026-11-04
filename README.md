# Twitter/X Scraper

**One-line installer:**

```bash
curl -fsSL https://raw.githubusercontent.com/dommurphy155/Twitter-scraper/main/install.sh | bash
```

That's it. The installer:
- creates a venv at `Twitter-scraper/venv/`
- installs `rnet`, `playwright`, `httpx` + Playwright Chromium
- detects your running Chrome (display `:1`, port 9222) and attaches to it
- if not logged in, opens the `x.com/i/flow/login` tab in your Chrome and waits for you to log in
- caches `auth_token` + `ct0` cookies in `twitter_cookies.json` (re-grabbed from the live chrome on every call)
- spawns its own headless Chrome on :9222 if none detected — **no manual `--remote-debugging-port` needed**
- installs a systemd service (if you have sudo) + symlinks `x` into `~/.local/bin`

**Use it:**

```bash
x status                    # health + cookie status
x user elonmusk 20          # scrape a profile + tweets
x search "OpenAI" 50       # keyword search
x login                     # re-open login flow
x grok "What is the weather?"   # chat with Grok via CDP
```

**How auth works (never fails):**
1. Server always tries to grab fresh cookies from your live Chrome via CDP first
2. If Chrome is down, spawns its own headless Chromium and re-auths
3. If no credentials in `.twitter_config.json`, errors with a clear hint — the server never crashes, the endpoint just returns `401` and a `POST /login` instruction

The Chrome session persists in `~/.config/google-chrome-debug/` (or `scripts/.chrome-profile/` for spawned copies) — your login survives reboots.

**Endpoints (raw HTTP):**

| Method | Path                  | Notes                                        |
|--------|-----------------------|----------------------------------------------|
| GET    | `/health`             | Liveness + cookie status                     |
| GET    | `/session`            | Re-grab live cookies from Chrome             |
| GET    | `/account/status`     | Per-account cooldown status                  |
| POST   | `/user`               | `{username, limit}`                          |
| POST   | `/search`             | `{query, limit, product}`                    |
| POST   | `/tweet`              | `{text, reply_to?}`                          |
| POST   | `/like`               | `{tweet_id}`                                 |
| POST   | `/delete`             | `{tweet_id}`                                 |
| POST   | `/refresh`            | Force cookie re-grab from live Chrome        |
| POST   | `/login`              | Open login UI + wait for completion          |
| POST   | `/grok/chat`          | `{message, conversation_id?}`                |
| POST   | `/grok/conversation`  | Get/create a conversation id                 |
| POST   | `/account/switch`     | `{username}` — pick active account           |

Default: `http://127.0.0.1:8765`. Override with `TWITTER_SCRAPE_HOST` / `TWITTER_SCRAPE_PORT`.

**Files:**

- `install.sh` — one-line curl installer (clone + run wizard)
- `scripts/setup_wizard.py` — first-run setup: venv, deps, Chrome attach/spawn, login flow, systemd, `x` symlink
- `scripts/server.py` — HTTP API + self-healing cookie/session management
- `scripts/rnet_twitter.py` — async GraphQL client (Cloudflare bypass via `rnet` Chrome TLS emulation)
- `scripts/cookie_refresh.py` — 3-tier auth: CDP grab → Playwright auto-login → login flow
- `scripts/account_manager.py` — multi-account state, round-robin, persistent cooldowns
- `scripts/pain_miner.py` — pain mining engine (18 query templates, 3-tier WTP scoring)
- `twx.py` — Python SDK (`from twx import Twitter`)
- `x` — stdlib CLI wrapper (no Python deps needed)

## Agent Setup

Any agent can set this up anywhere on any machine. Two paths:

### Path A — One-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/dommurphy155/Twitter-scraper/main/install.sh | bash
```

That clones the repo, creates a venv, installs `rnet` + `playwright` + `httpx`, installs Playwright Chromium, attaches to (or spawns) a Chrome session on `:9222`, walks you through the x.com login, installs the systemd service if you have sudo, and symlinks `x` into `~/.local/bin`.

### Path B — Manual

```bash
git clone https://github.com/dommurphy155/Twitter-scraper.git
cd Twitter-scraper
python3 scripts/setup_wizard.py      # interactive: venv, deps, Chrome, login, systemd
```

### What the user must do

1. **Log into x.com.** The scraper needs a real Chrome session — it grabs `auth_token` + `ct0` cookies via CDP from your browser. No API key, no password stored. If your Chrome isn't already logged in, the wizard opens the login tab and waits for you.
2. **Keep Chrome alive.** The session persists in `scripts/.chrome-profile/`. Reboots are fine — the server re-attaches on startup. If Chrome is killed, the server spawns its own headless Chromium and re-auths.
3. **Add accounts (optional).** Edit `scripts/.env`:
   ```
   ACCOUNT_1_USERNAME=@yourhandle
   ACCOUNT_2_USERNAME=@secondaccount
   ```
   Needed for Grok rate-limit rotation. Without it, `x accounts` shows "no accounts configured".
4. **Override defaults (optional).** `TWITTER_SCRAPE_HOST` / `TWITTER_SCRAPE_PORT` env vars change the HTTP endpoint (default `127.0.0.1:8765`). `TWITTER_SCRAPE_NO_AUTO_CHROME=1` disables auto-spawn.

### Verify it works

```bash
x status
```

You should see `ready — you are logged in and ready to post, search, and mine`.

### Raw HTTP

Default `http://127.0.0.1:8765`. Endpoints: `GET /health`, `GET /session`, `GET /account/status`, `POST /user`, `POST /search`, `POST /tweet`, `POST /like`, `POST /delete`, `POST /media`, `POST /refresh`, `POST /login`, `POST /grok/chat`, `POST /account/switch`. Python SDK: `from twx import Twitter`.
