#!/usr/bin/env python3
"""Pain Mining Engine — search Twitter for real customer pain signals.

Usage:
    from pain_miner import PainMiner
    miner = PainMiner(client)
    results = await miner.mine("CRM software", limit=200)
    # Returns ranked list of {tweet, signals, score, wtp_level}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ── Pain signal definitions ──────────────────────────────────────────────

# Tier 1: strongest WTP signals — people actively spending or paying
TIER_1_PATTERNS = [
    (r"\b(?:pay|paying|paid)\s+(?:\$\d+|\d+\s*(?:bucks|dollars?|USD|GBP|EUR))", "explicit_spend", 10),
    (r"\b(?:costs?|costing)\s+(?:me|us)\s+(?:\$\d+|\d+\s*(?:bucks|dollars?))", "cost_complaint", 10),
    (r"\b(?:cancel|cancelled|canceling)\s+(?:my|our)\s+(?:subscription|account|plan)", "cancelled", 10),
    (r"\b(?:switched|switching|moved|migrated)\s+(?:from|away\s+from)", "switched", 9),
    (r"\b(?:refund|chargeback|dispute)\b", "refund_sought", 9),
    (r"\b(?:billed|charged)\s+(?:me|us)\s+(?:\$\d+|\d+\s*(?:bucks|dollars?))", "billed_complaint", 9),
    (r"\b(?:waste|wasted|wasting)\s+(?:money|cash|dollars?|\$\d+)", "wasted_money", 9),
]

# Tier 2: strong pain + looking for alternatives
TIER_2_PATTERNS = [
    (r"\b(?:looking\s+for|seeking|need|want|anyone\s+know)\s+(?:an?\s+)?(?:alternative|replacement|substitute)", "seeking_alternative", 8),
    (r"\b(?:alternative|replacement)\s+(?:to|for)\b", "alternative_to", 8),
    (r"\b(?:I\s+(?:hate|despise|can't\s+stand))\b", "hate_signal", 8),
    (r"\b(?:so\s+(?:expensive|pricey|overpriced))\b", "price_complaint", 8),
    (r"\b(?:too\s+(?:expensive|pricey|costly|much))\b", "too_expensive", 8),
    (r"\b(?:rip.?off|scam|waste\s+of\s+money)\b", "rip_off", 8),
    (r"\b(?:I\s+(?:would|wouldn't|won't|will\s+not)\s+pay)\b", "wtp_negative", 7),
    (r"\b(?:I(?:'d|\s+would)\s+(?:pay|gladly\s+pay|happily\s+pay))\b", "wtp_positive", 9),
    (r"\b(?:anyone\s+(?:recommend|suggest|know\s+of))\b", "seeking_recommendation", 7),
    (r"\b(?:what\s+(?:do|are)\s+you\s+(?:guys|all|folks|people)\s+(?:use|using|recommend))\b", "community_ask", 7),
    (r"\b(?:best|favorite|go.?to)\s+(?:tool|app|software|platform|service)\s+(?:for|to)\b", "tool_request", 7),
    (r"\b(?:I\s+(?:wish|really\s+wish))\b", "wish_signal", 7),
    (r"\b(?:if\s+only|why\s+isn't\s+there|why\s+doesn't)\b", "gap_signal", 7),
]

# Tier 3: workaround behavior — people solving it themselves
TIER_3_PATTERNS = [
    (r"\b(?:built?|made?|coded?|hacked?|rigged?)\s+(?:my\s+own|a\s+custom|an?\s+internal)", "built_own", 6),
    (r"\b(?:spreadsheet|excel|google\s+sheets?|airtable)\b", "spreadsheet_workaround", 6),
    (r"\b(?:zapier|make|n8n|integromat|automate)\b", "automation_workaround", 5),
    (r"\b(?:manually|by\s+hand|copy.?paste|copypaste)\b", "manual_work", 5),
    (r"\b(?:hours?\s+(?:a|per|every)\s+(?:day|week|month))\b", "time_cost", 6),
    (r"\b(?:script|python|node\.?js|bash|automation)\s+(?:to|that|for)\b", "script_workaround", 6),
    (r"\b(?:workaround|hack|duct\s*tape|band.?aid)\b", "workaround", 5),
    (r"\b(?:I\s+(?:use|using|currently\s+use|currently\s+using))\s+(?:a\s+)?(?:spreadsheet|excel|sheets)\b", "current_spreadsheet", 6),
    (r"\b(?:I\s+have\s+to|forced\s+to|stuck)\b", "forced_behavior", 5),
    (r"\b(?:frustrating|annoying|driving\s+me\s+(?:crazy|nuts|insane|mad))\b", "frustration", 6),
]

ALL_PATTERNS = TIER_1_PATTERNS + TIER_2_PATTERNS + TIER_3_PATTERNS

# ── Pain query templates ─────────────────────────────────────────────────

PAIN_QUERIES = [
    '"{keyword}" "too expensive"',
    '"{keyword}" alternative -filter:replies',
    '"{keyword}" "looking for" -filter:replies',
    '"hate" "{keyword}" -filter:replies',
    '"{keyword}" "anyone recommend" -filter:replies',
    '"{keyword}" "what do you use" -filter:replies',
    '"{keyword}" switched from -filter:replies',
    '"{keyword}" "waste of money"',
    '"{keyword}" spreadsheet -filter:replies',
    '"{keyword}" cancelled -filter:replies',
    '"{keyword}" "I wish" -filter:replies',
    '"{keyword}" overpriced -filter:replies',
    '"{keyword}" "rip off"',
    '"{keyword}" "why is there no" -filter:replies',
    '"{keyword}" "built my own" -filter:replies',
    '"{keyword}" "so annoying" -filter:replies',
    '"{keyword}" "drives me crazy" -filter:replies',
    '"{keyword}" "there has to be" -filter:replies',
]


@dataclass
class PainResult:
    """A single tweet scored for pain signals."""
    tweet: dict
    signals: list[str] = field(default_factory=list)
    score: int = 0
    wtp_level: int = 0  # 1=strong, 2=moderate, 3=weak

    @property
    def signal_summary(self) -> str:
        return ", ".join(self.signals) if self.signals else "none"


class PainMiner:
    """Mine Twitter for real customer pain around a keyword/product category."""

    def __init__(self, client):
        self.client = client

    async def mine(
        self,
        keyword: str,
        limit: int = 200,
        min_score: int = 5,
        extra_queries: list[str] | None = None,
        search_filters: dict | None = None,
    ) -> list[PainResult]:
        """Run the full pain mining pipeline.

        Args:
            keyword: Product/category to mine (e.g. "CRM", "project management")
            limit: Max total tweets to return
            min_score: Minimum pain score to include in results
            extra_queries: Additional custom search queries
            search_filters: Dict of search filters to pass through
                (lang, min_faves, min_retweets, min_followers, location, since, until)

        Returns:
            Ranked list of PainResult objects, highest score first.
        """
        queries = [q.format(keyword=keyword) for q in PAIN_QUERIES]
        if extra_queries:
            queries.extend(q.format(keyword=keyword) for q in extra_queries)

        all_tweets: dict[str, dict] = {}  # tweet_id -> tweet
        all_signals: dict[str, list[str]] = {}  # tweet_id -> signals

        # Build search kwargs from filters
        search_kwargs: dict = {"product": "Latest"}
        if search_filters:
            for key in ("lang", "since", "until", "location"):
                if key in search_filters:
                    search_kwargs[key] = search_filters[key]
            for key in ("min_faves", "min_retweets", "min_followers"):
                if key in search_filters:
                    search_kwargs[key] = int(search_filters[key])

        for query in queries[:10]:  # Limit queries to avoid rate limits
            try:
                tweets = await self.client.search_tweets(
                    query=query, count=min(50, limit), **search_kwargs,
                )
            except Exception:
                continue

            for tweet in tweets:
                tid = tweet.get("id", "")
                if tid not in all_tweets:
                    all_tweets[tid] = tweet
                    all_signals[tid] = []

                text = tweet.get("text", "")
                for pattern, signal_name, weight in ALL_PATTERNS:
                    if re.search(pattern, text, re.IGNORECASE):
                        if signal_name not in all_signals[tid]:
                            all_signals[tid].append(signal_name)

        # Score and rank
        results = []
        for tid, tweet in all_tweets.items():
            signals = all_signals.get(tid, [])
            score = self._calculate_score(signals)
            wtp = self._wtp_level(signals)

            if score >= min_score:
                results.append(PainResult(
                    tweet=tweet,
                    signals=signals,
                    score=score,
                    wtp_level=wtp,
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _calculate_score(self, signals: list[str]) -> int:
        """Calculate composite pain score from signal list."""
        signal_weights = {}
        for pattern, name, weight in ALL_PATTERNS:
            if name not in signal_weights:
                signal_weights[name] = weight

        # Base: sum of unique signal weights
        unique = set(signals)
        base = sum(signal_weights.get(s, 0) for s in unique)

        # Bonus: multiple signal types = stronger pain
        if len(unique) >= 4:
            base += 5
        elif len(unique) >= 2:
            base += 2

        # Bonus: Tier 1 signals are gold
        t1_signals = [
            "explicit_spend", "cost_complaint", "cancelled", "switched",
            "refund_sought", "billed_complaint", "wasted_money",
        ]
        t1_count = sum(1 for s in unique if s in t1_signals)
        base += t1_count * 3

        return base

    def _wtp_level(self, signals: list[str]) -> int:
        """Classify willingness-to-pay evidence level."""
        unique = set(signals)
        t1 = {"explicit_spend", "cost_complaint", "cancelled", "switched",
              "refund_sought", "billed_complaint", "wasted_money", "wtp_positive"}
        t2 = {"seeking_alternative", "alternative_to", "hate_signal",
              "price_complaint", "too_expensive", "rip_off", "seeking_recommendation",
              "community_ask", "tool_request", "wish_signal", "gap_signal"}
        if unique & t1:
            return 1
        if unique & t2:
            return 2
        return 3

    def format_report(self, results: list[PainResult], top_n: int = 20) -> str:
        """Generate a human-readable pain mining report."""
        lines = [
            f"PAIN MINING REPORT — {len(results)} results",
            "=" * 60,
            "",
        ]
        t1 = [r for r in results if r.wtp_level == 1]
        t2 = [r for r in results if r.wtp_level == 2]
        t3 = [r for r in results if r.wtp_level == 3]

        lines.append(f"Tier 1 (strong WTP evidence): {len(t1)}")
        lines.append(f"Tier 2 (seeking alternatives):  {len(t2)}")
        lines.append(f"Tier 3 (workaround behavior):  {len(t3)}")
        lines.append("")

        for i, r in enumerate(results[:top_n], 1):
            t = r.tweet
            wtp_label = {1: "💰💰💰", 2: "💰💰", 3: "💰"}.get(r.wtp_level, "💰")
            lines.append(f"#{i} {wtp_label} Score: {r.score} | Signals: {r.signal_summary}")
            lines.append(f"   @{t.get('author', '?')}: {t.get('text', '')[:200]}")
            lines.append(f"   ❤️ {t.get('favorite_count', 0):,} 🔁 {t.get('retweet_count', 0):,} 👁 {t.get('views', 0):,}")
            lines.append(f"   {t.get('url', '')}")
            lines.append("")

        return "\n".join(lines)
