#!/usr/bin/env python3
"""Twitter Scraper API Server with MULTI-ACCOUNT GROK SUPPORT.

This server supports automatic account rotation when Grok rate limits are hit.

Endpoints:
    POST /user        - Scrape user profile + tweets
    POST /search      - Search tweets
    POST /tweet       - Post a tweet
    POST /like        - Like a tweet
    POST /delete      - Delete a tweet
    GET  /health      - Health check
    POST /refresh     - Manually trigger cookie refresh
    POST /grok/chat   - Send message to Grok (with auto account rotation)
    POST /grok/conversation - Get conversation ID
    GET  /account/status - Get current account status
    POST /account/switch - Switch to specific account
"""

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from rnet_twitter import RnetTwitterClient, TwitterAPIError
from cookie_refresh import refresh_cookies, pull_cookies_from_chrome, CookieRefreshError, COOKIES_PATH
from account_manager import get_account_manager, AccountManager

# Config
HOST = os.environ.get("TWITTER_SCRAPE_HOST", "127.0.0.1")
PORT = int(os.environ.get("TWITTER_SCRAPE_PORT", "8765"))
STORAGE_DIR = Path("storage/twitter")
GROK_CHATS_DIR = Path("storage/grok_chats")

# Ensure storage dirs exist
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
GROK_CHATS_DIR.mkdir(parents=True, exist_ok=True)

# Global to track if we're currently refreshing
cookies_being_refreshed = False

# Rate limit detection patterns
GROK_RATE_LIMIT_EXACT = "You've reached your limit of 20 Grok Auto questions per 2 hours. Please sign up for Premium+ to access more, or check back later."
GROK_RATE_LIMIT_PATTERNS = [
    "reached your limit",
    "More Grok with",
    "Upgrade to X",
]


def response(status_code, data):
    """Build JSON response."""
    return status_code, {"Content-Type": "application/json"}, json.dumps(data).encode()


def is_grok_rate_limited(response_text: str) -> bool:
    """Check if Grok response contains rate limit message.

    Checks exact string first, then falls back to substring patterns.
    Returns True if rate limited, False otherwise.
    """
    if not response_text:
        return False

    # Check exact match first
    if GROK_RATE_LIMIT_EXACT in response_text:
        return True

    # Check substring patterns (3+ word phrases)
    text_lower = response_text.lower()
    for pattern in GROK_RATE_LIMIT_PATTERNS:
        if pattern.lower() in text_lower:
            return True

    return False


def save_grok_context(conversation_id: str, exchanges: list, original_message: str) -> Path:
    """Save last 3 exchanges to JSON file for context carry-over."""
    context_data = {
        "conversation_id": conversation_id,
        "original_message": original_message,
        "exchanges": exchanges[-3:],  # Keep only last 3
        "created_at": datetime.now().isoformat()
    }

    context_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    context_file = GROK_CHATS_DIR / f"context_{context_id}.json"

    with open(context_file, "w") as f:
        json.dump(context_data, f, indent=2)

    return context_file


def load_grok_context(context_file: Path) -> dict:
    """Load context from JSON file."""
    with open(context_file) as f:
        return json.load(f)


def delete_grok_context(context_file: Path):
    """Delete context file after successful handoff."""
    try:
        context_file.unlink()
    except FileNotFoundError:
        pass


def build_context_prompt(context_data: dict) -> str:
    """Build the context injection prompt from saved exchanges."""
    exchanges = context_data.get("exchanges", [])
    original_message = context_data.get("original_message", "")

    lines = [
        "Hi so we was just having a conversation and we got cut off mid way —",
        "these are the last few messages we had, just acknowledge them and",
        "answer my new message:",
        ""
    ]

    for i, exchange in enumerate(exchanges, 1):
        lines.append(f"{i}{'st' if i == 1 else 'nd' if i == 2 else 'rd' if i == 3 else 'th'} exchange:")
        lines.append(f"Me: {exchange.get('user', '')}")
        lines.append(f"Grok: {exchange.get('grok', '')}")
        lines.append("")

    lines.append("New message:")
    lines.append(f"Me: {original_message}")

    return "\n".join(lines)


