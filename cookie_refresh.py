#!/usr/bin/env python3
"""
Automatic cookie refresh for Twitter/X using Playwright.

This module handles automatic re-authentication when cookies expire.
It uses Playwright to launch a headless browser, log in, and extract fresh cookies.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Config file for credentials (NOT in git)
CONFIG_PATH = Path(__file__).parent / ".twitter_config.json"
COOKIES_PATH = Path(__file__).parent / "twitter_cookies.json"


class CookieRefreshError(Exception):
    """Raised when cookie refresh fails."""
    pass


def load_credentials() -> tuple[str, str]:
    """Load Twitter credentials from config file.

    Config file format (JSON):
    {
        "username": "your_username",
        "password": "your_password",
        "email": "optional@email.com"  // For 2FA/verification
    }
    """
    if not CONFIG_PATH.exists():
        raise CookieRefreshError(
            f"Credentials file not found: {CONFIG_PATH}\n"
            "Create it with:\n"
            '{"username": "your_handle", "password": "your_pass", "email": "your@email.com"}'
        )

    config = json.loads(CONFIG_PATH.read_text())
    username = config.get("username")
    password = config.get("password")

    if not username or not password:
        raise CookieRefreshError("Config must contain 'username' and 'password'")

    return username, password, config.get("email")


async def refresh_cookies(
    headless: bool = True,
    timeout: int = 60
) -> list[dict]:
    """
    Refresh Twitter cookies using Playwright browser automation.

    Args:
        headless: Run browser in headless mode (no GUI)
        timeout: Maximum time to wait for login (seconds)

    Returns:
        List of cookie dicts with 'name' and 'value' keys

    Raises:
        CookieRefreshError: If login fails or cookies can't be extracted
    """
    try:
        from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        raise CookieRefreshError("Playwright not installed. Run: pip install playwright")

    username, password, email = load_credentials()

    print(f"[CookieRefresh] Starting browser for @{username}...")

    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )

        page = await context.new_page()

        try:
            # Go to login page
            print("[CookieRefresh] Navigating to login...")
            await page.goto("https://x.com/i/flow/login", wait_until="networkidle")

            # Wait for and fill username
            print("[CookieRefresh] Entering username...")
            await page.wait_for_selector('input[autocomplete="username"]', timeout=timeout*1000)
            await page.fill('input[autocomplete="username"]', username)

            # Click Next
            await page.click('//span[text()="Next" or text()="Next"]/ancestor::button')

            # Wait for password field
            print("[CookieRefresh] Entering password...")
            await page.wait_for_selector('input[name="password"]', timeout=timeout*1000)
            await page.fill('input[name="password"]', password)

            # Click Log in
            await page.click('//span[text()="Log in" or text()="Log in"]/ancestor::button')

            # Wait for home page or verification challenge
            print("[CookieRefresh] Waiting for login completion...")

            try:
                # Wait for home timeline (indicates success)
                await page.wait_for_selector('[data-testid="primaryColumn"]', timeout=timeout*1000)
                print("[CookieRefresh] Login successful!")
            except PlaywrightTimeout:
                # Check if there's a verification challenge
                if await page.query_selector('input[data-testid="ocfEnterTextTextInput"]'):
                    if email:
                        print(f"[CookieRefresh] Verification required. Using email: {email}")
                        await page.fill('input[data-testid="ocfEnterTextTextInput"]', email)
                        await page.click('//span[text()="Next"]/ancestor::button')
                        await page.wait_for_selector('[data-testid="primaryColumn"]', timeout=timeout*1000)
                    else:
                        raise CookieRefreshError(
                            "Verification required but no email in config. "
                            "Add 'email' to .twitter_config.json"
                        )
                else:
                    raise CookieRefreshError("Login failed - unknown error")

            # Navigate to get all cookies
            await page.goto("https://x.com", wait_until="networkidle")
            await asyncio.sleep(2)  # Wait for cookies to settle

            # Extract cookies
            cookies = await context.cookies()

            # Filter to just auth_token and ct0
            auth_cookies = [
                {"name": c["name"], "value": c["value"]}
                for c in cookies
                if c["name"] in ["auth_token", "ct0"]
            ]

            if not auth_cookies:
                raise CookieRefreshError("No auth cookies found after login")

            # Verify we have both
            cookie_names = {c["name"] for c in auth_cookies}
            if "auth_token" not in cookie_names:
                raise CookieRefreshError("auth_token cookie not found")
            if "ct0" not in cookie_names:
                raise CookieRefreshError("ct0 cookie not found")

            print(f"[CookieRefresh] Successfully extracted {len(auth_cookies)} cookies")

            # Save to file
            COOKIES_PATH.write_text(json.dumps(auth_cookies, indent=2))
            print(f"[CookieRefresh] Cookies saved to {COOKIES_PATH}")

            return auth_cookies

        except PlaywrightTimeout as e:
            # Take screenshot for debugging
            screenshot_path = Path(__file__).parent / "login_error.png"
            await page.screenshot(path=str(screenshot_path))
            raise CookieRefreshError(f"Timeout during login. Screenshot saved to {screenshot_path}")

        except Exception as e:
            raise CookieRefreshError(f"Login failed: {e}")

        finally:
            await browser.close()


def refresh_cookies_sync(headless: bool = True) -> list[dict]:
    """Synchronous wrapper for refresh_cookies."""
    return asyncio.run(refresh_cookies(headless=headless))


def needs_refresh() -> bool:
    """Check if cookies need refresh (file missing or empty)."""
    if not COOKIES_PATH.exists():
        return True

    try:
        cookies = json.loads(COOKIES_PATH.read_text())
        if not cookies:
            return True
        cookie_names = {c.get("name") for c in cookies}
        return "auth_token" not in cookie_names or "ct0" not in cookie_names
    except:
        return True


async def test_cookies(cookies_path: str = None) -> bool:
    """
    Test if current cookies are valid by making a simple API call.

    Returns:
        True if cookies work, False if they need refresh
    """
    from rnet_twitter import RnetTwitterClient, TwitterAPIError

    path = cookies_path or str(COOKIES_PATH)
    if not Path(path).exists():
        return False

    client = RnetTwitterClient()
    try:
        client.load_cookies(path)
        # Try to get a well-known user (Twitter's own account)
        await client.get_user_by_screen_name("twitter")
        return True
    except TwitterAPIError as e:
        if e.status in [403, 401]:
            return False
        raise


if __name__ == "__main__":
    """CLI usage: python cookie_refresh.py"""
    import argparse

    parser = argparse.ArgumentParser(description="Refresh Twitter cookies")
    parser.add_argument("--visible", "-v", action="store_true", help="Show browser window")
    parser.add_argument("--test", "-t", action="store_true", help="Test current cookies")
    args = parser.parse_args()

    if args.test:
        print("Testing current cookies...")
        valid = asyncio.run(test_cookies())
        print(f"Cookies valid: {valid}")
        sys.exit(0 if valid else 1)

    try:
        cookies = asyncio.run(refresh_cookies(headless=not args.visible))
        print(f"\nSuccess! Got {len(cookies)} cookies")
        for c in cookies:
            print(f"  - {c['name']}: {'*' * 20}...")
    except CookieRefreshError as e:
        print(f"\nFailed: {e}", file=sys.stderr)
        sys.exit(1)
