#!/usr/bin/env python3
"""Twitter Scraper API Server v3 — lean, working endpoints only.

Endpoints:
  GET  /health              — liveness + cookie status
  GET  /session             — re-grab live cookies from Chrome
  GET  /account/status      — per-account cooldown status
  POST /user                — {username, limit} → scrape profile + tweets
  POST /search              — {query, limit, product} → search tweets
  POST /tweet               — {text, reply_to?, media_ids?} → post tweet
  POST /media               — {file_path, media_type} → upload media
  POST /like                — {tweet_id} → like tweet
  POST /delete              — {tweet_id} → delete tweet
  POST /pain                — {keyword, limit?, min_score?} → pain mining
  POST /refresh             — force cookie re-grab
  POST /login               — open login UI
  POST /account/switch      — {username} → switch active account
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from rnet_twitter import RnetTwitterClient, TwitterAPIError
from cookie_refresh import (
    CookieRefreshError, COOKIES_PATH, CONFIG_PATH,
    debug_port, find_chromium, find_free_port, port_listening,
    grab_cookies_via_cdp, ensure_logged_in, refresh_cookies,
    spawn_chrome, wait_for_chrome, save_cookies, set_debug_port,
    load_cached_cookies,
)
from account_manager import get_account_manager
from pain_miner import PainMiner

HOST = os.environ.get("TWITTER_SCRAPE_HOST", "127.0.0.1")
PORT = int(os.environ.get("TWITTER_SCRAPE_PORT", "8765"))
DISPLAY = os.environ.get("DISPLAY", ":1")
STORAGE_DIR = SCRIPT_DIR.parent / "storage" / "twitter"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
AUTO_LAUNCH_CHROME = os.environ.get("TWITTER_SCRAPE_NO_AUTO_CHROME", "0") != "1"

_cookie_cache: list = []
_cookie_cache_mtime: float = 0.0


def response(status_code: int, data: dict):
    return status_code, {"Content-Type": "application/json"}, json.dumps(data).encode()


async def get_live_cookies() -> list:
    global _cookie_cache, _cookie_cache_mtime
    now = time.time()
    if _cookie_cache and (now - _cookie_cache_mtime) < 1.0:
        return _cookie_cache
    port = debug_port()
    cookies = await grab_cookies_via_cdp(port)
    if not cookies:
        cookies = load_cached_cookies()
    if cookies:
        _cookie_cache = cookies
        _cookie_cache_mtime = now
    return cookies


async def ensure_session() -> list:
    cookies = await get_live_cookies()
    if cookies and len(cookies) >= 2:
        return cookies
    try:
        cookies = await refresh_cookies(headless=False, display=DISPLAY)
        _cookie_cache = cookies
        _cookie_cache_mtime = time.time()
        return cookies
    except CookieRefreshError:
        pass
    new_port = find_free_port()
    proc = spawn_chrome(port=new_port, headless=False, display=DISPLAY)
    if not proc:
        raise CookieRefreshError("Could not find or launch Chromium. Install google-chrome/chromium and retry.")
    set_debug_port(new_port)
    cookies = await refresh_cookies(headless=False, display=DISPLAY)
    _cookie_cache = cookies
    _cookie_cache_mtime = time.time()
    return cookies


class TwitterHandler(BaseHTTPRequestHandler):
    server_version = "TwitterScraper/3.0"

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().isoformat()}] {args[0]}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._handle_health()
        elif path == "/account/status":
            self._handle_account_status()
        elif path == "/session":
            self._handle_session()
        else:
            self._send(*response(404, {"error": "Not found"}))

    def _handle_health(self):
        port = debug_port()
        listening = port_listening("127.0.0.1", port)
        cookies = load_cached_cookies()
        names = {c.get("name") for c in cookies}
        self._send(*response(200, {
            "status": "ok",
            "chrome_debug_port": port,
            "chrome_running": listening,
            "cookies_cached": len(cookies),
            "has_auth_token": "auth_token" in names,
            "has_ct0": "ct0" in names,
            "endpoint": f"{HOST}:{PORT}",
            "version": "3.0",
        }))

    def _handle_session(self):
        try:
            cookies = run_async(get_live_cookies())
            self._send(*response(200, {"cookies_count": len(cookies), "cookies": cookies}))
        except Exception as e:
            self._send(*response(500, {"error": str(e)}))

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length else "{}"
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send(*response(400, {"error": "Invalid JSON"}))
            return

        routes = {
            "/user": self._do_user,
            "/search": self._do_search,
            "/tweet": self._do_tweet,
            "/media": self._do_media,
            "/like": self._do_like,
            "/delete": self._do_delete,
            "/pain": self._do_pain,
            "/refresh": self._do_refresh,
            "/login": self._do_login,
            "/account/switch": self._do_account_switch,
        }
        handler = routes.get(path)
        if not handler:
            self._send(*response(404, {"error": f"Unknown endpoint: {path}"}))
            return

        try:
            self._send(*response(200, run_async(handler(data))))
        except TwitterAPIError as e:
            if e.status in (401, 403):
                self._send(*response(401, {"error": str(e), "action": "Call POST /login to re-authenticate"}))
                return
            self._send(*response(int(e.status), {"error": str(e)}))
        except ValueError as e:
            self._send(*response(400, {"error": str(e)}))
        except CookieRefreshError as e:
            self._send(*response(401, {"error": str(e)}))
        except Exception as e:
            self._send(*response(500, {"error": str(e)}))

    def _send(self, status, headers, body):
        try:
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _with_cookies(self, client):
        cookies = load_cached_cookies()
        if cookies:
            client._cookies = {c["name"]: c["value"] for c in cookies}

    # ── API handlers ─────────────────────────────────────────────────

    async def _do_user(self, data):
        username = data.get("username")
        limit = int(data.get("limit", 200))
        if not username:
            raise ValueError("username required")
        await ensure_session()
        client = RnetTwitterClient()
        self._with_cookies(client)
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
        path = STORAGE_DIR / f"{username}.json"
        path.write_text(json.dumps(output, indent=2, default=str))
        return {"success": True, "path": str(path), "tweets_count": len(tweets), "profile": output["profile"], "tweets": tweets}

    async def _do_search(self, data):
        query = data.get("query")
        limit = int(data.get("limit", 100))
        product = data.get("product", "Latest")
        lang = data.get("lang")
        min_faves = data.get("min_faves")
        min_retweets = data.get("min_retweets")
        since = data.get("since")
        until = data.get("until")
        exclude_replies = bool(data.get("exclude_replies", False))
        exclude_retweets = bool(data.get("exclude_retweets", False))
        verified_only = bool(data.get("verified_only", False))
        media_only = bool(data.get("media_only", False))
        min_followers = data.get("min_followers")
        location = data.get("location")

        if not query:
            raise ValueError("query required")
        await ensure_session()
        client = RnetTwitterClient()
        self._with_cookies(client)
        tweets = await client.search_tweets(
            query=query,
            count=limit,
            product=product,
            lang=lang,
            min_faves=min_faves,
            min_retweets=min_retweets,
            since=since,
            until=until,
            exclude_replies=exclude_replies,
            exclude_retweets=exclude_retweets,
            verified_only=verified_only,
            media_only=media_only,
            min_followers=min_followers,
            location=location,
        )
        output = {"scraped_at": datetime.now().isoformat(), "query": query, "product": product, "tweets": tweets, "tweets_count": len(tweets)}
        safe = query.replace(" ", "_").replace(":", "")[:50]
        path = STORAGE_DIR / f"search_{safe}.json"
        path.write_text(json.dumps(output, indent=2, default=str))
        return {"success": True, "path": str(path), "tweets_count": len(tweets), "tweets": tweets}

    async def _do_tweet(self, data):
        text = data.get("text")
        reply_to = data.get("reply_to")
        media_ids = data.get("media_ids")
        if not text:
            raise ValueError("text required")
        await ensure_session()
        client = RnetTwitterClient()
        self._with_cookies(client)
        result = await client.create_tweet(text, reply_to=reply_to, media_ids=media_ids)
        tweet_id = client.extract_tweet_id(result)
        return {"success": True, "tweet_id": tweet_id, "url": f"https://x.com/i/web/status/{tweet_id}"}

    async def _do_media(self, data):
        file_path = data.get("file_path")
        media_type = data.get("media_type", "image")
        if not file_path:
            raise ValueError("file_path required")
        await ensure_session()
        client = RnetTwitterClient()
        self._with_cookies(client)
        media_id = await client.upload_media(file_path, media_type=media_type)
        return {"success": True, "media_id": media_id}

    async def _do_like(self, data):
        tweet_id = data.get("tweet_id")
        if not tweet_id:
            raise ValueError("tweet_id required")
        await ensure_session()
        client = RnetTwitterClient()
        self._with_cookies(client)
        await client.favorite_tweet(tweet_id)
        return {"success": True}

    async def _do_delete(self, data):
        tweet_id = data.get("tweet_id")
        if not tweet_id:
            raise ValueError("tweet_id required")
        await ensure_session()
        client = RnetTwitterClient()
        self._with_cookies(client)
        await client.delete_tweet(tweet_id)
        return {"success": True}

    async def _do_pain(self, data):
        keyword = data.get("keyword")
        limit = int(data.get("limit", 200))
        min_score = int(data.get("min_score", 5))
        if not keyword:
            raise ValueError("keyword required")

        # Extract search filters for pain mining
        filters = {}
        for key in ("lang", "since", "until", "location"):
            if data.get(key):
                filters[key] = data[key]
        for key in ("min_faves", "min_retweets", "min_followers"):
            v = data.get(key)
            if v is not None:
                filters[key] = int(v)

        await ensure_session()
        client = RnetTwitterClient()
        self._with_cookies(client)
        miner = PainMiner(client)
        results = await miner.mine(
            keyword=keyword,
            limit=limit,
            min_score=min_score,
            search_filters=filters if filters else None,
        )
        return {
            "success": True, "keyword": keyword, "results_count": len(results),
            "results": [{"score": r.score, "wtp_level": r.wtp_level, "signals": r.signals, "tweet": r.tweet} for r in results],
        }

    async def _do_refresh(self, _data):
        global _cookie_cache
        cookies = await grab_cookies_via_cdp()
        if not cookies:
            return {"success": False, "error": "No cookies in live Chrome"}
        _cookie_cache = cookies
        save_cookies(cookies)
        return {"success": True, "cookies_count": len(cookies), "source": "live_cdp"}

    async def _do_login(self, _data):
        cookies, status = await ensure_logged_in(port=debug_port(), headless=False, display=DISPLAY)
        if not cookies:
            return {"success": False, "status": status, "error": "Login was not completed."}
        global _cookie_cache
        _cookie_cache = cookies
        _cookie_cache_mtime = time.time()
        return {"success": True, "status": "ok", "cookies_count": len(cookies)}

    # ── Account ──────────────────────────────────────────────────────

    def _handle_account_status(self):
        manager = get_account_manager()
        accounts_status = []
        current = manager.get_current_account()
        if not current:
            current = manager.get_all_accounts()[0] if manager.accounts else None
        for username, account in manager.accounts.items():
            status = "rate_limited" if account.is_rate_limited() else "active"
            tts = None
            if account.is_rate_limited():
                delta = account.time_until_available()
                tts = f"{int(delta.total_seconds() / 60)}m" if delta else "0m"
            accounts_status.append({"username": username, "status": status, "is_current": current and username == current.username, "time_until_available": tts})
        self._send(*response(200, {"current_account": current.username if current else None, "accounts": accounts_status}))

    async def _do_account_switch(self, data):
        target = data.get("username")
        if not target:
            raise ValueError("username required")
        manager = get_account_manager()
        if target not in manager.accounts:
            raise ValueError(f"Unknown account: {target}")
        manager.set_current_account(target)
        return {"success": True, "account": target, "message": f"Active account set to {target}"}


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.run(coro)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _ensure_chrome_running():
    port = debug_port()
    if port_listening("127.0.0.1", port):
        print(f"[Boot] Chrome debug port {port} already open — will attach")
        return
    if not AUTO_LAUNCH_CHROME:
        print(f"[Boot] Auto-launch disabled; no Chrome on :{port}")
        return
    print(f"[Boot] Spawning Chrome on :{port} (display: {DISPLAY})")
    proc = spawn_chrome(port=port, headless=False, display=DISPLAY)
    if proc and wait_for_chrome(port, timeout=15.0):
        print(f"[Boot] Chrome up on :{port} (profile: {proc.profile})")
    else:
        print(f"[Boot] Could not launch Chrome — login flow will retry per request")


def run_server():
    print("=" * 60)
    print(f"  Twitter Scraper v3 — http://{HOST}:{PORT}")
    print("=" * 60)
    print(f"  Storage:  {STORAGE_DIR}")
    print(f"  CDP port: {debug_port()}")
    print(f"  Display:  {DISPLAY}")
    manager = get_account_manager()
    if manager.accounts:
        print(f"  Accounts: {len(manager.accounts)}")
        for acc in manager.accounts.values():
            tag = "rate-limited" if acc.is_rate_limited() else "active"
            print(f"    - {acc.username} [{tag}]")
    else:
        print(f"  Accounts: none (edit {SCRIPT_DIR}/.env to add)")
    _ensure_chrome_running()
    print(f"\n[Boot] Listening on http://{HOST}:{PORT}")
    server = HTTPServer((HOST, PORT), TwitterHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Boot] Shutting down")
        server.shutdown()


if __name__ == "__main__":
    run_server()