async def ensure_valid_cookies():
    """Check if cookies are valid, refresh if needed."""
    global cookies_being_refreshed

    # Test current cookies
    if COOKIES_PATH.exists():
        client = RnetTwitterClient()
        try:
            client.load_cookies(str(COOKIES_PATH))
            # Try a simple API call
            await client.get_user_by_screen_name("twitter")
            print("[Server] Cookies are valid")
            return True
        except TwitterAPIError as e:
            if e.status in [401, 403]:
                print(f"[Server] Cookies expired (HTTP {e.status}), auto-refreshing...")
            else:
                # Some other error, assume cookies might still be valid
                print(f"[Server] Cookie test error (non-auth): {e}")
                return True
        except Exception as e:
            print(f"[Server] Cookie test error: {e}")

    # Need to refresh
    if cookies_being_refreshed:
        print("[Server] Cookie refresh already in progress, waiting...")
        # Wait up to 60 seconds for refresh to complete
        for _ in range(60):
            await asyncio.sleep(1)
            if not cookies_being_refreshed:
                break
        return COOKIES_PATH.exists()

    cookies_being_refreshed = True
    try:
        print("[Server] Starting automatic cookie refresh...")

        # First try to pull from Chrome CDP
        chrome_cookies = await pull_cookies_from_chrome()
        if chrome_cookies:
            print("[Server] Cookies refreshed from Chrome CDP!")
            return True

        # Fall back to full browser login
        print("[Server] Chrome pull failed, falling back to full browser login...")
        await refresh_cookies(headless=True, prefer_chrome=False)
        print("[Server] Cookie refresh successful!")
        return True
    except CookieRefreshError as e:
        print(f"[Server] Cookie refresh failed: {e}")
        return False
    finally:
        cookies_being_refreshed = False


class TwitterHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Twitter API."""

    def log_message(self, format, *args):
        """Custom logging."""
        print(f"[{datetime.now().isoformat()}] {args[0]}")

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health":
            cookies_exist = COOKIES_PATH.exists()
            cookies_valid = False
            if cookies_exist:
                try:
                    cookies_valid = asyncio.run(self._test_cookies_quick())
                except:
                    pass
            self._send(*response(200, {
                "status": "ok",
                "cookies_exist": cookies_exist,
                "cookies_valid": cookies_valid,
                "endpoint": f"{HOST}:{PORT}"
            }))
        elif self.path == "/account/status":
            self._handle_account_status()
        else:
            self._send(*response(404, {"error": "Not found"}))

    async def _test_cookies_quick(self):
        """Quick test if cookies work."""
        client = RnetTwitterClient()
        client.load_cookies(str(COOKIES_PATH))
        await client.get_user_by_screen_name("twitter")
        return True

    def do_POST(self):
        """Handle POST requests."""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else "{}"

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send(*response(400, {"error": "Invalid JSON"}))
            return

        handlers = {
            "/user": self._handle_user,
            "/search": self._handle_search,
            "/tweet": self._handle_tweet,
            "/like": self._handle_like,
            "/delete": self._handle_delete,
            "/refresh": self._handle_refresh,
            "/grok/conversation": self._handle_grok_conversation,
            "/grok/chat": self._handle_grok_chat,
            "/account/switch": self._handle_account_switch,
        }

        handler = handlers.get(self.path)
        if handler:
            handler(data)
        else:
            self._send(*response(404, {"error": "Unknown endpoint"}))

    def _send(self, status, headers, body):
        """Send HTTP response."""
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _handle_with_retry(self, handler_func, data, operation_name="Operation"):
        """Execute handler with automatic cookie refresh on auth failure."""
        if not asyncio.run(ensure_valid_cookies()):
            self._send(*response(401, {
                "error": "Authentication failed. Check .twitter_config.json"
            }))
            return

        try:
            result = asyncio.run(handler_func(data))
            result["_meta"] = {"refreshed": False, "message": f"{operation_name} successful"}
            self._send(*response(200, result))
        except TwitterAPIError as e:
            if e.status in [401, 403]:
                print(f"[Server] Auth error {e.status}, attempting refresh and retry...")
                if asyncio.run(ensure_valid_cookies()):
                    try:
                        result = asyncio.run(handler_func(data))
                        result["_meta"] = {"refreshed": True, "message": f"Cookies expired, refreshed, then {operation_name.lower()} successful"}
                        self._send(*response(200, result))
                        return
                    except TwitterAPIError as e2:
                        self._send(*response(e2.status, {"error": str(e2)}))
                        return
                else:
                    self._send(*response(401, {"error": "Auth failed and refresh failed"}))
            else:
                self._send(*response(int(e.status), {"error": str(e)}))
        except Exception as e:
            self._send(*response(500, {"error": str(e)}))

    def _handle_user(self, data):
        """Scrape user profile and tweets."""
        self._handle_with_retry(self._do_user, data)

    async def _do_user(self, data):
        """Actually scrape user."""
        username = data.get("username")
        limit = data.get("limit", 200)

        if not username:
            raise ValueError("username required")

        client = RnetTwitterClient()
        client.load_cookies(str(COOKIES_PATH))

        user = await client.get_user_by_screen_name(username)
        tweets = await client.get_user_tweets(user["rest_id"], count=limit)

        output = {
            "scraped_at": datetime.now().isoformat(),
            "profile": {
                "id": user["rest_id"],
                "username": user.get("screen_name", ""),
                "name": user.get("name", ""),
                "bio": user.get("description", ""),
                "location": user.get("location", ""),
                "url": user.get("url", ""),
                "followers_count": user.get("followers_count", 0),
                "following_count": user.get("friends_count", 0),
                "tweets_count": user.get("statuses_count", 0),
                "verified": user.get("verified", False),
                "created_at": user.get("created_at", ""),
            },
            "tweets": tweets,
            "tweets_count": len(tweets),
        }

        output_path = STORAGE_DIR / f"{username}.json"
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2, default=str)

        return {"success": True, "path": str(output_path), "tweets_count": len(tweets)}

    def _handle_search(self, data):
        """Search tweets."""
        self._handle_with_retry(self._do_search, data)

    async def _do_search(self, data):
        """Actually search tweets."""
        query = data.get("query")
        limit = data.get("limit", 100)
        product = data.get("product", "Latest")

        if not query:
            raise ValueError("query required")

        client = RnetTwitterClient()
        client.load_cookies(str(COOKIES_PATH))

        tweets = await client.search_tweets(query=query, count=limit, product=product)

        output = {
            "scraped_at": datetime.now().isoformat(),
            "query": query,
            "product": product,
            "tweets": tweets,
            "tweets_count": len(tweets),
        }

        safe_query = query.replace(" ", "_").replace(":", "")[:50]
        output_path = STORAGE_DIR / f"search_{safe_query}.json"
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2, default=str)

        return {"success": True, "path": str(output_path), "tweets_count": len(tweets), "tweets": tweets}

    def _handle_tweet(self, data):
        """Post a tweet."""
        self._handle_with_retry(self._do_tweet, data)

    async def _do_tweet(self, data):
        """Actually post tweet."""
        text = data.get("text")
        reply_to = data.get("reply_to")

        if not text:
            raise ValueError("text required")

        client = RnetTwitterClient()
        client.load_cookies(str(COOKIES_PATH))

        result = await client.create_tweet(text, reply_to=reply_to)
        tweet_id = client.extract_tweet_id(result)

        return {"success": True, "tweet_id": tweet_id, "url": f"https://x.com/i/web/status/{tweet_id}"}

    def _handle_like(self, data):
        """Like a tweet."""
        self._handle_with_retry(self._do_like, data)

    async def _do_like(self, data):
        """Actually like tweet."""
        tweet_id = data.get("tweet_id")
        if not tweet_id:
            raise ValueError("tweet_id required")

        client = RnetTwitterClient()
        client.load_cookies(str(COOKIES_PATH))
        await client.favorite_tweet(tweet_id)
        return {"success": True}

    def _handle_delete(self, data):
        """Delete a tweet."""
        self._handle_with_retry(self._do_delete, data)

    async def _do_delete(self, data):
        """Actually delete tweet."""
        tweet_id = data.get("tweet_id")
        if not tweet_id:
            raise ValueError("tweet_id required")

        client = RnetTwitterClient()
        client.load_cookies(str(COOKIES_PATH))
        await client.delete_tweet(tweet_id)
        return {"success": True}

    def _handle_grok_conversation(self, data):
        """Create a new Grok conversation."""
        try:
            result = asyncio.run(self._do_grok_conversation(data))
            self._send(*response(200, result))
        except Exception as e:
            self._send(*response(500, {"error": str(e)}))

    async def _do_grok_conversation(self, data):
        """Get conversation ID from the live Grok tab."""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0]

            page = None
            for pg in context.pages:
                if "x.com/i/grok" in pg.url:
                    page = pg
                    break

            if not page:
                page = await context.new_page()
                await page.goto("https://x.com/i/grok")
                await page.wait_for_load_state("domcontentloaded")

            url = page.url
            conversation_id = None
            if "conversation=" in url:
                conversation_id = url.split("conversation=")[-1].split("&")[0]

            return {"conversation_id": conversation_id, "url": url}

    def _handle_grok_chat(self, data):
        """Send message to Grok with automatic account rotation on rate limit."""
        attempted_accounts = set()
        context_file = None

        while True:
            try:
                result = asyncio.run(self._do_grok_chat_with_account(data, attempted_accounts, context_file))
                self._send(*response(200, result))
                return
            except Exception as e:
                error_str = str(e)
                if "rate_limited" in error_str:
                    account_username = error_str.split(":")[-1] if ":" in error_str else None
                    if account_username:
                        attempted_accounts.add(account_username)
                        print(f"[Grok] Account {account_username} rate limited, trying next...")
                        continue
                self._send(*response(500, {"error": error_str}))
                return

    async def _do_grok_chat_with_account(self, data, attempted_accounts: set, context_file: Path = None):
        """Send message to Grok via specific account with rate limit handling."""
        from playwright.async_api import async_playwright

        manager = get_account_manager()
        account = manager.get_next_available_account(exclude=list(attempted_accounts))
        if not account:
            earliest_reset = manager.get_earliest_reset_time()
            if earliest_reset:
                wait_minutes = int((earliest_reset - datetime.now()).total_seconds() / 60)
                raise Exception(f"All accounts rate limited. Earliest reset: {wait_minutes} minutes")
            raise Exception("All accounts rate limited")

        print(f"[Grok] Using account: {account.username}")

        message = data.get("message")
        conversation_id = data.get("conversation_id")

        if not message:
            raise ValueError("message required")

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0]

            page = None
            for pg in context.pages:
                if "x.com/i/grok" in pg.url:
                    page = pg
                    break

            if not page:
                page = await context.new_page()
                await page.goto("https://x.com/i/grok")
                await page.wait_for_load_state("domcontentloaded")

            if conversation_id:
                if conversation_id not in page.url:
                    await page.goto(f"https://x.com/i/grok?conversation={conversation_id}")
                    await page.wait_for_load_state("domcontentloaded")
            else:
                current_url = page.url
                has_conversation_param = "conversation=" in current_url

                if has_conversation_param:
                    try:
                        new_chat_btn = await page.wait_for_selector('button[aria-label="New Chat"]', timeout=5000)
                        if new_chat_btn:
                            await new_chat_btn.click()
                            await page.wait_for_load_state("domcontentloaded")
                            await asyncio.sleep(1)
                    except:
                        await page.goto("https://x.com/i/grok")
                        await page.wait_for_load_state("domcontentloaded")

            url = page.url
            if "conversation=" in url:
                conversation_id = url.split("conversation=")[-1].split("&")[0]

            before = await page.evaluate("""() => {
                const col = document.querySelector('[data-testid="primaryColumn"]');
                return col ? col.innerText.trim() : "";
            }""")

            exchanges = []

            if context_file and context_file.exists():
                context_data = load_grok_context(context_file)
                exchanges = context_data.get("exchanges", [])
                message = build_context_prompt(context_data)

            textarea = await page.wait_for_selector(
                'textarea[placeholder="Ask anything"]',
                timeout=15000
            )
            await textarea.click()
            await textarea.fill(message)
            await page.keyboard.press("Enter")

            response_text = None
            prev_text = before
            stable_count = 0
            final_conversation_id = conversation_id

            for attempt in range(180):
                await page.wait_for_timeout(1000)

                data = await page.evaluate("""() => {
                    const col = document.querySelector('[data-testid="primaryColumn"]');
                    const btns = [...document.querySelectorAll('button')];
                    const hasCancel = btns.some(b => b.getAttribute('aria-label') === 'Cancel');
                    const hasSend = btns.some(b => b.getAttribute('aria-label') === 'Enter voice mode');
                    return {
                        text: col ? col.innerText.trim() : "",
                        generating: hasCancel,
                        done: hasSend && !hasCancel,
                    };
                }""")

                current = data["text"]
                generating = data["generating"]
                done_signal = data["done"]

                if current != prev_text:
                    stable_count = 0
                    prev_text = current
                elif done_signal and current != before:
                    stable_count += 1
                    if stable_count >= 2:
                        parts = current.split(message)
                        if len(parts) > 1:
                            after = parts[-1].strip()
                            lines = [l for l in after.split("\n") if l.strip()]
                            ui_noise = {"See new posts", "Ask about", "Copy", "Retry", "Like", "Dislike", "Think Harder", "Auto", "Search", "DeepSearch", "Quick Answer", "Detail", "Explore"}
                            clean = []
                            for line in lines:
                                if any(line.startswith(n) for n in ui_noise):
                                    break
                                clean.append(line)
                            response_text = "\n".join(clean).strip()
                        else:
                            response_text = current[len(before):].strip()
                        break

            if is_grok_rate_limited(response_text):
                print(f"[Grok] Rate limit detected on account {account.username}")
                manager.mark_account_rate_limited(account.username, cooldown_hours=2)
                exchanges.append({
                    "user": data.get("message", ""),
                    "grok": "[Rate limited - switching account]"
                })
                new_context_file = save_grok_context(
                    conversation_id or "unknown",
                    exchanges,
                    data.get("message", "")
                )
                if context_file:
                    delete_grok_context(context_file)
                raise Exception(f"rate_limited:{account.username}")

            if context_file:
                delete_grok_context(context_file)

            final_url = page.url
            if "conversation=" in final_url:
                final_conversation_id = final_url.split("conversation=")[-1].split("&")[0]
            elif final_conversation_id is None:
                final_conversation_id = f"unknown_{datetime.now().strftime('%Y%m%d%H%M%S')}"

            manager.set_current_account(account.username)

            grok_storage_dir = STORAGE_DIR.parent / "grok"
            grok_storage_dir.mkdir(parents=True, exist_ok=True)

            response_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            response_file = (grok_storage_dir / f"response_{response_id}.txt").resolve()
            response_file.write_text(response_text or "No response captured - try again", encoding='utf-8')

            return {
                "conversation_id": final_conversation_id,
                "response": response_text or "No response captured - try again",
                "response_file": str(response_file.resolve()),
                "response_id": response_id,
                "account": account.username,
            }

    def _handle_account_status(self):
        """Get current account status."""
        manager = get_account_manager()
        current = manager.get_current_account()

        if not current:
            try:
                current = asyncio.run(self._detect_current_account_from_browser())
            except Exception as e:
                print(f"[Account] Could not detect current account: {e}")

        accounts_status = []
        for username, account in manager.accounts.items():
            status = "rate_limited" if account.is_rate_limited() else "active"
            time_left = None
            if account.is_rate_limited():
                time_left = account.time_until_available()
                minutes = int(time_left.total_seconds() / 60) if time_left else 0
                time_str = f"{minutes}m"
            else:
                time_str = None

            accounts_status.append({
                "username": username,
                "status": status,
                "is_current": username == (current.username if current else None),
                "time_until_available": time_str
            })

        self._send(*response(200, {
            "current_account": current.username if current else None,
            "accounts": accounts_status
        }))

    async def _detect_current_account_from_browser(self):
        """Detect current account by scraping X sidebar."""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0]

            page = None
            for pg in context.pages:
                if "x.com" in pg.url:
                    page = pg
                    break

            if not page:
                return None

            try:
                button = await page.query_selector('[data-testid="SideNav_AccountSwitcher_Button"]')
                if button:
                    aria_label = await button.get_attribute("aria-label")
                    if aria_label and "@" in aria_label:
                        import re
                        match = re.search(r'@(\w+)', aria_label)
                        if match:
                            username = f"@{match.group(1)}"
                            manager = get_account_manager()
                            if username in manager.accounts:
                                manager.set_current_account(username)
                                return manager.accounts[username]
            except Exception as e:
                print(f"[Account] Error detecting account: {e}")
            finally:
                try:
                    await page.reload()
                except:
                    pass

        return None

    def _handle_account_switch(self, data):
        """Switch to specific account via UI automation."""
        username = data.get("username")
        if not username:
            self._send(*response(400, {"error": "username required"}))
            return

        try:
            result = asyncio.run(self._do_account_switch(username))
            self._send(*response(200, result))
        except Exception as e:
            self._send(*response(500, {"error": str(e)}))

    async def _do_account_switch(self, target_username: str):
        """Switch to target account via X UI automation."""
        from playwright.async_api import async_playwright

        manager = get_account_manager()

        if target_username not in manager.accounts:
            raise Exception(f"Unknown account: {target_username}")

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            ctx = browser.contexts[0]

            page = None
            for pg in ctx.pages:
                if "x.com" in pg.url:
                    page = pg
                    break

            if not page:
                page = await ctx.new_page()
                await page.goto("https://x.com")
                await page.wait_for_load_state("domcontentloaded")

            print(f"[Account] Clicking account switcher...")
            try:
                switcher = await page.wait_for_selector(
                    '[data-testid="SideNav_AccountSwitcher_Button"]',
                    timeout=5000
                )
                await switcher.click()
                await asyncio.sleep(0.5)
            except Exception as e:
                raise Exception(f"Could not find account switcher: {e}")

            print(f"[Account] Selecting {target_username}...")
            try:
                account_span = await page.wait_for_selector(
                    f'span:text-is("{target_username}")',
                    timeout=5000
                )
                await account_span.click()
            except Exception as e:
                raise Exception(f"Could not find account {target_username}: {e}")

            print(f"[Account] Waiting for switch...")
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)

            print(f"[Account] Refreshing session...")
            manager.set_current_account(target_username)

            print(f"[Account] Opening Grok...")
            await page.goto("https://x.com/i/grok")
            await page.wait_for_load_state("domcontentloaded")

            return {
                "success": True,
                "account": target_username,
                "message": f"Switched to {target_username}"
            }

    def _handle_refresh(self, data):
        """Manually trigger cookie refresh."""
        from cookie_refresh import pull_cookies_from_chrome, refresh_cookies_from_browser

        messages = []

        def log(msg):
            messages.append(msg)
            print(f"[Refresh] {msg}")

        try:
            log("Checking for open x.com tab...")
            chrome_cookies = asyncio.run(pull_cookies_from_chrome())

            if chrome_cookies:
                log("Open tab found - pulling cookies now...")
                log("Done!")
                self._send(*response(200, {
                    "success": True,
                    "message": "Cookies refreshed",
                    "source": "chrome",
                    "details": messages
                }))
                return

            log("No tab found - navigating to x.com...")
            cookies = asyncio.run(refresh_cookies_from_browser(headless=True))
            log("Navigated")
            log("Refresh done")

            self._send(*response(200, {
                "success": True,
                "message": "Cookies refreshed",
                "source": "browser_login",
                "details": messages
            }))

        except Exception as e:
            log(f"Failed: {e}")
            self._send(*response(500, {
                "error": str(e),
                "details": messages
            }))


def run_server():
    """Run the HTTP server."""
    server = HTTPServer((HOST, PORT), TwitterHandler)
    print(f"Twitter Scraper Server - MULTI-ACCOUNT GROK")
    print(f"Endpoint: http://{HOST}:{PORT}")
    print(f"Storage: {STORAGE_DIR}")
    print(f"Cookies: {COOKIES_PATH}")
    print()

    # Load and show accounts
    manager = get_account_manager()
    accounts = manager.get_all_accounts()
    if accounts:
        print(f"Loaded {len(accounts)} account(s):")
        for acc in accounts:
            status = "rate limited" if acc.is_rate_limited() else "active"
            print(f"   - {acc.username} [{status}]")
        print()
    else:
        print("No accounts configured in .env")
        print("Add ACCOUNT_N_USERNAME entries to enable multi-account\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    run_server()
