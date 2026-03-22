#!/usr/bin/env python3
"""
Twitter/X Scraper CLI - Full featured scraper using rnet_twitter client.

Usage:
    python scrape.py user <username> [--limit 200]           # Scrape user profile + tweets
    python scrape.py search "<query>" [--limit 100]           # Search tweets
    python scrape.py tweet "<text>" [--reply-to <id>]         # Post a tweet
    python scrape.py like <tweet_id>                          # Like a tweet
    python scrape.py delete <tweet_id>                        # Delete your tweet
"""

import asyncio
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from rnet_twitter import RnetTwitterClient, TwitterAPIError


def load_cookies(client: RnetTwitterClient, path: str = None) -> None:
    """Load cookies from file or env var."""
    cookies_path = path or os.environ.get("TWITTER_COOKIES_PATH", "twitter_cookies.json")
    if not Path(cookies_path).exists():
        print(f"Error: Cookies file not found: {cookies_path}", file=sys.stderr)
        print("Set TWITTER_COOKIES_PATH or create twitter_cookies.json", file=sys.stderr)
        sys.exit(1)
    client.load_cookies(cookies_path)
    print(f"Loaded cookies from {cookies_path}")


async def scrape_user(args):
    """Scrape a user's profile and tweets."""
    client = RnetTwitterClient()
    load_cookies(client, args.cookies)

    print(f"\nFetching profile for @{args.username}...")
    try:
        user = await client.get_user_by_screen_name(args.username)
    except TwitterAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  Name: {user.get('name', 'N/A')}")
    print(f"  Bio: {user.get('description', 'N/A')[:100]}...")
    print(f"  Followers: {user.get('followers_count', 0):,}")
    print(f"  Following: {user.get('friends_count', 0):,}")
    print(f"  Tweets: {user.get('statuses_count', 0):,}")

    print(f"\nFetching {args.limit} tweets...")
    tweets = await client.get_user_tweets(user["rest_id"], count=args.limit)
    print(f"Got {len(tweets)} tweets")

    # Build output
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

    # Save
    output_dir = Path("storage/twitter")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{args.username}.json"

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nSaved to: {output_path}")

    # Print sample tweets
    if tweets and args.verbose:
        print("\n--- Sample Tweets ---")
        for t in tweets[:3]:
            print(f"\n[{t.get('created_at', 'N/A')}]")
            print(f"  {t.get('text', 'N/A')[:150]}...")
            print(f"  Likes: {t.get('favorite_count', 0)} | RTs: {t.get('retweet_count', 0)}")


async def search_tweets(args):
    """Search for tweets by keyword/query."""
    client = RnetTwitterClient()
    load_cookies(client, args.cookies)

    print(f"\nSearching: '{args.query}'")
    print(f"Product: {args.product} | Limit: {args.limit}")

    try:
        tweets = await client.search_tweets(
            query=args.query,
            count=args.limit,
            product=args.product
        )
    except TwitterAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nGot {len(tweets)} tweets")

    # Build output
    output = {
        "scraped_at": datetime.now().isoformat(),
        "query": args.query,
        "product": args.product,
        "tweets": tweets,
        "tweets_count": len(tweets),
    }

    # Save
    output_dir = Path("storage/twitter")
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_query = args.query.replace(" ", "_").replace(":", "")[:50]
    output_path = output_dir / f"search_{safe_query}.json"

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"Saved to: {output_path}")

    # Print results
    if tweets:
        print("\n--- Results ---")
        for t in tweets[:5]:
            author = t.get('author', 'N/A')
            text = t.get('text', 'N/A')[:100]
            print(f"\n@{author}: {text}...")
            print(f"   Likes: {t.get('favorite_count', 0)} | Views: {t.get('views', 0):,}")


async def post_tweet(args):
    """Post a new tweet or reply."""
    client = RnetTwitterClient()
    load_cookies(client, args.cookies)

    print(f"\nPosting tweet...")
    if args.reply_to:
        print(f"Reply to: {args.reply_to}")
    print(f"Text: {args.text[:100]}...")

    try:
        result = await client.create_tweet(args.text, reply_to=args.reply_to)
        tweet_id = client.extract_tweet_id(result)
        print(f"\nSuccess! Tweet ID: {tweet_id}")
        print(f"URL: https://x.com/i/web/status/{tweet_id}")
    except TwitterAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


async def like_tweet(args):
    """Like a tweet by ID."""
    client = RnetTwitterClient()
    load_cookies(client, args.cookies)

    print(f"\nLiking tweet {args.tweet_id}...")

    try:
        await client.favorite_tweet(args.tweet_id)
        print("Success!")
    except TwitterAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


async def delete_tweet(args):
    """Delete a tweet by ID."""
    client = RnetTwitterClient()
    load_cookies(client, args.cookies)

    print(f"\nDeleting tweet {args.tweet_id}...")

    try:
        await client.delete_tweet(args.tweet_id)
        print("Success!")
    except TwitterAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Twitter/X Scraper CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s user elonmusk --limit 50
  %(prog)s search "OpenAI lang:en" --limit 100
  %(prog)s search "\"machine learning\" min_faves:10" --product Top
  %(prog)s tweet "Hello from CLI!"
  %(prog)s tweet "Replying..." --reply-to 1234567890
  %(prog)s like 1234567890
  %(prog)s delete 1234567890
        """
    )

    parser.add_argument("--cookies", "-c", default=None,
                        help="Path to cookies JSON (default: TWITTER_COOKIES_PATH env or twitter_cookies.json)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # User command
    user_parser = subparsers.add_parser("user", help="Scrape a user's profile and tweets")
    user_parser.add_argument("username", help="Twitter username (without @)")
    user_parser.add_argument("--limit", "-l", type=int, default=200, help="Number of tweets to fetch")
    user_parser.set_defaults(func=scrape_user)

    # Search command
    search_parser = subparsers.add_parser("search", help="Search tweets")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", "-l", type=int, default=100, help="Max tweets to fetch")
    search_parser.add_argument("--product", "-p", choices=["Latest", "Top"], default="Latest",
                               help="Sort by Latest (chronological) or Top (relevance)")
    search_parser.set_defaults(func=search_tweets)

    # Tweet command
    tweet_parser = subparsers.add_parser("tweet", help="Post a tweet")
    tweet_parser.add_argument("text", help="Tweet text")
    tweet_parser.add_argument("--reply-to", "-r", help="Tweet ID to reply to")
    tweet_parser.set_defaults(func=post_tweet)

    # Like command
    like_parser = subparsers.add_parser("like", help="Like a tweet")
    like_parser.add_argument("tweet_id", help="Tweet ID to like")
    like_parser.set_defaults(func=like_tweet)

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete your tweet")
    delete_parser.add_argument("tweet_id", help="Tweet ID to delete")
    delete_parser.set_defaults(func=delete_tweet)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
