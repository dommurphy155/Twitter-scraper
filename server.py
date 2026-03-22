#!/usr/bin/env python3
"""
Twitter Scraper API Server with AUTO COOKIE REFRESH.

This server automatically detects expired cookies (403 errors) and
uses Playwright browser automation to log in and extract fresh cookies.

Endpoints:
    POST /user        - Scrape user profile + tweets
    POST /search      - Search tweets
    POST /tweet       - Post a tweet
    POST /like        - Like a tweet
    POST /delete      - Delete a tweet
    GET  /health      - Health check
    POST /refresh     - Manually trigger cookie refresh

Auto-refresh: Enabled - server will automatically re-login on auth failures.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from rnet_twitter import RnetTwitterClient, TwitterAPIError
from cookie_refresh import refresh_cookies, CookieRefreshError, COOKIES_PATH

# Config
HOST = os.environ.get("TWITTER_SCRAPE_HOST", "127.0.0.1")
PORT = int(os.environ.get("TWITTER_SCRAPE_PORT", "8765"))
STORAGE_DIR = Path("storage/twitter")

# Ensure storage dir exists
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Global to track if we're currently refreshing
cookies_being_refreshed = False


def response(status_code, data):
    """Build JSON response."""
    return status_code, {"Content-Type": "application/json"}, json.dumps(data).encode()


async def ensure_valid_cookies():
    """
    Check if cookies are valid, refresh if needed.

    Returns True if valid cookies exist, False otherwise.
    """
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
        await refresh_cookies(headless=True)
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
        # Parse body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else "{}"

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send(*response(400, {"error": "Invalid JSON"}))
            return

        # Route to handler
        handlers = {
            "/user": self._handle_user,
            "/search": self._handle_search,
            "/tweet": self._handle_tweet,
            "/like": self._handle_like,
            "/delete": self._handle_delete,
            "/refresh": self._handle_refresh,
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

    def _handle_with_retry(self, handler_func, data):
        """
        Execute handler with automatic cookie refresh on auth failure.
        """
        # First, ensure cookies are valid
        if not asyncio.run(ensure_valid_cookies()):
            self._send(*response(401, {
                "error": "Authentication failed. Check .twitter_config.json"
            }))
            return

        # Try the operation
        try:
            result = asyncio.run(handler_func(data))
            self._send(*response(200, result))
        except TwitterAPIError as e:
            if e.status in [401, 403]:
                # Auth error - try to refresh and retry once
                print(f"[Server] Auth error {e.status}, attempting refresh and retry...")
                if asyncio.run(ensure_valid_cookies()):
                    try:
                        result = asyncio.run(handler_func(data))
                        self._send(*response(200, result))
                        return
                    except TwitterAPIError as e2:
                        self._send(*response(e2.status, {"error": str(e2)}))
                        return
                else:
                    self._send(*response(401, {"error": "Auth failed and refresh failed"}))
            else:
                self._send(*response(e.status, {"error": str(e)}))
        except Exception as e:
            self._send(*response(500, {"error": str(e)}))

    def _handle_user(self, data):
        """Scrape user profile and tweets."""
        self._handle_with_retry(self._do_user, data)

    async def _do_user(self, data):
        """Actually scrape user (called with retry logic)."""
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

    def _handle_refresh(self, data):
        """Manually trigger cookie refresh."""
        try:
            success = asyncio.run(ensure_valid_cookies())
            if success:
                self._send(*response(200, {"success": True, "message": "Cookies refreshed"}))
            else:
                self._send(*response(500, {"error": "Refresh failed"}))
        except Exception as e:
            self._send(*response(500, {"error": str(e)}))


def run_server():
    """Run the HTTP server."""
    server = HTTPServer((HOST, PORT), TwitterHandler)
    print(f"╔═══════════════════════════════════════════════════════════╗")
    print(f"║     Twitter Scraper Server - AUTO COOKIE REFRESH        ║")
    print(f"╠═══════════════════════════════════════════════════════════╣")
    print(f"║  Endpoint: http://{HOST}:{PORT}                      ║")
    print(f"║  Storage:  {STORAGE_DIR}        ║")
    print(f"║  Cookies:  {COOKIES_PATH}                ║")
    print(f"║                                                           ║")
    print(f"║  Features:                                                ║")
    print(f"║  • Automatic cookie refresh on 403/401 errors             ║")
    print(f"║  • Playwright browser automation for re-login            ║")
    print(f"║  • Headless Chrome - no GUI required                     ║")
    print(f"║                                                           ║")
    print(f"║  Setup:                                                   ║")
    print(f"║  1. cp .twitter_config.example.json .twitter_config.json ║")
    print(f"║  2. Edit with your Twitter credentials                   ║")
    print(f"║                                                           ║")
    print(f"╚═══════════════════════════════════════════════════════════╝")
    print()

    # Check if config exists
    config_path = Path(__file__).parent / ".twitter_config.json"
    if not config_path.exists():
        print("⚠️  WARNING: .twitter_config.json not found!")
        print("   Auto-refresh will fail until you create it.")
        print("   Copy .twitter_config.example.json and fill in your credentials.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    run_server()
