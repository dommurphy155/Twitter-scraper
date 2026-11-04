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

        followers = user_legacy.get("followers_count", 0) or 0
        location = user_legacy.get("location", "") or ""
        verified = (
            user_core.get("is_blue_verified", False)
            or user_legacy.get("verified", False)
            or user_legacy.get("is_blue_verified", False)
        )
        has_media = bool(
            legacy.get("extended_entities", {}).get("media")
            or legacy.get("entities", {}).get("media")
        )

        return {
            "id": legacy.get("id_str", result.get("rest_id", "")),
            "text": legacy.get("full_text", ""),
            "author": screen_name,
            "display_name": display_name,
            "followers_count": followers,
            "location": location,
            "verified": bool(verified),
            "has_media": has_media,
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

                # Use shared parser — fixes engagement metrics
                tweet = self._parse_tweet(result)
                if tweet:
                    tweets.append(tweet)

        return tweets

    async def search_tweets(
        self,
        query: str,
        count: int = 100,
        product: str = "Latest",
        lang: str | None = None,
        min_faves: int | None = None,
        min_retweets: int | None = None,
        since: str | None = None,
        until: str | None = None,
        exclude_replies: bool = False,
        exclude_retweets: bool = False,
        verified_only: bool = False,
        media_only: bool = False,
        min_followers: int | None = None,
        location: str | None = None,
    ) -> list[dict]:
        """Search Twitter by keyword with structured filters.

        Twitter-native filters (baked into query string):
            lang, min_faves, min_retweets, since, until,
            exclude_replies, exclude_retweets, verified_only, media_only

        Post-filters (applied after API response):
            min_followers, location

        Args:
            query: Search query. Also supports inline operators.
            count: Max tweets to return (paginates automatically).
            product: "Latest" or "Top".
            lang: ISO 639-1 language code (en, zh, ja, ko, fr, de, etc.).
            min_faves: Minimum likes.
            min_retweets: Minimum retweets.
            since: ISO date YYYY-MM-DD or YYYY-MM-DD_HH:MM:SS_UTC.
            until: ISO date (same format).
            exclude_replies: Exclude reply tweets.
            exclude_retweets: Exclude retweets.
            verified_only: Only verified (blue) accounts.
            media_only: Only tweets with images/video.
            min_followers: Minimum follower count (post-filter).
            location: Profile location substring match, case-insensitive (post-filter).

        Returns:
            List of tweet dicts with: id, text, author, display_name,
            followers_count, location, verified, has_media,
            favorite_count, reply_count, retweet_count, views, created_at,
            url, is_reply, is_quote.
        """
        # Build the query string with native Twitter operators
        parts = [query]

        if lang:
            parts.append(f"lang:{lang}")
        if min_faves:
            parts.append(f"min_faves:{min_faves}")
        if min_retweets:
            parts.append(f"min_retweets:{min_retweets}")
        if since:
            parts.append(f"since:{since}")
        if until:
            parts.append(f"until:{until}")
        if exclude_replies:
            parts.append("-filter:replies")
        if exclude_retweets:
            parts.append("-filter:retweets")
        if verified_only:
            parts.append("filter:verified")
        if media_only:
            parts.append("filter:media")

        full_query = " ".join(parts)

        tweets: list[dict] = []
        cursor: str | None = None
        per_page = min(count, 20)
        # Fetch extra to account for post-filter drops
        fetch_target = count * 3 if (min_followers or location) else count

        while len(tweets) < fetch_target:
            variables: dict = {
                "rawQuery": full_query,
                "count": per_page,
                "querySource": "typed_query",
                "product": product,
            }
            if cursor is not None:
                variables["cursor"] = cursor

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

                if inst_type == "TimelineReplaceEntry":
                    entry = instruction.get("entry", {})
                    eid = entry.get("entryId", "")
                    if "cursor-bottom" in eid:
                        new_cursor = entry.get("content", {}).get("value")
                    continue

                entries = instruction.get("entries", [])
                for entry in entries:
                    eid = entry.get("entryId", "")
                    content = entry.get("content", {})

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

            if batch_count == 0 or new_cursor is None:
                break

            cursor = new_cursor

        # ── Post-filters (not supported natively by Twitter GraphQL) ────
        if min_followers is not None:
            tweets = [t for t in tweets if t.get("followers_count", 0) >= min_followers]

        if location:
            loc_lower = location.lower()
            tweets = [
                t for t in tweets
                if loc_lower in (t.get("location", "") or "").lower()
            ]

        return tweets[:count]

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

    # ── Media upload ──────────────────────────────────────────────────

    async def upload_media(
        self, file_path: str, media_type: str = "image"
    ) -> str | None:
        """Upload an image or video. Returns media_id for use in create_tweet."""
        import mimetypes
        from pathlib import Path

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Media file not found: {file_path}")

        total_bytes = path.stat().st_size
        mime_type = mimetypes.guess_type(file_path)[0] or (
            "video/mp4" if media_type == "video" else "image/jpeg"
        )
        media_category = (
            "tweet_video" if media_type == "video"
            else "tweet_gif" if mime_type == "image/gif"
            else "tweet_image"
        )

        # Step 1: INIT — get media_id
        init_data = {
            "command": "INIT",
            "total_bytes": total_bytes,
            "media_type": mime_type,
            "media_category": media_category,
        }
        init_resp = await self._rnet.post(
            "https://upload.twitter.com/1.1/media/upload.json",
            headers={
                **self._base_headers,
                "content-type": "application/x-www-form-urlencoded",
            },
            data=init_data,
        )
        if init_resp.status not in (200, 202):
            text = await init_resp.text()
            raise TwitterAPIError(init_resp.status, f"Media INIT failed: {text[:300]}")

        init_json = json.loads(await init_resp.text())
        media_id = init_json.get("media_id_string")
        if not media_id:
            raise TwitterAPIError(500, f"No media_id in INIT response: {init_json}")

        # Step 2: APPEND — upload the bytes in chunks
        chunk_size = 4 * 1024 * 1024  # 4MB chunks
        segment_index = 0
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                append_data = {
                    "command": "APPEND",
                    "media_id": media_id,
                    "segment_index": str(segment_index),
                }
                resp = await self._rnet.post(
                    "https://upload.twitter.com/1.1/media/upload.json",
                    headers={
                        **self._base_headers,
                        "content-type": "multipart/form-data",
                    },
                    data=append_data,
                    files={"media": chunk},
                )
                if resp.status not in (200, 202, 204):
                    text = await resp.text()
                    raise TwitterAPIError(resp.status, f"Media APPEND failed: {text[:300]}")
                segment_index += 1

        # Step 3: FINALIZE
        finalize_data = {
            "command": "FINALIZE",
            "media_id": media_id,
        }
        finalize_resp = await self._rnet.post(
            "https://upload.twitter.com/1.1/media/upload.json",
            headers={
                **self._base_headers,
                "content-type": "application/x-www-form-urlencoded",
            },
            data=finalize_data,
        )
        if finalize_resp.status not in (200, 202, 204):
            text = await finalize_resp.text()
            raise TwitterAPIError(finalize_resp.status, f"Media FINALIZE failed: {text[:300]}")

        # For videos, wait for processing
        if media_type == "video":
            import asyncio
            for _ in range(30):
                await asyncio.sleep(1)
                status_resp = await self._rnet.get(
                    f"https://upload.twitter.com/1.1/media/upload.json?command=STATUS&media_id={media_id}",
                    headers=self._base_headers,
                )
                if status_resp.status == 200:
                    status_json = json.loads(await status_resp.text())
                    state = status_json.get("processing_info", {}).get("state", "succeeded")
                    if state == "succeeded":
                        break
                    if state == "failed":
                        raise TwitterAPIError(500, f"Video processing failed: {status_json}")

        return media_id

    async def create_tweet(
        self,
        text: str,
        reply_to: str | None = None,
        media_ids: list[str] | None = None,
    ) -> dict:
        """Create a tweet or reply, optionally with media attachments."""
        media_entities = []
        if media_ids:
            media_entities = [
                {"media_id": mid, "tagged_users": []} for mid in media_ids
            ]

        variables: dict = {
            "tweet_text": text,
            "dark_request": False,
            "media": {
                "media_entities": media_entities,
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
