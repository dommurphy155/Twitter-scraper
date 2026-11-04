"""Account management for multi-account Grok CLI.

Handles:
- Loading account usernames from .env
- Tracking rate limit status per account
- Selecting next available account
- Persisting state across server restarts
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict

# Constants
STATE_FILE = Path(__file__).parent / "state" / "account_state.json"
ENV_FILE = Path(__file__).parent / ".env"
GROK_COOLDOWN_HOURS = 2


@dataclass
class Account:
    """Represents a Twitter/X account."""
    username: str
    rate_limited_at: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None

    def is_rate_limited(self) -> bool:
        """Check if account is currently rate limited."""
        if self.cooldown_until is None:
            return False
        return datetime.now() < self.cooldown_until

    def mark_rate_limited(self, cooldown_hours: int = GROK_COOLDOWN_HOURS):
        """Mark account as rate limited."""
        self.rate_limited_at = datetime.now()
        self.cooldown_until = datetime.now() + timedelta(hours=cooldown_hours)

    def time_until_available(self) -> Optional[timedelta]:
        """Return time until account is available again."""
        if self.cooldown_until is None:
            return None
        if datetime.now() >= self.cooldown_until:
            return timedelta(0)
        return self.cooldown_until - datetime.now()

    def reset_if_expired(self):
        """Reset rate limit status if cooldown has expired."""
        if self.cooldown_until and datetime.now() >= self.cooldown_until:
            self.rate_limited_at = None
            self.cooldown_until = None


class AccountManager:
    """Manages multiple Twitter/X accounts and their rate limit state."""

    def __init__(self):
        self.accounts: Dict[str, Account] = {}
        self.current_account: Optional[str] = None
        self._load_env()
        self._load_state()

    def _load_env(self):
        """Load account usernames from .env file."""
        if not ENV_FILE.exists():
            # Create empty accounts list if no .env
            return

        # Parse .env file
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ACCOUNT_") and "_USERNAME=" in line:
                    # Parse ACCOUNT_N_USERNAME=@username
                    try:
                        _, value = line.split("=", 1)
                        username = value.strip()
                        if username and not username.startswith("@your_"):
                            self.accounts[username] = Account(username=username)
                    except ValueError:
                        continue

        # Set first account as current if not set
        if self.accounts and not self.current_account:
            self.current_account = list(self.accounts.keys())[0]

    def _load_state(self):
        """Load rate limit state from JSON file."""
        if not STATE_FILE.exists():
            return

        try:
            with open(STATE_FILE) as f:
                data = json.load(f)

            # Update accounts with saved state
            for username, account_data in data.get("accounts", {}).items():
                if username in self.accounts:
                    account = self.accounts[username]
                    if account_data.get("rate_limited_at"):
                        account.rate_limited_at = datetime.fromisoformat(
                            account_data["rate_limited_at"]
                        )
                    if account_data.get("cooldown_until"):
                        account.cooldown_until = datetime.fromisoformat(
                            account_data["cooldown_until"]
                        )

            self.current_account = data.get("current_account", self.current_account)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[AccountManager] Warning: Could not load state: {e}")

    def save_state(self):
        """Save rate limit state to JSON file."""
        data = {
            "accounts": {},
            "current_account": self.current_account
        }

        for username, account in self.accounts.items():
            data["accounts"][username] = {
                "rate_limited_at": account.rate_limited_at.isoformat() if account.rate_limited_at else None,
                "cooldown_until": account.cooldown_until.isoformat() if account.cooldown_until else None
            }

        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def get_all_accounts(self) -> List[Account]:
        """Return list of all accounts."""
        return list(self.accounts.values())

    def get_available_accounts(self) -> List[Account]:
        """Return list of accounts not currently rate limited."""
        available = []
        for account in self.accounts.values():
            account.reset_if_expired()  # Clear expired rate limits
            if not account.is_rate_limited():
                available.append(account)
        return available

    def get_current_account(self) -> Optional[Account]:
        """Return the currently active account."""
        if not self.current_account:
            return None
        return self.accounts.get(self.current_account)

    def get_next_available_account(self, exclude: List[str] = None) -> Optional[Account]:
        """Get next available account, optionally excluding some.

        Strategy: Round-robin from current, skipping rate-limited accounts.
        """
        exclude = exclude or []
        available = self.get_available_accounts()

        # Filter out excluded accounts
        available = [a for a in available if a.username not in exclude]

        if not available:
            return None

        # Try to find next account in round-robin fashion
        if self.current_account and self.current_account in self.accounts:
            usernames = list(self.accounts.keys())
            current_idx = usernames.index(self.current_account)

            # Look for next available account
            for i in range(1, len(usernames) + 1):
                next_idx = (current_idx + i) % len(usernames)
                next_username = usernames[next_idx]
                if next_username not in exclude:
                    account = self.accounts.get(next_username)
                    if account and not account.is_rate_limited():
                        return account

        # Fallback to first available
        return available[0] if available else None

    def mark_account_rate_limited(self, username: str, cooldown_hours: int = GROK_COOLDOWN_HOURS):
        """Mark an account as rate limited."""
        if username in self.accounts:
            self.accounts[username].mark_rate_limited(cooldown_hours)
            self.save_state()

    def set_current_account(self, username: str):
        """Set the current active account."""
        if username in self.accounts:
            self.current_account = username
            self.save_state()

    def get_earliest_reset_time(self) -> Optional[datetime]:
        """Get the earliest time when any rate-limited account becomes available."""
        earliest = None
        for account in self.accounts.values():
            if account.is_rate_limited():
                if earliest is None or (account.cooldown_until and account.cooldown_until < earliest):
                    earliest = account.cooldown_until
        return earliest

    def format_status(self) -> str:
        """Format account status for display."""
        lines = ["Accounts:"]
        for username, account in self.accounts.items():
            marker = "❯" if username == self.current_account else " "
            if account.is_rate_limited():
                time_left = account.time_until_available()
                minutes = int(time_left.total_seconds() / 60) if time_left else 0
                lines.append(f"{marker} {username} [rate limited — {minutes} min remaining]")
            else:
                lines.append(f"{marker} {username} [active]")
        return "\n".join(lines)


# Global instance
_account_manager: Optional[AccountManager] = None


def get_account_manager() -> AccountManager:
    """Get or create the global account manager instance."""
    global _account_manager
    if _account_manager is None:
        _account_manager = AccountManager()
    return _account_manager


if __name__ == "__main__":
    # Test the module
    manager = get_account_manager()
    print(manager.format_status())
