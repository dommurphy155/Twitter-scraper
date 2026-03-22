# Twitter/X Scraper CLI (`x`)

A systemd-powered Twitter/X scraper that runs as a background service with a simple `x` command available everywhere on your system.

## Architecture

```
┌─────────────┐      HTTP API      ┌─────────────────────────────┐
│   `x` CLI   │  ─────────────────→ │  twitter-scrape.service   │
│  (anywhere) │    (port 8765)      │  Python 3.12 + rnet       │
└─────────────┘                     │  systemd-managed          │
                                    └─────────────────────────────┘
```

- **Server**: Runs in isolated Python 3.12 venv with `rnet` for Cloudflare bypass
- **Client**: Pure Python stdlib, works from any directory/venv without activation

---

## Installation

The service is already installed. To reinstall or update:

```bash
sudo bash ~/.openclaw/skills/twitter_scrape/install-service.sh
```

---

## Commands

### Check Status
```bash
x status
```

### Scrape a User
```bash
x user elonmusk                    # Default: 200 tweets
x user jack --limit 50             # Custom limit
```

Output saved to: `~/.openclaw/skills/twitter_scrape/storage/twitter/{username}.json`

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
- `since:2026-01-01 until:2026-03-01` — date range
- `-filter:replies` — exclude replies
- `from:username` — tweets from user

Output saved to: `~/.openclaw/skills/twitter_scrape/storage/twitter/search_{query}.json`

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

### Get Help
```bash
x help
x user --help
x search --help
```

---

## File Locations

| File | Purpose |
|------|---------|
| `~/.openclaw/skills/twitter_scrape/` | Skill directory |
| `~/.openclaw/skills/twitter_scrape/venv/` | Python 3.12 venv with rnet |
| `~/.openclaw/skills/twitter_scrape/server.py` | API server |
| `~/.openclaw/skills/twitter_scrape/x` | CLI client |
| `~/.openclaw/skills/twitter_scrape/twitter_cookies.json` | Auth cookies |
| `~/.openclaw/skills/twitter_scrape/storage/twitter/` | Output directory |
| `~/.local/bin/x` | Symlink to CLI (in your PATH) |

---

## Service Management

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

## Cookie Refresh

Cookies expire ~2 weeks. When you get 403 errors:

1. Open Chrome → Go to `x.com` → Log in
2. DevTools (F12) → Application → Cookies → `https://x.com`
3. Copy `auth_token` and `ct0` values
4. Edit `~/.openclaw/skills/twitter_scrape/twitter_cookies.json`:

```json
[
  {"name": "auth_token", "value": "your_auth_token_here"},
  {"name": "ct0", "value": "your_ct0_here"}
]
```

5. Restart: `sudo systemctl restart twitter-scrape`

---

## Output Format

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

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `Cannot connect to server` | Service not running | `sudo systemctl start twitter-scrape` |
| `403 Forbidden` | Cookies expired | Refresh cookies (see above) |
| `404 Not Found` | User doesn't exist | Check username |
| `Rate limited` | Too many requests | Wait 15 minutes |

---

## Why This Architecture?

- **Python 3.10** system default stays untouched
- **Python 3.12** venv isolated for rnet (requires 3.11+)
- **systemd** keeps server running, auto-restarts on crash
- **`x` client** uses stdlib only - works in any venv/directory
- **HTTP API** lets you extend with other languages/tools

---

## Environment Variables

Override defaults by setting these before running `x`:

```bash
export TWITTER_SCRAPE_HOST=127.0.0.1    # Server host
export TWITTER_SCRAPE_PORT=8765         # Server port
export TWITTER_COOKIES_PATH=/path/to/cookies.json
```

---

## License

Internal tool for authorized Twitter/X API usage only.
