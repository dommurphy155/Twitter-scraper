#!/usr/bin/env python3
"""twx — Python client for the Twitter Scraper API.

Import this from execute_code or any script that needs Twitter access.
All calls go through the local HTTP server (default http://127.0.0.1:8765).

Usage:
    from twx import Twitter
    t = Twitter()

    # Search & mining
    t.search("I hate my CRM", limit=50)
    t.pain_mine("CRM", min_score=5)

    # Users & profiles
    t.user("elonmusk", limit=20)
    t.find_users("photography blogger", count=20)
    t.followers("user_id_here", count=100)

    # Posting
    t.tweet("Hello world")
    t.tweet_with_media("Check this out", "/path/to/image.jpg")
    t.reply("good point", tweet_id="123")

    # Threads
    t.thread("tweet_id_here", count=50)

    # Health
    t.healthy()
"""

from __future__ import annotations

import json
import os
from typing import Optional

import httpx

DEFAULT_HOST = os.environ.get("TWITTER_SCRAPE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("TWITTER_SCRAPE_PORT", "8765"))


class TwitterError(Exception):
    """Raised when the Twitter API returns an error."""
    pass


class Twitter:
    """Synchronous client for the Twitter Scraper HTTP API."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.base = f"http://{host}:{port}"
        self._client = httpx.Client(timeout=60.0)

    def _post(self, path: str, data: dict) -> dict:
        r = self._client.post(f"{self.base}{path}", json=data)
        if r.status_code == 401:
            raise TwitterError(
                f"Auth required — POST /login or run 'x login' first. "
                f"Detail: {r.json().get('error', r.text)}"
            )
        if r.status_code != 200:
            raise TwitterError(
                f"HTTP {r.status_code}: {r.json().get('error', r.text)}"
            )
        result = r.json()
        if not result.get("success", True):
            raise TwitterError(str(result))
        return result

    def _get(self, path: str) -> dict:
        r = self._client.get(f"{self.base}{path}")
        if r.status_code != 200:
            raise TwitterError(f"HTTP {r.status_code}: {r.text}")
        return r.json()

    # ── Health ──────────────────────────────────────────────────────

    def healthy(self) -> bool:
        """Check if the server is up and authenticated."""
        try:
            data = self._get("/health")
            return data.get("has_auth_token", False) and data.get("has_ct0", False)
        except Exception:
            return False

    def status(self) -> dict:
        """Full health check with detail."""
        return self._get("/health")

    def accounts(self) -> dict:
        """Multi-account status."""
        return self._get("/account/status")

    # ── Users ───────────────────────────────────────────────────────

    def user(self, username: str, limit: int = 200) -> dict:
        """Scrape a user's profile and recent tweets."""
        return self._post("/user", {"username": username, "limit": limit})

    # ── Search & Mining ─────────────────────────────────────────────

    def search(self, query: str, limit: int = 100, product: str = "Latest",
               lang: str | None = None,
               min_likes: int | None = None,
               min_retweets: int | None = None,
               min_followers: int | None = None,
               location: str | None = None,
               since: str | None = None,
               until: str | None = None,
               verified_only: bool = False,
               media_only: bool = False,
               exclude_replies: bool = False,
               exclude_retweets: bool = False,
               ) -> dict:
        """Search tweets by keyword with full filter support."""
        payload = {"query": query, "limit": limit, "product": product}
        if lang: payload["lang"] = lang
        if min_likes: payload["min_faves"] = min_likes
        if min_retweets: payload["min_retweets"] = min_retweets
        if min_followers: payload["min_followers"] = min_followers
        if location: payload["location"] = location
        if since: payload["since"] = since
        if until: payload["until"] = until
        if verified_only: payload["verified_only"] = True
        if media_only: payload["media_only"] = True
        if exclude_replies: payload["exclude_replies"] = True
        if exclude_retweets: payload["exclude_retweets"] = True
        return self._post("/search", payload)

    def pain_mine(self, keyword: str, limit: int = 200, min_score: int = 5) -> dict:
        """Mine Twitter for customer pain signals around a keyword.

        Returns scored, ranked tweets with WTP evidence levels.
        Use this for SaaS idea validation, competitor research, market analysis.
        """
        return self._post("/pain", {"keyword": keyword, "limit": limit, "min_score": min_score})

    # ── Posting ─────────────────────────────────────────────────────

    def tweet(self, text: str, reply_to: str | None = None) -> dict:
        """Post a tweet (text only)."""
        return self._post("/tweet", {"text": text, "reply_to": reply_to})

    def tweet_with_media(self, text: str, file_path: str,
                         media_type: str = "image",
                         reply_to: str | None = None) -> dict:
        """Post a tweet with an image or video attached."""
        # Step 1: Upload media
        media_result = self._post("/media", {"file_path": file_path, "media_type": media_type})
        media_id = media_result.get("media_id")
        if not media_id:
            raise TwitterError(f"Media upload failed: {media_result}")

        # Step 2: Post tweet with media
        data = {"text": text, "media_ids": [media_id]}
        if reply_to:
            data["reply_to"] = reply_to
        return self._post("/tweet", data)

    def reply(self, text: str, tweet_id: str) -> dict:
        """Reply to a tweet."""
        return self.tweet(text, reply_to=tweet_id)

    def like(self, tweet_id: str) -> dict:
        """Like a tweet."""
        return self._post("/like", {"tweet_id": tweet_id})

    def delete(self, tweet_id: str) -> dict:
        """Delete a tweet."""
        return self._post("/delete", {"tweet_id": tweet_id})

    def upload_media(self, file_path: str, media_type: str = "image") -> str:
        """Upload media and return the media_id."""
        result = self._post("/media", {"file_path": file_path, "media_type": media_type})
        return result.get("media_id", "")

    # ── Convenience ─────────────────────────────────────────────────

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── CLI ───────────────────────────────────────────────────────────────────

def _cli():
    """Quick CLI for twx when called directly."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="twx — Twitter API client")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("health", help="Health check")
    p = sub.add_parser("pain", help="Pain mining")
    p.add_argument("keyword")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--min-score", type=int, default=5)

    p = sub.add_parser("search", help="Search tweets")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("users", help="Find users")
    p.add_argument("query")
    p.add_argument("--count", type=int, default=20)

    p = sub.add_parser("thread", help="Get thread")
    p.add_argument("tweet_id")
    p.add_argument("--count", type=int, default=50)

    p = sub.add_parser("tweet", help="Post a tweet")
    p.add_argument("text")

    args = parser.parse_args()

    t = Twitter()
    if args.cmd == "health":
        print(json.dumps(t.status(), indent=2))
    elif args.cmd == "pain":
        result = t.pain_mine(args.keyword, limit=args.limit, min_score=args.min_score)
        print(f"Found {result.get('results_count', 0)} pain signals for '{args.keyword}'")
        for i, r in enumerate(result.get("results", [])[:10], 1):
            tw = r["tweet"]
            print(f"\n#{i} Score: {r['score']} | WTP: {r['wtp_level']} | {r['signals']}")
            print(f"   @{tw.get('author')}: {tw.get('text', '')[:150]}")
            print(f"   {tw.get('url', '')}")
    elif args.cmd == "search":
        result = t.search(args.query, limit=args.limit)
        for tw in result.get("tweets", [])[:5]:
            print(f"@{tw.get('author')}: {tw.get('text', '')[:120]}")
    elif args.cmd == "users":
        users = t.find_users(args.query, count=args.count)
        for u in users:
            print(f"@{u['username']} — {u.get('followers_count', 0):,} followers — {u.get('bio', '')[:80]}")
    elif args.cmd == "thread":
        result = t.thread(args.tweet_id, count=args.count)
        for reply in result.get("replies", [])[:10]:
            print(f"@{reply.get('author')}: {reply.get('text', '')[:120]}")
    elif args.cmd == "tweet":
        result = t.tweet(args.text)
        print(f"Posted: {result.get('url')}")
    else:
        parser.print_help()

    t.close()


if __name__ == "__main__":
    _cli()
