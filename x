#!/usr/bin/env python3
"""x — Twitter Scraper CLI v4 — your weapon on the bird app.

      ██╗  ██╗
      ╚██╗██╔╝
       ╚███╔╝ 
       ██╔██╗ 
      ██╔╝ ██╗
      ╚═╝  ╚═╝
      
  talk to the bird. scrape the bird. mine pain from the bird.
  no API keys. no cloud. just your chrome session.
"""

import json, os, sys, urllib.request, urllib.error, shutil, argparse

HOST = os.environ.get("TWITTER_SCRAPE_HOST", "127.0.0.1")
PORT = os.environ.get("TWITTER_SCRAPE_PORT", "8765")
BASE = "http://" + HOST + ":" + str(PORT)

# ── ANSI colour helpers ─────────────────────────────────────────────
BOLD = "\033[1m"; DIM = "\033[2m"; RED = "\033[31m"; GREEN = "\033[32m"
YELLOW = "\033[33m"; BLUE = "\033[34m"; CYAN = "\033[36m"; MAGENTA = "\033[35m"
WHITE = "\033[37m"; RESET = "\033[0m"

def b(s):    return BOLD + s + RESET
def d(s):     return DIM + s + RESET
def g(s):   return GREEN + s + RESET
def r(s):     return RED + s + RESET
def y(s):  return YELLOW + s + RESET
def bl(s):    return BLUE + s + RESET
def c(s):    return CYAN + s + RESET
def m(s): return MAGENTA + s + RESET
def w(s):   return WHITE + s + RESET

def _tw(): return shutil.get_terminal_size().columns or 80
def _hr(ch="─"): return d(ch * _tw())
def _icon(e): return "  " + e + "  "
def _hdr(t): return b(m("  " + t))
def _lbl(t): return d("  " + t)
def _ok(): return g(" ✓")
def _bad(): return r(" ✗")
def _tag(t): return d("[" + t + "]")
def _num(n):
    if n >= 1000000: return str(round(n/1000000, 1)) + "M"
    if n >= 1000: return str(round(n/1000, 1)) + "K"
    return str(n)

def _eng(tw):
    parts = []
    for em, key in [("❤️","favorite_count"),("🔁","retweet_count"),("💬","reply_count"),("👁","views")]:
        v = tw.get(key, 0) or 0
        if v: parts.append(em + " " + _num(v))
    if parts: return d("  " + "  ".join(parts))
    return ""

def _url(tw):
    u = tw.get("url", "")
    if u: return d("  " + u)
    return ""

def _tl(tw):
    text = (tw.get("text", "") or "").replace("\n", " ")[:160]
    return "  " + text

def _badges(tw):
    """Render verification, media, location, follower count badges."""
    badges = []
    if tw.get("verified"):
        badges.append(bl("✓"))
    if tw.get("has_media"):
        badges.append(m("📷"))
    loc = tw.get("location", "")
    if loc:
        badges.append(d(loc[:20]))
    fc = tw.get("followers_count", 0)
    if fc:
        badges.append(d(_num(fc) + " followers"))
    if badges:
        return "  " + "  ".join(badges)
    return ""

# ── HTTP helpers ────────────────────────────────────────────────────

