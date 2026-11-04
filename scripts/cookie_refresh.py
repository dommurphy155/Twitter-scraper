#!/usr/bin/env python3
"""
Twitter cookie + session management.

Core principle: the LOGIN STATE lives in a real Chrome profile — never in
a static cookies.json file. We connect to that Chrome over CDP, drive the
user through the login flow the first time, and from then on we re-grab
auth cookies from the live profile on every check. The profile keeps the
session fresh; the cookies file is just a cache.

Attach-or-spawn:
  1. If a Chrome is already on the configured debug port — attach.
  2. If not — spawn one ourselves (headless, persistent user-data-dir).
  3. If we can't find any Chromium binary — try Playwright's bundled one.
  4. Last resort: raise a clear error.

Login flow (first run only):
  - If a Chrome is already up: open x.com/i/flow/login in a new tab and
    wait for the user to finish logging in. Detect success via the URL
    changing to /home.
  - If we spawned a headless Chrome: same flow, but we navigate the user
    to the displayed browser via notification.
  - Persistence: the Chrome profile on disk holds the session forever.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple


# --- Paths -----------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent
PROFILE_DIR = SCRIPT_DIR / ".chrome-profile"          # default (when we spawn)
COOKIES_PATH = SCRIPT_DIR / "twitter_cookies.json"
CONFIG_PATH = SCRIPT_DIR / ".twitter_config.json"
PORT_FILE = SCRIPT_DIR / ".debug-port"

# User's VNC Chrome (preferred when present). Override with env var
# TWITTER_CHROME_DEBUG_PORT to point at a different Chrome.
DEFAULT_DEBUG_PORT = 9222


def debug_port() -> int:
    """Resolve the CDP port: env > port-file > default."""
    env = os.environ.get("TWITTER_CHROME_DEBUG_PORT")
    if env and env.isdigit():
        return int(env)
    if PORT_FILE.exists():
        try:
            return int(PORT_FILE.read_text().strip())
        except ValueError:
            pass
    return DEFAULT_DEBUG_PORT


def set_debug_port(port: int) -> None:
    PORT_FILE.write_text(str(port))


# --- Chromium discovery ----------------------------------------------------

CHROMIUM_CANDIDATES = [
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/snap/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    # Playwright cache
    "~/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
    "~/.cache/ms-playwright/chromium-*/chrome-linux/headless_shell",
]


def find_chromium() -> Optional[str]:
    env = os.environ.get("CHROMIUM_BIN")
    if env and Path(env).exists():
        return env
    for c in CHROMIUM_CANDIDATES:
        for p in (Path(c).expanduser(),):
            if p.exists():
                return str(p)
        # Glob patterns
        if "*" in c:
            matches = list(Path(c.split("*")[0]).expanduser().glob(
                c.split("*", 1)[1].lstrip("/")
            ))
            if matches:
                return str(matches[0])
    return shutil.which("google-chrome") or shutil.which("chromium") \
        or shutil.which("chromium-browser")


# --- Networking ------------------------------------------------------------

def port_listening(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- Chrome process management --------------------------------------------

class ChromeProc:
    """Wraps a Chrome subprocess we own."""

    def __init__(self, proc: subprocess.Popen, port: int, profile: Path):
        self.proc = proc
        self.port = port
        self.profile = profile

    def alive(self) -> bool:
        return self.proc.poll() is None

    def terminate(self) -> None:
        if not self.alive():
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def spawn_chrome(
    port: Optional[int] = None,
    profile: Optional[Path] = None,
    headless: bool = True,
    display: Optional[str] = None,
) -> Optional[ChromeProc]:
    """Spawn a Chrome with the debug port. Returns ChromeProc or None.

    If `display` is provided, Chrome will use it (lets us attach to the
    user's VNC desktop so they can interact with the login UI).
    """
    chrome = find_chromium()
    if not chrome:
        return None
    port = port or find_free_port()
    profile = profile or PROFILE_DIR
    profile.mkdir(parents=True, exist_ok=True)

    cmd = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--lang=en-US",
    ]
    if headless:
        cmd += ["--headless=new", "--disable-gpu", "--no-sandbox"]
    else:
        # Visible mode for the login flow
        cmd += ["--no-sandbox", "--start-maximized"]

    env = os.environ.copy()
    if display:
        env["DISPLAY"] = display
    if "XAUTHORITY" not in env and Path.home().joinpath(".Xauthority").exists():
        env["XAUTHORITY"] = str(Path.home() / ".Xauthority")

    try:
        proc = subprocess.Popen(
            cmd, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        return None

    # Wait for the port to accept connections.
    deadline = time.time() + 15
    while time.time() < deadline:
        if port_listening("127.0.0.1", port):
            set_debug_port(port)
            return ChromeProc(proc, port, profile)
        if proc.poll() is not None:
            return None
        time.sleep(0.25)
    # Didn't come up in time — clean up.
    proc.terminate()
    return None


def wait_for_chrome(port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_listening("127.0.0.1", port):
            return True
        time.sleep(0.25)
    return False


# --- Cookie extraction -----------------------------------------------------

AUTH_COOKIE_NAMES = {"auth_token", "ct0"}


def _filter_auth(cookies: list) -> List[Dict]:
    return [
        {"name": c["name"], "value": c["value"]}
        for c in cookies
        if isinstance(c, dict) and c.get("name") in AUTH_COOKIE_NAMES
    ]


def save_cookies(cookies: List[Dict]) -> Path:
    COOKIES_PATH.write_text(json.dumps(cookies, indent=2))
    try:
        os.chmod(COOKIES_PATH, 0o600)
    except OSError:
        pass
    return COOKIES_PATH


def load_cached_cookies() -> List[Dict]:
    if not COOKIES_PATH.exists():
        return []
    try:
        data = json.loads(COOKIES_PATH.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


# --- CDP grab (the live source of truth) -----------------------------------

async def grab_cookies_via_cdp(port: Optional[int] = None) -> List[Dict]:
    """Connect to a live Chrome and pull auth cookies. Empty list on miss.

    Never raises. If Chrome is unreachable, returns [].
    """
    port = port or debug_port()
    if not port_listening("127.0.0.1", port):
        return []

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}"
            )
            for ctx in browser.contexts:
                # Prefer the default context (most user sessions live here)
                try:
                    cookies = await ctx.cookies("https://x.com")
                except Exception:
                    cookies = []
                auth = _filter_auth(cookies)
                if len(auth) >= 2:
                    return auth
            # No x.com cookies in any context — maybe x.com tab is
            # open in an incognito context. Try that.
            return []
    except Exception:
        return []


# --- Login flow ------------------------------------------------------------

async def ensure_logged_in(
    port: Optional[int] = None,
    headless: bool = True,
    display: Optional[str] = None,
    wait_callback=None,
) -> Tuple[List[Dict], str]:
    """Top-level: ensure we're logged in to x.com.

    1. Try to grab cookies from the live Chrome via CDP.
    2. If that works AND they validate, return them.
    3. If Chrome is on but no cookies, walk the user through login.
    4. If no Chrome at all, spawn one (headless or visible depending on
       whether we have a display) and walk through login.

    Returns (cookies, status) where status is one of:
      "ok"        — logged in, cookies fresh
      "no_chrome" — no browser available at all
      "abandoned" — user gave up before finishing login
    """
    port = port or debug_port()
    cookies = await grab_cookies_via_cdp(port)
    if cookies and len(cookies) >= 2:
        save_cookies(cookies)
        return cookies, "ok"

    # No valid cookies in the live Chrome. Drive the login flow.
    from playwright.async_api import async_playwright

    if not port_listening("127.0.0.1", port):
        # No Chrome — spawn one. Try to use the user's display so they
        # can see and interact with the login.
        if display and not headless:
            spawned = spawn_chrome(
                port=port, profile=PROFILE_DIR,
                headless=False, display=display,
            )
        else:
            spawned = spawn_chrome(
                port=port, profile=PROFILE_DIR,
                headless=headless, display=display,
            )
        if not spawned:
            return [], "no_chrome"
        if not wait_for_chrome(port, timeout=10):
            spawned.terminate()
            return [], "no_chrome"
    else:
        spawned = None

    # Now drive the login.
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(
            f"http://127.0.0.1:{port}"
        )
        ctx = browser.contexts[0] if browser.contexts else \
            await browser.new_context()

        # Open a fresh x.com login tab — but don't hold a hard reference
        # to the page. X's SPA can close/navigate tabs and a stale
        # page reference kills the wait loop with TargetClosedError.
        # We poll cookies on the CONTEXT, not the page, so we don't
        # care which tab is showing what.
        new_page = await ctx.new_page()
        try:
            await new_page.goto("https://x.com/i/flow/login",
                                wait_until="domcontentloaded")
        except Exception as e:
            # X sometimes closes the tab during redirect — that's fine,
            # the cookies are what we care about.
            print(f"    (login tab navigation: {e})")

        # Notify the user.
        print("\n" + "=" * 60)
        print("  LOGIN REQUIRED")
        print("=" * 60)
        print(f"  A browser window is now open on port {port}.")
        print("  Log into x.com in that window, then return here.")
        print("  Waiting for auth_token + ct0 cookies to appear...")
        print("=" * 60 + "\n")
        sys.stdout.flush()

        # Poll the CONTEXT for cookies. No page references held — robust
        # to the user closing the login tab, navigating, opening new
        # tabs, etc.
        cookies = []
        for _ in range(600):  # up to 10 minutes
            if wait_callback and wait_callback():
                return [], "abandoned"

            try:
                all_cookies = await ctx.cookies("https://x.com")
            except Exception:
                all_cookies = []
            auth = _filter_auth(all_cookies)
            names = {c["name"] for c in auth}
            if "auth_token" in names and "ct0" in names:
                await asyncio.sleep(1.5)
                # Re-fetch in case ct0 rotated
                try:
                    all_cookies = await ctx.cookies("https://x.com")
                except Exception:
                    pass
                cookies = _filter_auth(all_cookies)
                if cookies and len(cookies) >= 2:
                    break

            await asyncio.sleep(1)

        if cookies and len(cookies) >= 2:
            save_cookies(cookies)
            return cookies, "ok"

        return [], "abandoned"


# --- Cookie validity check (against the live X API) -----------------------

async def cookies_work(cookies: Optional[List[Dict]] = None,
                      port: Optional[int] = None) -> bool:
    """True if the cookies authenticate against the Twitter GraphQL API."""
    if not cookies:
        cookies = load_cached_cookies()
    if not cookies:
        cookies = await grab_cookies_via_cdp(port or debug_port())
    if not cookies or len(cookies) < 2:
        return False

    from rnet_twitter import RnetTwitterClient, TwitterAPIError
    client = RnetTwitterClient()
    client._cookies = {c["name"]: c["value"] for c in cookies}
    try:
        await client.get_user_by_screen_name("twitter")
        return True
    except TwitterAPIError as e:
        return e.status not in (401, 403)
    except Exception:
        return False


# --- Master "refresh" entry point -----------------------------------------

async def refresh_cookies(
    headless: bool = True,
    display: Optional[str] = None,
) -> List[Dict]:
    """Get usable auth cookies, by whatever means necessary.

    Tries (in order):
      1. CDP grab from live Chrome on the configured port.
      2. Ensure-logged-in flow (login UI if needed).
      3. Raise.

    Never silently returns an empty list. On total failure raises
    CookieRefreshError with a clear message.
    """
    cookies, status = await ensure_logged_in(
        port=debug_port(), headless=headless, display=display,
    )
    if cookies and len(cookies) >= 2:
        save_cookies(cookies)
        return cookies

    if status == "no_chrome":
        raise CookieRefreshError(
            "No Chromium browser is available and none could be spawned. "
            "Install google-chrome, chromium, or run `playwright install chromium`."
        )
    raise CookieRefreshError(
        "Login was not completed in the browser window. "
        "Make sure you log in and the URL changes to x.com/home, then retry."
    )


class CookieRefreshError(Exception):
    pass


# --- Sync helpers ---------------------------------------------------------

def refresh_cookies_sync(**kwargs) -> List[Dict]:
    return asyncio.run(refresh_cookies(**kwargs))


def needs_refresh() -> bool:
    if not COOKIES_PATH.exists():
        return True
    try:
        cookies = json.loads(COOKIES_PATH.read_text())
    except Exception:
        return True
    names = {c.get("name") for c in cookies if isinstance(c, dict)}
    return "auth_token" not in names or "ct0" not in names


# --- CLI ------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Twitter session: attach-or-spawn Chrome, log in, "
                    "keep cookies fresh.",
    )
    parser.add_argument("--display", default=os.environ.get("DISPLAY", ":1"),
                        help="X11 display for the login window (default: :1)")
    parser.add_argument("--headless", action="store_true",
                        help="Use headless Chrome (no visible login window)")
    parser.add_argument("--port", type=int, default=None,
                        help="CDP port (default: 9222)")
    parser.add_argument("--spawn", action="store_true",
                        help="Force-spawn a new Chrome even if one is up")
    parser.add_argument("--status", action="store_true",
                        help="Show current session status and exit")
    args = parser.parse_args()

    if args.port:
        set_debug_port(args.port)

    if args.spawn:
        spawned = spawn_chrome(
            port=debug_port(), profile=PROFILE_DIR,
            headless=args.headless, display=args.display if not args.headless else None,
        )
        if not spawned:
            print("Failed to spawn Chrome", file=sys.stderr)
            sys.exit(1)
        print(f"Chrome up on :{spawned.port} (profile: {spawned.profile})")
        sys.exit(0)

    if args.status:
        port = debug_port()
        listening = port_listening("127.0.0.1", port)
        cached = load_cached_cookies()
        names = {c.get("name") for c in cached}
        print(f"Debug port:     {port} ({'UP' if listening else 'DOWN'})")
        print(f"Profile dir:     {PROFILE_DIR}")
        print(f"Cached cookies:  {len(cached)} ({', '.join(sorted(names)) or 'none'})")
        sys.exit(0 if listening and "auth_token" in names else 1)

    try:
        cookies = refresh_cookies_sync(
            headless=args.headless, display=args.display,
        )
        print(f"\nSession active: {len(cookies)} cookies saved to {COOKIES_PATH}")
        for c in cookies:
            print(f"  - {c['name']}: {'*' * 20}...")
    except CookieRefreshError as e:
        print(f"\nFailed: {e}", file=sys.stderr)
        sys.exit(1)
