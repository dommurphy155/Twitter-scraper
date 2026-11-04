#!/usr/bin/env python3
"""
Example usage of the twitter_scrape skill.
"""

import asyncio, json, os
from rnet_twitter import RnetTwitterClient
from datetime import datetime

async def scrape_user(username: str, limit: int = 200):
    """
    Scrape a Twitter user's profile and recent tweets.
    """
    client = RnetTwitterClient()
    cookies_path = os.environ.get("TWITTER_COOKIES_PATH", "twitter_cookies.json")
    client.load_cookies(cookies_path)

    # Get user profile
    user = await client.get_user_by_screen_name(username)

    # Get tweets
    tweets = await client.get_user_tweets(user["rest_id"], count=limit)

    # Save to JSON
    output = {
        "scraped_at": datetime.now().isoformat(),
        "profile": {
            "id": user["rest_id"],
            "username": user.get("screen_name", ""),
            "name": user.get("name", ""),
            "bio": user.get("description", ""),
            "followers_count": user.get("followers_count", 0),
            "following_count": user.get("friends_count", 0),
        },
        "tweets": tweets,
        "tweets_count": len(tweets),
    }

    output_path = f"storage/twitter/{username}.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"Saved to {output_path}")
    return output_path

if __name__ == "__main__":
    import sys
    username = sys.argv[1] if len(sys.argv) > 1 else "elonmusk"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    asyncio.run(scrape_user(username, limit))