# Twitter/X Scraper CLI (`x`)

A systemd-powered Twitter/X scraper with **automatic cookie refresh** that runs as a background service with a simple `x` command available everywhere on your system.

## ✨ Key Features

- **Auto Cookie Refresh**: When cookies expire (403 error), the server automatically logs in via Playwright browser automation and extracts fresh cookies
- **Global CLI**: `x` command works from any directory, any venv, system-wide
- **Cloudflare Bypass**: Uses Chrome TLS fingerprint emulation via `rnet`
- **Headless Operation**: Runs in background via systemd, auto-restarts on crash

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         YOUR TERMINAL (Anywhere)                        │
│                                                                         │
│    ┌─────────┐    HTTP Request     ┌───────────────────────────────┐   │
│    │   `x`   │ ─────────────────→ │   twitter-scrape.service      │   │
│    │  CLI    │    Port 8765        │   (systemd managed)           │   │
│    │         │ ←─────────────────  │                               │   │
│    └─────────┘    JSON Response    │  ┌─────────────────────────┐  │   │
│        ↑                           │  │   server.py             │  │   │
│   Uses ONLY                        │  │   Python 3.12 venv      │  │   │
│   Python stdlib                    │  │   ┌─────────────────┐   │  │   │
│   (no deps!)                       │  │   │ rnet_twitter.py │   │  │   │
│        │                           │  │   │ cookie_refresh.py│  │  │   │
│   Can run from                     │  │   └─────────────────┘   │  │   │
│   ANY venv/folder                  │  │           ↓           │  │   │
│   system-wide                      │  │      Twitter/X        │  │   │
│                                    │  │      GraphQL API      │  │   │
│                                    │  └─────────────────────────┘  │   │
│                                    └───────────────────────────────┘   │
│                                                  ↑                      │
│                                                  │                      │
│                                    ┌─────────────┴────────────┐         │
│                                    │  Playwright Headless     │         │
│                                    │  Chrome (auto-login)     │         │
│                                    └──────────────────────────┘         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Installation

```bash
# 1. Clone the repo
git clone git@github.com:dommurphy155/Twitter-scraper.git
cd Twitter-scraper

# 2. Install the service
sudo bash install-service.sh

# 3. Set up auto-refresh credentials
cp .twitter_config.example.json .twitter_config.json
# Edit with your Twitter username/password
nano .twitter_config.json

# 4. Restart to pick up config
sudo systemctl restart twitter-scrape

# 5. Test
x status
x help
```

### Requirements

- Python 3.12+ (for the server venv)
- Playwright will auto-install Chromium browser on first run

---

## 🔑 Auto Cookie Refresh Setup

Create `.twitter_config.json` in the skill directory:

```json
{
  "username": "your_twitter_handle",
  "password": "your_twitter_password",
  "email": "your_email@example.com"
}
```

**Security note**: This file is in `.gitignore` and never committed.

**How it works:**
1. When Twitter returns 403/401, server detects expired cookies
2. Launches headless Chrome via Playwright
3. Navigates to x.com, logs in with your credentials
4. Extracts fresh `auth_token` and `ct0` cookies
5. Saves to `twitter_cookies.json` and continues the request

**Manual refresh:**
```bash
x refresh  # Force cookie refresh anytime
```

---

## 📋 Commands

### Check Status
```bash
x status              # Shows server status + cookie validity
```

### Scrape a User
```bash
x user elonmusk                    # Default: 200 tweets
x user jack --limit 50             # Custom limit
```

Output saved to: `storage/twitter/{username}.json`

### Search Tweets
```bash
x search "OpenAI lang:en"                       # Basic search
x search "python" --limit 200                   # Get 200 results
x search "AI" --product Top                     # Sort by relevance
x search '"machine learning" min_faves:10'      # Exact phrase + filters
```

**Search operators:**
- `"exact phrase"` — exact match
- `lang:en` — language filter
- `min_faves:10` — minimum likes
- `since:2026-01-01` — date range
- `from:username` — tweets from user
- `-filter:replies` — exclude replies

Output saved to: `storage/twitter/search_{query}.json`

### Post a Tweet
```bash
x tweet "Hello world!"
x tweet "This is a reply" --reply-to 1234567890
```

### Like a Tweet
```bash
x like 1234567890
```

### Delete Your Tweet
```bash
x delete 1234567890
```

