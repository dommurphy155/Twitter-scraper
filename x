#!/usr/bin/env python3
"""
Twitter/X CLI Client - talks to the twitter-scrape server.

Usage:
    x help                           # Show help
    x user <username> [--limit 200]  # Scrape user profile + tweets
    x search "<query>" [--limit 100] [--product Latest|Top]
    x tweet "<text>" [--reply-to <id>]
    x like <tweet_id>
    x delete <tweet_id>
    x status                         # Check server status

Examples:
    x user elonmusk --limit 50
    x search "OpenAI lang:en" --limit 100
    x search '"machine learning" min_faves:10' --product Top
    x tweet "Hello from CLI!"
    x tweet "Replying..." --reply-to 1234567890
    x like 1234567890
    x delete 1234567890
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

# Config - must match server
DEFAULT_HOST = os.environ.get("TWITTER_SCRAPE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("TWITTER_SCRAPE_PORT", 8765))


def api_call(endpoint, data=None):
    """Make API call to server."""
    url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}{endpoint}"

    if data is None:
        data = {}

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode() if data else None,
            headers={"Content-Type": "application/json"},
            method="POST" if data else "GET"
        )

        with urllib.request.urlopen(req, timeout=300) as response:
            return json.loads(response.read().decode())

    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        try:
            error_data = json.loads(error_body)
            print(f"Error: {error_data.get('error', 'Unknown error')}", file=sys.stderr)
        except:
            print(f"HTTP Error {e.code}: {error_body}", file=sys.stderr)
        sys.exit(1)

    except urllib.error.URLError as e:
        print(f"Cannot connect to server at {DEFAULT_HOST}:{DEFAULT_PORT}", file=sys.stderr)
        print("Is the server running? Try: sudo systemctl start twitter-scrape", file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args=None):
    """Check server status."""
    result = api_call("/health", None)
    print(f"Server: {'OK' if result.get('status') == 'ok' else 'ERROR'}")
    print(f"Cookies loaded: {result.get('cookies_loaded', False)}")
    print(f"Endpoint: {DEFAULT_HOST}:{DEFAULT_PORT}")


def cmd_user(args):
    """Scrape a user."""
    print(f"Fetching @{args.username}...")
    result = api_call("/user", {"username": args.username, "limit": args.limit})
    print(f"Saved to: {result['path']}")
    print(f"Tweets: {result['tweets_count']}")


def cmd_search(args):
    """Search tweets."""
    print(f"Searching: {args.query}")
    result = api_call("/search", {
        "query": args.query,
        "limit": args.limit,
        "product": args.product
    })
    print(f"Found: {result['tweets_count']} tweets")
    print(f"Saved to: {result['path']}")

    # Show preview
    if result.get('tweets'):
        print("\n--- Top Results ---")
        for t in result['tweets'][:5]:
            author = t.get('author', 'N/A')
            text = t.get('text', 'N/A')[:100]
            print(f"\n@{author}: {text}...")
            print(f"   Likes: {t.get('favorite_count', 0)} | Views: {t.get('views', 0):,}")


def cmd_tweet(args):
    """Post a tweet."""
    print(f"Posting tweet...")
    result = api_call("/tweet", {"text": args.text, "reply_to": args.reply_to})
    print(f"Success! Tweet ID: {result['tweet_id']}")
    print(f"URL: {result['url']}")


def cmd_like(args):
    """Like a tweet."""
    print(f"Liking tweet {args.tweet_id}...")
    api_call("/like", {"tweet_id": args.tweet_id})
    print("Success!")


def cmd_delete(args):
    """Delete a tweet."""
    print(f"Deleting tweet {args.tweet_id}...")
    api_call("/delete", {"tweet_id": args.tweet_id})
    print("Success!")


def cmd_help():
    """Show help."""
    print(__doc__)


def main():
    parser = argparse.ArgumentParser(
        description="Twitter/X CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  x user elonmusk --limit 50
  x search "OpenAI lang:en"
  x search '"machine learning" min_faves:10' --product Top
  x tweet "Hello world!"
  x status
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Status
    subparsers.add_parser("status", help="Check server status")

    # User
    user_parser = subparsers.add_parser("user", help="Scrape a user")
    user_parser.add_argument("username", help="Twitter username")
    user_parser.add_argument("--limit", "-l", type=int, default=200, help="Tweet limit")

    # Search
    search_parser = subparsers.add_parser("search", help="Search tweets")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", "-l", type=int, default=100)
    search_parser.add_argument("--product", "-p", choices=["Latest", "Top"], default="Latest")

    # Tweet
    tweet_parser = subparsers.add_parser("tweet", help="Post a tweet")
    tweet_parser.add_argument("text", help="Tweet text")
    tweet_parser.add_argument("--reply-to", "-r", help="Reply to tweet ID")

    # Like
    like_parser = subparsers.add_parser("like", help="Like a tweet")
    like_parser.add_argument("tweet_id", help="Tweet ID")

    # Delete
    delete_parser = subparsers.add_parser("delete", help="Delete your tweet")
    delete_parser.add_argument("tweet_id", help="Tweet ID")

    # Help
    subparsers.add_parser("help", help="Show help")

    args = parser.parse_args()

    if not args.command or args.command == "help":
        cmd_help()
        return

    # Route commands
    commands = {
        "status": cmd_status,
        "user": cmd_user,
        "search": cmd_search,
        "tweet": cmd_tweet,
        "like": cmd_like,
        "delete": cmd_delete,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