def _post(path, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(BASE + path, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read())
            msg = err.get("error", str(err))
        except:
            msg = str(e)
        return {"_error": True, "_status": e.code, "_message": msg}
    except urllib.error.URLError as e:
        return {"_error": True, "_status": 0, "_message": str(e.reason)}

def _get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return {"_error": True, "_status": 0, "_message": str(e.reason)}

def _check(result, label="request"):
    if result.get("_error"):
        code = result.get("_status", 0)
        msg = result.get("_message", "unknown")
        print()
        print(_icon("💀") + r(label + " failed"))
        print(_hr())
        if code == 0:
            print("  " + r("connection dead") + "  — " + msg)
            print()
            print(d("  is the server alive? try:"))
            print(c("    systemctl restart twitter-scraper"))
        elif code == 401:
            print("  " + y("not logged in") + "  — " + msg)
            print()
            print(d("  fix:  ") + c("x login"))
        else:
            print("  " + r("HTTP " + str(code)) + "  — " + msg)
        print(_hr())
        return True
    return False


# ── Shared search argument builder ───────────────────────────────────

def _add_search_args(parser):
    """Add common search filter flags to a subparser."""
    parser.add_argument("--lang", default=None, metavar="CODE",
        help="Language: en, zh, ja, ko, fr, de, es, ar, ru, pt, etc.")
    parser.add_argument("--product", default="Latest", choices=["Latest", "Top"],
        help="Sort order (default: Latest)")
    parser.add_argument("--min-likes", type=int, default=None, metavar="N",
        help="Minimum likes (Twitter-native filter)")
    parser.add_argument("--min-retweets", type=int, default=None, metavar="N",
        help="Minimum retweets (Twitter-native filter)")
    parser.add_argument("--min-followers", type=int, default=None, metavar="N",
        help="Minimum author follower count (post-filter)")
    parser.add_argument("--location", default=None, metavar="CITY",
        help="Filter by profile location (case-insensitive substring, post-filter)")
    parser.add_argument("--since", default=None, metavar="DATE",
        help="Start date: YYYY-MM-DD")
    parser.add_argument("--until", default=None, metavar="DATE",
        help="End date: YYYY-MM-DD")
    parser.add_argument("--verified", action="store_true",
        help="Only verified (blue) accounts")
    parser.add_argument("--media-only", action="store_true",
        help="Only tweets with images/video")
    parser.add_argument("--exclude-replies", action="store_true",
        help="Exclude reply tweets")
    parser.add_argument("--exclude-retweets", action="store_true",
        help="Exclude retweets")

def _search_payload(args):
    """Build search API payload dict from argparse namespace."""
    payload = {
        "query": args.query,
        "limit": getattr(args, "limit", 50),
        "product": getattr(args, "product", "Latest"),
    }
    for key in ("lang", "since", "until", "location"):
        v = getattr(args, key, None)
        if v is not None:
            payload[key] = v
    ml = getattr(args, "min_likes", None)
    if ml is not None:
        payload["min_faves"] = ml
    for key in ("min_retweets", "min_followers"):
        v = getattr(args, key.replace("-", "_"), None)
        if v is not None:
            payload[key] = v
    for key in ("exclude_replies", "exclude_retweets", "verified_only", "media_only"):
        v = getattr(args, key, False)
        if v:
            payload[key] = True
    return payload

def _print_filter_summary(args, is_pain=False):
    """Print active filters line."""
    filters = []
    if getattr(args, "lang", None):
        filters.append(f"lang={args.lang}")
    if getattr(args, "min_likes", None):
        filters.append(f"≥{args.min_likes}❤️")
    if getattr(args, "min_retweets", None):
        filters.append(f"≥{args.min_retweets}🔁")
    if getattr(args, "min_followers", None):
        filters.append(f"≥{args.min_followers} followers")
    if getattr(args, "location", None):
        filters.append(f"📍{args.location}")
    if getattr(args, "since", None):
        filters.append(f"since={args.since}")
    if getattr(args, "until", None):
        filters.append(f"until={args.until}")
    if not is_pain:
        if getattr(args, "verified", False):
            filters.append("verified only")
        if getattr(args, "media_only", False):
            filters.append("media only")
        if getattr(args, "exclude_replies", False):
            filters.append("no replies")
        if getattr(args, "exclude_retweets", False):
            filters.append("no RTs")
    if filters:
        print(d("  filters: " + " · ".join(filters)))


# ── Commands ────────────────────────────────────────────────────────

def cmd_status(args):
    data = _get("/health")
    if _check(data, "health"): return
    ver = data.get("version", "?")
    print()
    print(_hr("═"))
    print(_icon("🐦") + b("x") + "  " + d("—") + "  " + b("Twitter Scraper") + "  " + _tag("v" + ver))
    print(_hr("═"))
    print()
    print(_hdr("SERVER"))
    print(_lbl("endpoint") + "  " + data["endpoint"])
    print(_lbl("storage") + "   ~/Twitter-scraper/storage/twitter/")
    print()
    print(_hdr("CHROME"))
    ok = data["chrome_running"]
    print(_lbl("debug port") + "  " + str(data["chrome_debug_port"]) + "  " + (_ok() if ok else _bad()))
    print()
    print(_hdr("AUTH"))
    auth = data["has_auth_token"] and data["has_ct0"]
    print(_lbl("cookies") + "    " + str(data["cookies_cached"]) + " cached")
    print(_lbl("auth_token") + "  " + (_ok() if data["has_auth_token"] else _bad()))
    print(_lbl("ct0") + "        " + (_ok() if data["has_ct0"] else _bad()))
    print()
    if auth:
        print("  " + g("ready") + "  —  " + d("you are logged in and ready to post, search, and mine"))
    else:
        print("  " + r("not logged in") + "  —  " + d("run") + " " + c("x login") + " " + d("to authenticate"))
    print()
    print(_hr("═"))


def cmd_user(args):
    username = args.username
    limit = args.limit if args.limit is not None else args.limit_flag
    if limit > 200: limit = 200
    print()
    print(d("  scraping @" + username + " ..."))
    result = _post("/user", {"username": username, "limit": limit})
    if _check(result, "user @" + username): return
    p = result.get("profile", {})
    tweets = result.get("tweets", [])
    print(_hr("═"))
    uname = p.get("username", username)
    name = p.get("name", "")
    print(_icon("👤") + b("@" + uname) + "  " + d("—") + "  " + name)
    print(_hr("═"))
    stats = []
    fc = p.get("followers_count", 0)
    if fc: stats.append(b(_num(fc)) + " " + d("followers"))
    fg = p.get("following_count", 0)
    if fg: stats.append(b(_num(fg)) + " " + d("following"))
    tc = p.get("tweets_count", 0)
    if tc: stats.append(b(_num(tc)) + " " + d("tweets"))
    if stats:
        print()
        print("  " + "  ╱  ".join(stats))
        print()
    bio = p.get("bio", "")
    if bio:
        print("  " + d(bio[:200]))
        print()
    if p.get("verified"):
        print("  " + bl("✓ verified"))
    loc = p.get("location", "")
    if loc:
        print("  " + d("📍 " + loc))
    print("  " + d("joined " + str(p.get("created_at", "?"))))
    print()
    print(_hdr("TWEETS  (" + str(len(tweets)) + " scraped)"))
    print(_hr())
    for t in tweets:
        print()
        author = t.get("author", "?")
        created = t.get("created_at", "")
        print("  " + b("@" + author) + "  " + d(created))
        print(_tl(t))
        eng = _eng(t).strip()
        if eng: print(eng)
        bd = _badges(t).strip()
        if bd: print(bd)
        u = _url(t).strip()
        if u: print(u)
    print()
    print(_hr("═"))
    print("  " + d("saved to") + "  " + result.get("path", "?"))


def cmd_search(args):
    # Positional shorthand takes priority, then --limit flag, then default 50
    limit = args.limit if args.limit is not None else args.limit_flag
    if limit > 100: limit = 100
    args.limit = limit
    payload = _search_payload(args)
    print()
    print(d("  searching: \"" + args.query + "\" ..."))
    _print_filter_summary(args)
    result = _post("/search", payload)
    if _check(result, "search"): return
    tweets = result.get("tweets", [])
    print(_hr("═"))
    cnt = "(" + str(len(tweets)) + " results)"
    print(_icon("🔍") + b("search") + "  " + d("—") + "  " + c('"' + args.query + '"') + "  " + d(cnt))
    print(_hr("═"))
    if not tweets:
        print()
        print("  " + d("nothing found. try broader terms or drop filters."))
    else:
        for t in tweets:
            print()
            a = t.get("author", "?")
            n = t.get("display_name", "")
            lbl = "@" + a
            if n and n != a:
                lbl += " (" + n + ")"
            print("  " + b(lbl))
            print(_tl(t))
            eng = _eng(t).strip()
            if eng: print(eng)
            bd = _badges(t).strip()
            if bd: print(bd)
            u = _url(t).strip()
            if u: print(u)
    print()
    print(_hr("═"))


def cmd_pain(args):
    limit = args.limit if args.limit is not None else args.limit_flag
    if limit > 200: limit = 200
    payload = {
        "keyword": args.keyword,
        "limit": limit,
        "min_score": args.min_score,
    }
    for key in ("lang", "since", "until", "location"):
        v = getattr(args, key, None)
        if v is not None:
            payload[key] = v
    ml = getattr(args, "min_likes", None)
    if ml is not None:
        payload["min_faves"] = ml
    for key in ("min_retweets", "min_followers"):
        v = getattr(args, key.replace("-", "_"), None)
        if v is not None:
            payload[key] = v

    print()
    print(d("  mining pain for: \"" + args.keyword + "\" ..."))
    _print_filter_summary(args, is_pain=True)
    result = _post("/pain", payload)
    if _check(result, "pain '" + args.keyword + "'"): return
    results = result.get("results", [])
    wtp_map = {1: "💰💰💰", 2: "💰💰", 3: "💰"}
    print(_hr("═"))
    cnt = "(" + str(len(results)) + " signals)"
    print(_icon("⛏️") + b("pain mine") + "  " + d("—") + "  " + c('"' + args.keyword + '"') + "  " + d(cnt))
    print(_hr("═"))
    if not results:
        print()
        print("  " + d("no pain found. either nobody cares or try a broader keyword."))
    for i, pr in enumerate(results, 1):
        tw = pr["tweet"]
        wtp = wtp_map.get(pr.get("wtp_level", 3), "💰")
        sigs = ", ".join(pr.get("signals", [])[:4])
        print()
        print("  " + b("#" + str(i)) + "  " + wtp + "  " + b("Score: " + str(pr["score"])) + "  " + d("|") + "  " + d(sigs))
        print("  " + b("@" + tw.get("author", "?")))
        text = (tw.get("text", "") or "")[:200].replace("\n", " ")
        print("  " + text)
        eng = _eng(tw).strip()
        if eng: print(eng)
        bd = _badges(tw).strip()
        if bd: print(bd)
        u = _url(tw).strip()
        if u: print(u)
    print()
    print(_hr("═"))


def cmd_tweet(args):
    print()
    print(d("  posting ..."))
    result = _post("/tweet", {"text": args.text})
    if _check(result, "tweet"): return
    print()
    print(_icon("✅") + g("posted"))
    print("  " + c(result.get("url", "?")))
    print()


def cmd_tweet_media(args):
    print()
    print(d("  uploading " + args.file + " ..."))
    media = _post("/media", {"file_path": args.file, "media_type": "image"})
    if _check(media, "media upload"): return
    mid = media.get("media_id")
    if not mid:
        print()
        print("  " + r("upload returned no media_id"))
        print()
        sys.exit(1)
    print("  " + g("uploaded") + "  " + d(mid))
    print(d("  posting ..."))
    result = _post("/tweet", {"text": args.text, "media_ids": [mid]})
    if _check(result, "tweet with media"): return
    print()
    print(_icon("✅") + g("posted"))
    print("  " + c(result.get("url", "?")))
    print()


def cmd_reply(args):
    print()
    print(d("  replying to " + args.tweet_id + " ..."))
    result = _post("/tweet", {"text": args.text, "reply_to": args.tweet_id})
    if _check(result, "reply"): return
    print()
    print(_icon("💬") + g("replied"))
    print("  " + c(result.get("url", "?")))
    print()


def cmd_like(args):
    result = _post("/like", {"tweet_id": args.tweet_id})
    if _check(result, "like"): return
    print()
    print(_icon("❤️") + g("liked") + "  " + d(args.tweet_id))
    print()


def cmd_delete(args):
    print()
    print(d("  deleting ..."))
    result = _post("/delete", {"tweet_id": args.tweet_id})
    if _check(result, "delete"): return
    print()
    print(_icon("🗑️") + g("deleted") + "  " + d(args.tweet_id))
    print()


def cmd_login(args):
    print()
    print(d("  opening login flow in browser ..."))
    result = _post("/login", {})
    if _check(result, "login"): return
    if result.get("success"):
        print()
        print(_icon("🔑") + g("logged in") + "  —  " + str(result["cookies_count"]) + " cookies cached")
        print()
    else:
        print()
        print(_icon("💀") + r("login failed") + "  —  " + result.get("error", "unknown"))
        print()


def cmd_accounts(args):
    data = _get("/account/status")
    if _check(data, "accounts"): return
    print()
    print(_hdr("ACCOUNTS"))
    print(_hr())
    for a in data.get("accounts", []):
        mark = g("→") if a.get("is_current") else " "
        tts = ""
        if a.get("time_until_available"):
            tts = " " + d("(" + a["time_until_available"] + " left)")
        sc = r if a.get("status") == "rate_limited" else g
        print("  " + mark + " " + b(a["username"]) + "  " + sc("[" + a["status"] + "]") + tts)
    if not data.get("accounts"):
        print("  " + d("no accounts configured"))
    print()
    print(_hr("═"))


# ── Main parser ─────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="x",
        description="Twitter Scraper CLI — search, scrape, mine pain, post",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", title="commands")

    # status
    sub.add_parser("status", help="Health check — server, Chrome, auth")

    # user
    p = sub.add_parser("user", help="Scrape a profile + recent tweets")
    p.add_argument("username", help="Twitter handle without @ (e.g. elonmusk)")
    p.add_argument("limit", nargs="?", type=int, default=None,
                   help="Max tweets (positional shorthand)")
    p.add_argument("--limit", type=int, default=200, dest="limit_flag",
                   help="Max tweets (default: 200, max: 200)")

    # search — the big one
    p = sub.add_parser("search", help="Search tweets with full filters")
    p.add_argument("query", help="Search query (supports inline operators)")
    p.add_argument("limit", nargs="?", type=int, default=None,
                   help="Max results (positional shorthand, e.g. 'x search \"AI\" 20')")
    p.add_argument("--limit", type=int, default=50, dest="limit_flag",
                   help="Max results (default: 50, max: 100)")
    _add_search_args(p)

    # pain
    p = sub.add_parser("pain", help="Mine Twitter for customer pain signals")
    p.add_argument("keyword", help="Product, category, or competitor name")
    p.add_argument("limit", nargs="?", type=int, default=None,
                   help="Max results (positional shorthand)")
    p.add_argument("--limit", type=int, default=200, dest="limit_flag",
                   help="Max results (default: 200)")
    p.add_argument("--min-score", type=int, default=5,
                   help="Minimum pain score (default: 5)")
    p.add_argument("--lang", default=None, metavar="CODE",
                   help="Language filter: en, zh, ja, ko, fr, de, es, etc.")
    p.add_argument("--min-likes", type=int, default=None, metavar="N",
                   help="Minimum likes")
    p.add_argument("--min-retweets", type=int, default=None, metavar="N",
                   help="Minimum retweets")
    p.add_argument("--min-followers", type=int, default=None, metavar="N",
                   help="Minimum author follower count (post-filter)")
    p.add_argument("--location", default=None, metavar="CITY",
                   help="Filter by profile location (post-filter)")
    p.add_argument("--since", default=None, metavar="DATE",
                   help="Start date: YYYY-MM-DD")
    p.add_argument("--until", default=None, metavar="DATE",
                   help="End date: YYYY-MM-DD")

    # tweet
    p = sub.add_parser("tweet", help="Post a tweet")
    p.add_argument("text", help="Tweet text")

    # tweet-media
    p = sub.add_parser("tweet-media", help="Tweet with image or video")
    p.add_argument("text", help="Tweet text")
    p.add_argument("file", help="Path to image or video file")

    # reply
    p = sub.add_parser("reply", help="Reply to a tweet")
    p.add_argument("text", help="Reply text")
    p.add_argument("tweet_id", help="Tweet ID from URL (the long number)")

    # like
    p = sub.add_parser("like", help="Like a tweet by ID")
    p.add_argument("tweet_id", help="Tweet ID from URL")

    # delete
    p = sub.add_parser("delete", help="Delete your tweet by ID")
    p.add_argument("tweet_id", help="Tweet ID from URL")

    # login
    sub.add_parser("login", help="Re-authenticate via browser")

    # accounts
    sub.add_parser("accounts", help="Multi-account status")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "status":      cmd_status,
        "user":        cmd_user,
        "search":      cmd_search,
        "pain":        cmd_pain,
        "tweet":       cmd_tweet,
        "tweet-media": cmd_tweet_media,
        "reply":       cmd_reply,
        "like":        cmd_like,
        "delete":      cmd_delete,
        "login":       cmd_login,
        "accounts":    cmd_accounts,
    }

    func = dispatch.get(args.command)
    if func:
        func(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
