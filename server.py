#!/usr/bin/env python3
"""
Twitter Scraper API Server - Runs as systemd service.

Endpoints:
    POST /user        - Scrape user profile + tweets
    POST /search      - Search tweets
    POST /tweet       - Post a tweet
    POST /like        - Like a tweet
    POST /delete      - Delete a tweet
    GET  /health      - Health check
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import urllib.parse

from rnet_twitter import RnetTwitterClient, TwitterAPIError

# Config
COOKIES_PATH = os.environ.get("TWITTER_COOKIES_PATH", "twitter_cookies.json")
HOST = os.environ.get("TWITTER_SCRAPE_HOST", "127.0.0.1")
PORT = int(os.environ.get("TWITTER_SCRAPE_PORT", 8765))
STORAGE_DIR = Path("storage/twitter")

# Ensure storage dir exists
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def response(status_code, data):
    """Build JSON response."""
    return status_code, {"Content-Type": "application/json"}, json.dumps(data).encode()


class TwitterHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Twitter API."""

    def log_message(self, format, *args):
        """Custom logging."""
        print(f"[{datetime.now().isoformat()}] {args[0]}")

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health":
            self._send(*response(200, {"status": "ok", "cookies_loaded": Path(COOKIES_PATH).exists()}))
        else:
            self._send(*response(404, {"error": "Not found"}))

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

    def _handle_user(self, data):
        """Scrape user profile and tweets."""
        username = data.get("username")
        limit = data.get("limit", 200)

        if not username:
            self._send(*response(400, {"error": "username required"}))
            return

        async def _do():
            client = RnetTwitterClient()
            client.load_cookies(COOKIES_PATH)

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

            # Save to file
            output_path = STORAGE_DIR / f"{username}.json"
            with open(output_path, "w") as f:
                json.dump(output, f, indent=2, default=str)

            return {"success": True, "path": str(output_path), "tweets_count": len(tweets)}

        try:
            result = asyncio.run(_do())
            self._send(*response(200, result))
        except TwitterAPIError as e:
            self._send(*response(400, {"error": str(e)}))
        except Exception as e:
            self._send(*response(500, {"error": str(e)}))

    def _handle_search(self, data):
        """Search tweets."""
        query = data.get("query")
        limit = data.get("limit", 100)
        product = data.get("product", "Latest")

        if not query:
            self._send(*response(400, {"error": "query required"}))
            return

        async def _do():
            client = RnetTwitterClient()
            client.load_cookies(COOKIES_PATH)

            tweets = await client.search_tweets(query=query, count=limit, product=product)

            output = {
                "scraped_at": datetime.now().isoformat(),
                "query": query,
                "product": product,
                "tweets": tweets,
                "tweets_count": len(tweets),
            }

            # Save to file
            safe_query = query.replace(" ", "_").replace(":", "")[:50]
            output_path = STORAGE_DIR / f"search_{safe_query}.json"
            with open(output_path, "w") as f:
                json.dump(output, f, indent=2, default=str)

            return {"success": True, "path": str(output_path), "tweets_count": len(tweets), "tweets": tweets}

        try:
            result = asyncio.run(_do())
            self._send(*response(200, result))
        except TwitterAPIError as e:
            self._send(*response(400, {"error": str(e)}))
        except Exception as e:
            self._send(*response(500, {"error": str(e)}))

    def _handle_tweet(self, data):
        """Post a tweet."""
        text = data.get("text")
        reply_to = data.get("reply_to")

        if not text:
            self._send(*response(400, {"error": "text required"}))
            return

        async def _do():
            client = RnetTwitterClient()
            client.load_cookies(COOKIES_PATH)

            result = await client.create_tweet(text, reply_to=reply_to)
            tweet_id = client.extract_tweet_id(result)

            return {
                "success": True,
                "tweet_id": tweet_id,
                "url": f"https://x.com/i/web/status/{tweet_id}"
            }

        try:
            result = asyncio.run(_do())
            self._send(*response(200, result))
        except TwitterAPIError as e:
            self._send(*response(400, {"error": str(e)}))
        except Exception as e:
            self._send(*response(500, {"error": str(e)}))

    def _handle_like(self, data):
        """Like a tweet."""
        tweet_id = data.get("tweet_id")

        if not tweet_id:
            self._send(*response(400, {"error": "tweet_id required"}))
            return

        async def _do():
            client = RnetTwitterClient()
            client.load_cookies(COOKIES_PATH)
            await client.favorite_tweet(tweet_id)
            return {"success": True}

        try:
            result = asyncio.run(_do())
            self._send(*response(200, result))
        except TwitterAPIError as e:
            self._send(*response(400, {"error": str(e)}))
        except Exception as e:
            self._send(*response(500, {"error": str(e)}))

    def _handle_delete(self, data):
        """Delete a tweet."""
        tweet_id = data.get("tweet_id")

        if not tweet_id:
            self._send(*response(400, {"error": "tweet_id required"}))
            return

        async def _do():
            client = RnetTwitterClient()
            client.load_cookies(COOKIES_PATH)
            await client.delete_tweet(tweet_id)
            return {"success": True}

        try:
            result = asyncio.run(_do())
            self._send(*response(200, result))
        except TwitterAPIError as e:
            self._send(*response(400, {"error": str(e)}))
        except Exception as e:
            self._send(*response(500, {"error": str(e)}))


def run_server():
    """Run the HTTP server."""
    server = HTTPServer((HOST, PORT), TwitterHandler)
    print(f"Twitter Scraper Server running on http://{HOST}:{PORT}")
    print(f"Cookies: {COOKIES_PATH}")
    print(f"Storage: {STORAGE_DIR}")
    print("Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    run_server()
