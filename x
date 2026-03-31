#!/usr/bin/env python3
"""Twitter/X CLI Client - talks to the twitter-scrape server.

Usage:
    x help                           # Show help
    x user <username> [--limit 200]  # Scrape user profile + tweets
    x search "<query>" [--limit 100] [--product Latest|Top]
    x grok "<message>" [--conversation <id>]  # Chat with Grok
    x tweet "<text>" [--reply-to <id>]
    x like <tweet_id>
    x delete <tweet_id>
    x refresh                        # Manually refresh cookies
    x restart                        # Restart the twitter-scrape service
    x status                         # Check server status
    x account                        # Interactive account selector

Examples:
    x user elonmusk --limit 50
    x grok "What is 5x5?"
    x grok "Tell me more" --conversation 12345
    x search "OpenAI lang:en" --limit 100
    x search '"machine learning" min_faves:10' --product Top
    x tweet "Hello from CLI!"
    x tweet "Replying..." --reply-to 1234567890
    x like 1234567890
    x delete 1234567890
    x refresh                        # Force cookie refresh
    x restart                        # Restart service
    x account                        # Switch accounts
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

# Config - must match server
DEFAULT_HOST = os.environ.get("TWITTER_SCRAPE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("TWITTER_SCRAPE_PORT", "8765"))


def api_call(endpoint, data=None):
    """Make API call to server."""
    url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}{endpoint}"

    # data=None means GET request
    # data={} or data={...} means POST request
    is_post = data is not None

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode() if is_post else None,
            headers={"Content-Type": "application/json"},
            method="POST" if is_post else "GET"
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
    # Get basic health
    result = api_call("/health", None)
    print(f"Server: {'OK' if result.get('status') == 'ok' else 'ERROR'}")
    print(f"Cookies exist: {result.get('cookies_exist', False)}")
    print(f"Cookies valid: {result.get('cookies_valid', False)}")
    print(f"Endpoint: {DEFAULT_HOST}:{DEFAULT_PORT}")

    # Get account status
    try:
        account_result = api_call("/account/status", None)
        current = account_result.get('current_account', 'unknown')
        print(f"Account: {current}")

        # Show all accounts
        accounts = account_result.get('accounts', [])
        if accounts:
            print(f"\n  Accounts:")
            for acc in accounts:
                marker = "❯" if acc.get('is_current') else " "
                status = acc.get('status', 'unknown')
                if status == 'rate_limited':
                    time_left = acc.get('time_until_available', '?')
                    print(f"    {marker} {acc['username']} [rate limited — {time_left} remaining]")
                else:
                    print(f"    {marker} {acc['username']} [active]")
    except Exception as e:
        print(f"Account status: unavailable ({e})")


def cmd_user(args):
    """Scrape a user."""
    print(f"Fetching @{args.username}...")
    result = api_call("/user", {"username": args.username, "limit": args.limit})

    # Show refresh status if cookies were refreshed
    if result.get('_meta', {}).get('refreshed'):
        print("  ⚠️  Cookies expired, refreshing...")
        print("  ✓  Refreshed!")

    print(f"✓ Saved to: {result['path']}")
    print(f"  Tweets: {result['tweets_count']}")


def cmd_search(args):
    """Search tweets."""
    print(f"Searching: {args.query}")
    result = api_call("/search", {
        "query": args.query,
        "limit": args.limit,
        "product": args.product
    })

    # Show refresh status if cookies were refreshed
    if result.get('_meta', {}).get('refreshed'):
        print("  ⚠️  Cookies expired, refreshing...")
        print("  ✓  Refreshed!")

    print(f"✓ Found: {result['tweets_count']} tweets")
    print(f"  Saved to: {result['path']}")

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

    # Show refresh status if cookies were refreshed
    if result.get('_meta', {}).get('refreshed'):
        print("  ⚠️  Cookies expired, refreshing...")
        print("  ✓  Refreshed!")

    print(f"✓ Posted! Tweet ID: {result['tweet_id']}")
    print(f"  URL: {result['url']}")


def cmd_like(args):
    """Like a tweet."""
    print(f"Liking tweet {args.tweet_id}...")
    result = api_call("/like", {"tweet_id": args.tweet_id})

    # Show refresh status if cookies were refreshed
    if result.get('_meta', {}).get('refreshed'):
        print("  ⚠️  Cookies expired, refreshing...")
        print("  ✓  Refreshed!")

    print("✓ Liked!")


def cmd_delete(args):
    """Delete a tweet."""
    print(f"Deleting tweet {args.tweet_id}...")
    result = api_call("/delete", {"tweet_id": args.tweet_id})

    # Show refresh status if cookies were refreshed
    if result.get('_meta', {}).get('refreshed'):
        print("  ⚠️  Cookies expired, refreshing...")
        print("  ✓  Refreshed!")

    print("✓ Deleted!")


def cmd_refresh(args=None):
    """Manually refresh cookies with detailed output."""
    result = api_call("/refresh", {})

    # Display detailed progress messages
    if result.get('details'):
        for msg in result['details']:
            print(msg)
    else:
        print("Refreshing cookies...")

    if not result.get('success'):
        print(f"Failed: {result.get('error', 'Unknown error')}")


def cmd_restart(args=None):
    """Restart the twitter-scrape service."""
    import subprocess
    print("Restarting twitter-scrape service...")
    try:
        subprocess.run(["sudo", "systemctl", "restart", "twitter-scrape.service"], check=True)
        print("✓ Service restarted successfully")
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to restart service: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("Error: systemctl not found. Are you on a systemd system?", file=sys.stderr)
        sys.exit(1)


def cmd_grok(args):
    """Chat with Grok."""
    conversation_id = args.conversation

    # Send message (creates conversation automatically if needed)
    print(f"Sending to Grok: {args.message}")
    result = api_call("/grok/chat", {
        "message": args.message,
        "conversation_id": conversation_id
    })

    # Show refresh status if cookies were refreshed
    if result.get('_meta', {}).get('refreshed'):
        print("  ⚠️  Cookies expired, refreshing...")
        print("  ✓  Refreshed!")

    # Show account used (if multi-account)
    if result.get('account'):
        print(f"  Account: {result['account']}")

    # Print response
    grok_response = result.get('response', 'No response received')
    print(f"\n🤖 Grok:\n{grok_response}")

    # Show conversation ID and file path (ALWAYS)
    new_id = result.get('conversation_id') or 'unknown'
    response_file = result.get('response_file') or 'unknown'
    print()  # Blank line before metadata
    print(f"--conversation {new_id}")
    # Convert to ~/ shorthand
    home = os.path.expanduser("~")
    if response_file.startswith(home):
        response_file = "~" + response_file[len(home):]
    print(response_file)


def cmd_account(args=None):
    """Interactive account selector."""
    # Get current account status
    try:
        result = api_call("/account/status", None)
    except Exception as e:
        print(f"Error: Could not get account status: {e}", file=sys.stderr)
        sys.exit(1)

    accounts = result.get('accounts', [])
    current = result.get('current_account')

    if not accounts:
        print("No accounts configured.")
        print("Add ACCOUNT_N_USERNAME entries to .env file")
        sys.exit(1)

    # Build menu
    print("\n  Select an account:")
    print()

    available_accounts = []
    for i, acc in enumerate(accounts):
        marker = "❯" if acc.get('is_current') else " "
        status = acc.get('status', 'unknown')

        if status == 'rate_limited':
            time_left = acc.get('time_until_available', '?')
            print(f"  {marker} {i+1}. {acc['username']} [rate limited — {time_left} remaining]")
        else:
            print(f"  {marker} {i+1}. {acc['username']} [active]")
            available_accounts.append(acc['username'])

    print()
    print("  [Enter number to select, or Ctrl+C to cancel]")
    print()

    # Get user input
    try:
        choice = input("  Account: ").strip()
    except KeyboardInterrupt:
        print("\n  Cancelled.")
        sys.exit(0)

    # Validate choice
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(accounts):
            print("Invalid selection.", file=sys.stderr)
            sys.exit(1)
    except ValueError:
        print("Please enter a number.", file=sys.stderr)
        sys.exit(1)

    selected_username = accounts[idx]['username']

    # Check if rate limited
    if selected_username not in available_accounts:
        print(f"\n  ⚠️  {selected_username} is currently rate limited.")
        print("  Try again later or select a different account.")
        sys.exit(1)

    # Perform switch
    print(f"\n  Switching to {selected_username}...")
    try:
        result = api_call("/account/switch", {"username": selected_username})
        if result.get('success'):
            print(f"  ✓ Switched to {selected_username}")
            print(f"  ✓ Session refreshed")
            print(f"  ✓ Grok tab opened")
        else:
            print(f"  ✗ Switch failed: {result.get('error', 'Unknown error')}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


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
  x refresh
  x status
  x account
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
    tweet_parser.add_argument("--reply-to", "-r", help="Tweet ID to reply to")

    # Like
    like_parser = subparsers.add_parser("like", help="Like a tweet")
    like_parser.add_argument("tweet_id", help="Tweet ID")

    # Delete
    delete_parser = subparsers.add_parser("delete", help="Delete your tweet")
    delete_parser.add_argument("tweet_id", help="Tweet ID")

    # Grok
    grok_parser = subparsers.add_parser("grok", help="Chat with Grok")
    grok_parser.add_argument("message", help="Message to send to Grok")
    grok_parser.add_argument("--conversation", "-c", help="Continue existing conversation ID")

    # Refresh
    subparsers.add_parser("refresh", help="Manually refresh cookies")

    # Restart
    subparsers.add_parser("restart", help="Restart the twitter-scrape service")

    # Account
    subparsers.add_parser("account", help="Interactive account selector")

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
        "grok": cmd_grok,
        "tweet": cmd_tweet,
        "like": cmd_like,
        "delete": cmd_delete,
        "refresh": cmd_refresh,
        "restart": cmd_restart,
        "account": cmd_account,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
