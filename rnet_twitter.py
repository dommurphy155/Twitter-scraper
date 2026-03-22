"""Lightweight Twitter GraphQL client using rnet (bypasses Cloudflare).

Drop-in replacement for twikit's Client for the functions we actually use:
- load_cookies / get_cookies
- get_user_by_screen_name
- get_user_tweets
- search_tweets (NEW — keyword search with pagination)
- create_tweet (with reply_to)
- favorite_tweet
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from rnet import Client as RnetClient, Emulation

# Common bearer token (same for all Twitter users)
TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

GRAPHQL_BASE = "https://x.com/i/api/graphql"

# Endpoint IDs — update if Twitter rotates them.
# SearchTimeline extracted from x.com main bundle 2026-02-24.
ENDPOINTS = {
    "UserByScreenName": "NimuplG1OB7Fd2btCLdBOw/UserByScreenName",
    "UserTweets": "QWF3SzpHmykQHsQMixG0cg/UserTweets",
    "SearchTimeline": "ML-n2SfAxx5S_9QMqNejbg/SearchTimeline",
    "CreateTweet": "SiM_cAu83R0wnrpmKQQSEw/CreateTweet",
    "FavoriteTweet": "lI07N6Otwv1PhnEgXILM7A/FavoriteTweet",
    "DeleteTweet": "VaenaVgh5q5ih7kvyVjgtg/DeleteTweet",
}

FEATURES = {
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "responsive_web_media_download_video_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

USER_FEATURES = {
    "hidden_profile_likes_enabled": True,
    "hidden_profile_subscriptions_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}


class TwitterAPIError(Exception):
    """Raised when Twitter API returns an error."""

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"Twitter API error {status}: {message}")


class RnetTwitterClient:
    """Async Twitter client powered by rnet (Cloudflare-safe)."""

    def __init__(self, language: str = "en-US"):
        self._rnet = RnetClient(emulation=Emulation.Chrome133)
        self._cookies: dict[str, str] = {}
        self._language = language
        self._user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/133.0.0.0 Safari/537.36"
        )

    # ── Cookie Management ──────────────────────────────────────────────

    def load_cookies(self, path: str) -> None:
        """Load cookies from a JSON file (twikit format)."""
        raw = json.loads(Path(path).read_text())
        if isinstance(raw, list):
            self._cookies = {c["name"]: c["value"] for c in raw}
        else:
            self._cookies = dict(raw)

    def get_cookies(self) -> dict[str, str]:
        return dict(self._cookies)

    # ── Internal Helpers ───────────────────────────────────────────────

    @property
    def _ct0(self) -> str:
        return self._cookies.get("ct0", "")

    @property
    def _cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self._cookies.items())

    @property
    def _base_headers(self) -> dict[str, str]:
        headers = {
            "authorization": f"Bearer {TOKEN}",
            "content-type": "application/json",
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-active-user": "yes",
            "x-csrf-token": self._ct0,
            "cookie": self._cookie_header,
            "referer": "https://x.com/",
            "user-agent": self._user_agent,
            "accept-language": f"{self._language},{self._language.split('-')[0]};q=0.9",
        }
        return headers

    def _gql_url(self, endpoint_key: str) -> str:
        return f"{GRAPHQL_BASE}/{ENDPOINTS[endpoint_key]}"

    @staticmethod
    def _query_id(endpoint_key: str) -> str:
        return ENDPOINTS[endpoint_key].split("/")[0]

    async def _gql_get(
        self,
        endpoint_key: str,
        variables: dict,
        features: dict | None = None,
        extra_params: dict | None = None,
    ) -> dict:
        params_parts = [f"variables={quote(json.dumps(variables))}"]
        if features is not None:
            params_parts.append(f"features={quote(json.dumps(features))}")
        if extra_params:
            for k, v in extra_params.items():
                val = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                params_parts.append(f"{k}={quote(val)}")

        url = f"{self._gql_url(endpoint_key)}?{'&'.join(params_parts)}"
        resp = await self._rnet.get(url, headers=self._base_headers)

        if resp.status != 200:
            text = await resp.text()
            raise TwitterAPIError(resp.status, text[:500])

        return json.loads(await resp.text())

    async def _gql_post(
        self,
        endpoint_key: str,
        variables: dict,
        features: dict | None = None,
    ) -> dict:
        data: dict = {
            "variables": variables,
            "queryId": self._query_id(endpoint_key),
        }
        if features is not None:
            data["features"] = features

        resp = await self._rnet.post(
            self._gql_url(endpoint_key),
            headers=self._base_headers,
            json=data,
        )

        if resp.status != 200:
            text = await resp.text()
            raise TwitterAPIError(resp.status, text[:500])

        return json.loads(await resp.text())

    # ── Internal: parse tweet from search/timeline result ────────────

    @staticmethod
    def _parse_tweet(result: dict) -> dict | None:
        """Parse a tweet result dict into a flat tweet dict.

        Works with both UserTweets and SearchTimeline responses.
        Handles the 2026-02 API change where screen_name moved to
        core.user_results.result.core (not .legacy).
        """
        if result.get("__typename") == "TweetWithVisibilityResults":
            result = result.get("tweet", {})

        legacy = result.get("legacy", {})
        if not legacy:
            return None

        # User info — try new path first (core.core), then old path (core.legacy)
        user_result = (
            result.get("core", {})
            .get("user_results", {})
            .get("result", {})
        )
        user_core = user_result.get("core", {})
        user_legacy = user_result.get("legacy", {})

        screen_name = (
            user_core.get("screen_name")
            or user_legacy.get("screen_name", "")
        )
        display_name = (
            user_core.get("name")
            or user_legacy.get("name", "")
        )

        views_raw = result.get("views", {}).get("count", "0")
        try:
            views = int(views_raw)
        except (ValueError, TypeError):
            views = 0

        return {
            "id": legacy.get("id_str", result.get("rest_id", "")),
            "text": legacy.get("full_text", ""),
            "author": screen_name,
            "display_name": display_name,
            "favorite_count": legacy.get("favorite_count", 0),
            "reply_count": legacy.get("reply_count", 0),
            "retweet_count": legacy.get("retweet_count", 0),
            "views": views,
            "created_at": legacy.get("created_at", ""),
            "url": (
                f"https://x.com/{screen_name}/status/"
                f"{legacy.get('id_str', result.get('rest_id', ''))}"
                if screen_name else ""
            ),
            "is_reply": bool(legacy.get("in_reply_to_status_id_str")),
            "is_quote": bool(result.get("quoted_status_result")),
        }

    # ── Public API ─────────────────────────────────────────────────────

    async def get_user_by_screen_name(self, screen_name: str) -> dict:
        """Get user info by screen name. Returns legacy user dict."""
        variables = {
            "screen_name": screen_name,
            "withSafetyModeUserFields": False,
        }
        extra = {"fieldToggles": {"withAuxiliaryUserLabels": False}}
        data = await self._gql_get(
            "UserByScreenName", variables, USER_FEATURES, extra
        )
        result = data.get("data", {}).get("user", {}).get("result", {})
        if not result:
            raise TwitterAPIError(404, f"User @{screen_name} not found")

        legacy = result.get("legacy", {})
        legacy["rest_id"] = result.get("rest_id", "")
        return legacy

    async def get_user_tweets(
        self, user_id: str, count: int = 10
    ) -> list[dict]:
        """Get recent tweets for a user ID. Returns list of tweet dicts."""
        variables = {
            "userId": user_id,
            "count": count,
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        data = await self._gql_get("UserTweets", variables, FEATURES)

        tweets = []
        instructions = (
            data.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("timeline_v2", {})
            .get("timeline", {})
            .get("instructions", [])
        )

        for instruction in instructions:
            entries = instruction.get("entries", [])
            for entry in entries:
                content = entry.get("content", {})
                item = content.get("itemContent", {})
                tweet_results = item.get("tweet_results", {})
                result = tweet_results.get("result", {})

                # Handle tweet with visibility results wrapper
                if result.get("__typename") == "TweetWithVisibilityResults":
                    result = result.get("tweet", {})

                legacy = result.get("legacy", {})
                if not legacy:
                    continue

                core = result.get("core", {})
                user_legacy = (
                    core.get("user_results", {})
                    .get("result", {})
                    .get("legacy", {})
                )

                tweets.append({
                    "id": legacy.get("id_str", result.get("rest_id", "")),
                    "text": legacy.get("full_text", ""),
                    "author": user_legacy.get("screen_name", ""),
                    "favorite_count": legacy.get("favorite_count", 0),
                    "reply_count": legacy.get("reply_count", 0),
                    "retweet_count": legacy.get("retweet_count", 0),
                    "created_at": legacy.get("created_at", ""),
                })

        return tweets

    async def search_tweets(
        self,
        query: str,
        count: int = 100,
        product: str = "Latest",
    ) -> list[dict]:
        """Search Twitter by keyword. Returns list of tweet dicts.

        Args:
            query: Search query. Supports Twitter operators:
                - "OpenClaw lang:en" — language filter
                - '"exact phrase"' — exact match
                - "OpenClaw since:2026-01-24 until:2026-02-24" — date range
                - "OpenClaw min_faves:10" — min likes
                - "OpenClaw -filter:replies" — exclude replies
            count: Max tweets to return (will paginate automatically).
            product: "Latest" (chronological) or "Top" (relevance).

        Returns:
            List of tweet dicts with: id, text, author, display_name,
            favorite_count, reply_count, retweet_count, views, created_at,
            url, is_reply, is_quote.
        """
        tweets: list[dict] = []
        cursor: str | None = None
        per_page = min(count, 20)

        while len(tweets) < count:
            variables: dict = {
                "rawQuery": query,
                "count": per_page,
                "querySource": "typed_query",
                "product": product,
            }
            if cursor is not None:
                variables["cursor"] = cursor

            # SearchTimeline requires POST (GET returns 404)
            data = await self._gql_post(
                "SearchTimeline", variables, FEATURES
            )

            instructions = (
                data.get("data", {})
                .get("search_by_raw_query", {})
                .get("search_timeline", {})
                .get("timeline", {})
                .get("instructions", [])
            )

            new_cursor = None
            batch_count = 0

            for instruction in instructions:
                inst_type = instruction.get("type", "")

                # Page 1+: cursor comes in TimelineReplaceEntry
                if inst_type == "TimelineReplaceEntry":
                    entry = instruction.get("entry", {})
                    eid = entry.get("entryId", "")
                    if "cursor-bottom" in eid:
                        new_cursor = entry.get("content", {}).get("value")
                    continue

                # Page 0: entries include tweets and cursors
                entries = instruction.get("entries", [])
                for entry in entries:
                    eid = entry.get("entryId", "")
                    content = entry.get("content", {})

                    # Cursor entries
                    if "cursor-bottom" in eid:
                        new_cursor = content.get("value")
                        continue
                    if "cursor-top" in eid:
                        continue

                    item = content.get("itemContent", {})
                    result = item.get("tweet_results", {}).get("result", {})
                    tweet = self._parse_tweet(result)
                    if tweet:
                        tweets.append(tweet)
                        batch_count += 1

            # Stop if no new tweets or no cursor
            if batch_count == 0 or new_cursor is None:
                break

            cursor = new_cursor

        return tweets[:count]

    async def create_tweet(
        self,
        text: str,
        reply_to: str | None = None,
    ) -> dict:
        """Create a tweet or reply."""
        variables: dict = {
            "tweet_text": text,
            "dark_request": False,
            "media": {
                "media_entities": [],
                "possibly_sensitive": False,
            },
            "semantic_annotation_ids": [],
        }
        if reply_to is not None:
            variables["reply"] = {
                "in_reply_to_tweet_id": reply_to,
                "exclude_reply_user_ids": [],
            }

        return await self._gql_post("CreateTweet", variables, FEATURES)

    async def favorite_tweet(self, tweet_id: str) -> dict:
        """Like a tweet."""
        variables = {"tweet_id": tweet_id}
        return await self._gql_post("FavoriteTweet", variables)

    async def delete_tweet(self, tweet_id: str) -> dict:
        """Delete a tweet."""
        variables = {"tweet_id": tweet_id, "dark_request": False}
        return await self._gql_post("DeleteTweet", variables)

    @staticmethod
    def extract_tweet_id(result: dict) -> str | None:
        """Extract tweet ID from create_tweet response."""
        try:
            return result["data"]["create_tweet"]["tweet_results"]["result"]["rest_id"]
        except (KeyError, TypeError):
            return None