### Refresh Cookies (Manual)
```bash
x refresh             # Force re-login and cookie refresh
```

### Get Help
```bash
x help
x user --help
x search --help
```

---

## 📁 File Locations

| File | Purpose |
|------|---------|
| `~/.openclaw/skills/twitter_scrape/` | Skill directory |
| `~/.openclaw/skills/twitter_scrape/venv/` | Python 3.12 venv with rnet + playwright |
| `~/.openclaw/skills/twitter_scrape/server.py` | API server (auto-refresh enabled) |
| `~/.openclaw/skills/twitter_scrape/cookie_refresh.py` | Browser automation for login |
| `~/.openclaw/skills/twitter_scrape/x` | CLI client (any Python) |
| `~/.openclaw/skills/twitter_scrape/.twitter_config.json` | Your credentials (NOT in git) |
| `~/.openclaw/skills/twitter_scrape/twitter_cookies.json` | Auth tokens (auto-refreshed) |
| `~/.openclaw/skills/twitter_scrape/storage/twitter/` | Scraped JSONs |
| `~/.local/bin/x` | Symlink to CLI (in your PATH) |

---

## 🔧 Service Management

```bash
# Check status
sudo systemctl status twitter-scrape

# View logs
sudo journalctl -u twitter-scrape -f

# Restart
sudo systemctl restart twitter-scrape

# Stop
sudo systemctl stop twitter-scrape

# Start on boot
sudo systemctl enable twitter-scrape
```

---

## 📊 Output Format

### User Scrape (`{username}.json`)
```json
{
  "scraped_at": "2026-03-22T10:30:00",
  "profile": {
    "id": "123456789",
    "username": "elonmusk",
    "name": "Elon Musk",
    "bio": "...",
    "followers_count": 123456789,
    "following_count": 1234,
    "tweets_count": 12345
  },
  "tweets": [...],
  "tweets_count": 200
}
```

### Search Results (`search_{query}.json`)
```json
{
  "scraped_at": "2026-03-22T10:30:00",
  "query": "OpenAI",
  "product": "Latest",
  "tweets": [
    {
      "id": "1234567890123456789",
      "text": "Tweet content...",
      "author": "username",
      "display_name": "Display Name",
      "favorite_count": 123,
      "reply_count": 45,
      "retweet_count": 67,
      "views": 8901,
      "created_at": "Thu Mar 22 10:30:00 +0000 2026",
      "url": "https://x.com/username/status/1234567890123456789",
      "is_reply": false,
      "is_quote": false
    }
  ],
  "tweets_count": 100
}
```

---

## 🛡️ How It Bypasses Cloudflare

The key is **rnet** - a Rust HTTP client with TLS fingerprint emulation:

```python
from rnet import Emulation

# Creates TLS handshake identical to Chrome 133
client = RnetClient(emulation=Emulation.Chrome133)
```

**Normal scrapers** → Python requests → Cloudflare sees "Python-requests" → **BLOCKED**

**Our scraper** → rnet (Rust) → TLS looks like Chrome 133 → **ALLOWED**

---

## 🔥 Why ChatGPT Said It's Impossible

ChatGPT probably said you can't:
1. **Scrape Twitter without API keys** → We use internal GraphQL with browser automation
2. **Bypass Cloudflare with Python** → We use rnet (Rust) with TLS emulation
3. **Have a global CLI that works in any venv** → Server/client architecture
4. **Auto-refresh cookies** → Playwright browser automation
5. **Post tweets programmatically** → Same endpoints as the web app

**They were wrong because they were thinking "one Python script" not "distributed architecture with browser automation."**

---

## 🐛 Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `Cannot connect to server` | Service not running | `sudo systemctl start twitter-scrape` |
| `Authentication failed` | Wrong credentials | Check `.twitter_config.json` |
| `403 Forbidden` | Cookies expired | Auto-refresh should handle it, or run `x refresh` |
| `Verification required` | Suspicious login | Add `email` to config for 2FA handling |
| `Browser not found` | Playwright not installed | Server will auto-install on first refresh |

---

## 🌍 Environment Variables

Override defaults:

```bash
export TWITTER_SCRAPE_HOST=127.0.0.1    # Server host
export TWITTER_SCRAPE_PORT=8765         # Server port
export TWITTER_COOKIES_PATH=/path/to/cookies.json
```

---

## License

Internal tool for authorized Twitter/X API usage only.
