#!/usr/bin/env python3
"""
Twitter/X Scraper Setup Wizard
Installs and configures the twitter_scrape skill with auto-cookie refresh.
"""

import os
import sys
import json
import subprocess
import time
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Tuple


class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_colored(text: str, color: str = ""):
    """Print colored text."""
    if color:
        print(f"{color}{text}{Colors.END}")
    else:
        print(text)


def print_step(step_num: int, total: int, description: str):
    """Print a step header."""
    print()
    print_colored(f"{'='*60}", Colors.CYAN)
    print_colored(f"  STEP {step_num}/{total}: {description}", Colors.BOLD + Colors.CYAN)
    print_colored(f"{'='*60}", Colors.CYAN)
    print()


def run_command(cmd: List[str], capture: bool = True, check: bool = True, sudo: bool = False, cwd: str = None) -> Tuple[int, str, str]:
    """Run a shell command and return exit code, stdout, stderr."""
    if sudo and os.geteuid() != 0:
        cmd = ['sudo'] + cmd

    try:
        if capture:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=cwd
            )
            return result.returncode, result.stdout, result.stderr
        else:
            result = subprocess.run(cmd, check=check, cwd=cwd)
            return result.returncode, "", ""
    except Exception as e:
        return 1, "", str(e)


def prompt_user(message: str, options: List[str] = None) -> str:
    """Prompt user for input with optional predefined options."""
    print()
    if options:
        print_colored(message, Colors.CYAN)
        for i, opt in enumerate(options, 1):
            print(f"  [{i}] {opt}")
        while True:
            choice = input(f"\nEnter choice (1-{len(options)}): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                return options[int(choice) - 1]
            print_colored("Invalid choice. Please try again.", Colors.WARNING)
    else:
        return input(f"{message} ").strip()


def confirm(message: str) -> bool:
    """Ask for yes/no confirmation."""
    while True:
        response = input(f"{message} (yes/no): ").strip().lower()
        if response in ('y', 'yes'):
            return True
        if response in ('n', 'no'):
            return False
        print("Please answer 'yes' or 'no'.")


def get_skill_dir() -> Path:
    """Get the twitter_scrape skill directory."""
    return Path.home() / ".openclaw" / "skills" / "twitter_scrape"


def get_venv_path() -> Path:
    """Get the Python virtual environment path."""
    return get_skill_dir() / "venv"


def get_venv_python() -> Path:
    """Get the Python executable path in the virtual environment."""
    venv = get_venv_path()
    if os.name == 'nt':
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def get_venv_pip() -> Path:
    """Get the pip executable path in the virtual environment."""
    venv = get_venv_path()
    if os.name == 'nt':
        return venv / "Scripts" / "pip.exe"
    return venv / "bin" / "pip"


def check_python_version() -> bool:
    """Check if Python 3.10+ is installed."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print_colored(f"Python 3.10+ required, found {version.major}.{version.minor}", Colors.FAIL)
        return False
    print_colored(f"Python {version.major}.{version.minor}.{version.micro} found", Colors.GREEN)
    return True


def check_venv_exists() -> bool:
    """Check if the virtual environment exists."""
    venv_path = get_venv_path()
    python = get_venv_python()
    if venv_path.exists() and python.exists():
        print_colored(f"Virtual environment found at {venv_path}", Colors.GREEN)
        return True
    return False


def create_venv():
    """Create Python virtual environment."""
    venv_path = get_venv_path()
    skill_dir = get_skill_dir()

    print(f"Creating virtual environment at {venv_path}...")
    code, out, err = run_command([sys.executable, "-m", "venv", str(venv_path)], check=True)
    if code != 0:
        print_colored(f"Failed to create venv: {err}", Colors.FAIL)
        sys.exit(1)
    print_colored("Virtual environment created", Colors.GREEN)


def install_dependencies():
    """Install required Python packages into venv."""
    pip = get_venv_pip()
    deps = ['rnet', 'playwright', 'httpx']

    print(f"Installing dependencies: {', '.join(deps)}")
    code, out, err = run_command([str(pip), 'install'] + deps, check=True)
    if code != 0:
        print_colored(f"Failed to install dependencies: {err}", Colors.FAIL)
        sys.exit(1)
    print_colored("Dependencies installed successfully", Colors.GREEN)


def install_playwright_chromium():
    """Install Playwright Chromium browser."""
    venv_python = get_venv_python()
    print("Installing Playwright Chromium browser...")
    print("(This may take a few minutes on first run)")

    code, out, err = run_command([str(venv_python), '-m', 'playwright', 'install', 'chromium'], check=False)
    if code != 0:
        print_colored(f"Warning: Playwright install had issues: {err}", Colors.WARNING)
        print_colored("The server will try to install on first run", Colors.WARNING)
    else:
        print_colored("Chromium browser installed", Colors.GREEN)


def get_current_user() -> str:
    """Get the current username."""
    return os.environ.get('SUDO_USER') or os.environ.get('USER') or os.environ.get('USERNAME') or 'root'


def collect_twitter_credentials() -> Dict[str, str]:
    """Collect Twitter/X credentials from user."""
    print_colored("\nTwitter/X credentials are needed for automatic cookie refresh.", Colors.BOLD)
    print_colored("Your credentials are stored locally and never committed to git.", Colors.CYAN)
    print()

    while True:
        username = input("Twitter/X username (without @): ").strip()
        if username:
            break
        print_colored("Username is required", Colors.WARNING)

    while True:
        password = input("Twitter/X password: ").strip()
        if password:
            break
        print_colored("Password is required", Colors.WARNING)

    email = input("Email (optional, used for 2FA/verification): ").strip()

    return {
        "username": username,
        "password": password,
        "email": email
    }


def write_twitter_config(credentials: Dict[str, str]):
    """Write Twitter credentials to config file."""
    skill_dir = get_skill_dir()
    config_path = skill_dir / ".twitter_config.json"

    # Only include non-empty email
    config = {
        "username": credentials["username"],
        "password": credentials["password"]
    }
    if credentials.get("email"):
        config["email"] = credentials["email"]

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    # Ensure permissions are restrictive
    os.chmod(config_path, 0o600)

    print_colored(f"Credentials saved to {config_path}", Colors.GREEN)


def check_twitter_config_exists() -> bool:
    """Check if Twitter config already exists."""
    skill_dir = get_skill_dir()
    config_path = skill_dir / ".twitter_config.json"
    return config_path.exists()


def read_twitter_config() -> Optional[Dict]:
    """Read existing Twitter config."""
    skill_dir = get_skill_dir()
    config_path = skill_dir / ".twitter_config.json"
    if not config_path.exists():
        return None
    try:
        with open(config_path) as f:
            return json.load(f)
    except:
        return None


def is_systemd_service_installed(service_name: str) -> bool:
    """Check if a systemd service is installed."""
    service_path = Path(f"/etc/systemd/system/{service_name}")
    return service_path.exists()


def is_systemd_service_active(service_name: str) -> bool:
    """Check if a systemd service is active."""
    code, out, _ = run_command(['systemctl', 'is-active', service_name], check=False)
    return code == 0 and 'active' in out


def install_systemd_service():
    """Create and install the twitter-scrape systemd service."""
    user = get_current_user()
    skill_dir = get_skill_dir()
    venv_python = get_venv_python()

    service_content = f"""[Unit]
Description=Twitter Scraper API Server with Auto Cookie Refresh
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={skill_dir}
Environment="TWITTER_COOKIES_PATH={skill_dir}/twitter_cookies.json"
Environment="TWITTER_SCRAPE_HOST=127.0.0.1"
Environment="TWITTER_SCRAPE_PORT=8765"
Environment="PLAYWRIGHT_BROWSERS_PATH=0"
ExecStart={venv_python} {skill_dir}/server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""

    # Write to temp file first
    temp_service = "/tmp/twitter-scrape.service"
    with open(temp_service, 'w') as f:
        f.write(service_content)

    # Copy to systemd
    service_path = "/etc/systemd/system/twitter-scrape.service"
    code, out, err = run_command(['cp', temp_service, service_path], sudo=True, check=True)
    if code != 0:
        print_colored(f"Failed to install service: {err}", Colors.FAIL)
        sys.exit(1)

    # Reload systemd
    run_command(['systemctl', 'daemon-reload'], sudo=True, check=True)

    # Enable service
    run_command(['systemctl', 'enable', 'twitter-scrape'], sudo=True, check=True)

    print_colored("Systemd service installed", Colors.GREEN)


def start_service():
    """Start the twitter-scrape service."""
    print("Starting twitter-scrape service...")

    # Stop any existing instance first
    run_command(['systemctl', 'stop', 'twitter-scrape'], sudo=True, check=False)
    time.sleep(1)

    # Start fresh
    code, out, err = run_command(['systemctl', 'start', 'twitter-scrape'], sudo=True, check=True)
    if code != 0:
        print_colored(f"Failed to start service: {err}", Colors.FAIL)
        return False

    # Wait for service to be ready
    time.sleep(3)

    # Check status
    code, out, err = run_command(['systemctl', 'is-active', 'twitter-scrape'], check=False)
    if code == 0 and 'active' in out:
        print_colored("Service is running", Colors.GREEN)
        return True
    else:
        print_colored("Service failed to start", Colors.FAIL)
        print_colored("Checking logs...", Colors.WARNING)
        run_command(['journalctl', '-u', 'twitter-scrape', '-n', '20', '--no-pager'], sudo=True, capture=False)
        return False


def create_x_symlink():
    """Create symlink for the `x` command in ~/.local/bin."""
    home = Path.home()
    local_bin = home / ".local" / "bin"
    x_script = get_skill_dir() / "x"
    x_link = local_bin / "x"

    # Create ~/.local/bin if it doesn't exist
    local_bin.mkdir(parents=True, exist_ok=True)

    # Remove existing symlink if it exists
    if x_link.is_symlink():
        x_link.unlink()

    # Create the symlink
    if x_script.exists():
        x_link.symlink_to(x_script)
        print_colored(f"Created 'x' command at {x_link}", Colors.GREEN)

        # Add to PATH if needed
        shell_profiles = [
            home / ".bashrc",
            home / ".zshrc",
            home / ".profile",
        ]

        path_export = '\n# Local bin\nexport PATH="$HOME/.local/bin:$PATH"\n'

        for profile in shell_profiles:
            if profile.exists():
                with open(profile, 'r') as f:
                    content = f.read()
                if '.local/bin' not in content:
                    with open(profile, 'a') as f:
                        f.write(path_export)

        # Add to current PATH
        os.environ['PATH'] = str(local_bin) + os.pathsep + os.environ.get('PATH', '')
    else:
        print_colored(f"Warning: x script not found at {x_script}", Colors.WARNING)


def check_x_symlink_exists() -> bool:
    """Check if the x symlink exists."""
    home = Path.home()
    x_link = home / ".local" / "bin" / "x"
    return x_link.exists()


def test_installation() -> bool:
    """Test the installation by checking server health."""
    print("Testing installation...")

    try:
        import urllib.request
        import json

        req = urllib.request.Request(
            "http://127.0.0.1:8765/health",
            method="GET"
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data.get('status') == 'ok':
                print_colored("Server health check passed", Colors.GREEN)
                return True
            else:
                print_colored(f"Health check returned unexpected status: {data}", Colors.WARNING)
                return False

    except urllib.error.URLError as e:
        print_colored(f"Cannot connect to server: {e}", Colors.FAIL)
        return False
    except Exception as e:
        print_colored(f"Test failed: {e}", Colors.FAIL)
        return False


def check_cookies_exist() -> bool:
    """Check if Twitter cookies exist."""
    skill_dir = get_skill_dir()
    cookies_path = skill_dir / "twitter_cookies.json"
    return cookies_path.exists()


def run_initial_auth() -> bool:
    """Run initial authentication to get cookies."""
    print_colored("\nRunning initial authentication...", Colors.BOLD)
    print("This will open a headless browser to log in to Twitter/X.")
    print("Please wait...\n")

    skill_dir = get_skill_dir()
    venv_python = get_venv_python()

    # Run the cookie refresh script
    code, out, err = run_command(
        [str(venv_python), "-c",
         "import asyncio; from cookie_refresh import refresh_cookies; print(asyncio.run(refresh_cookies()))"],
        cwd=str(skill_dir),
        check=False
    )

    if code != 0:
        print_colored("Initial authentication failed", Colors.FAIL)
        print(f"Output: {out}")
        print(f"Error: {err}")
        return False

    # Check if cookies were created
    if check_cookies_exist():
        print_colored("Authentication successful - cookies saved", Colors.GREEN)
        return True
    else:
        print_colored("Authentication may have failed - no cookies found", Colors.WARNING)
        return False


def main():
    """Main wizard flow."""
    total_steps = 6

    skill_dir = get_skill_dir()

    # Verify we're in the right directory
    if not skill_dir.exists():
        print_colored(f"Error: Skill directory not found at {skill_dir}", Colors.FAIL)
        print_colored("Please ensure the twitter_scrape skill is cloned correctly.", Colors.FAIL)
        sys.exit(1)

    # Print welcome banner
    print_colored("""
    ╔══════════════════════════════════════════════════════════════╗
    ║                                                              ║
    ║         Twitter/X Scraper Setup Wizard                       ║
    ║         Installs and configures twitter_scrape skill         ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
    """, Colors.CYAN + Colors.BOLD)

    # STEP 1: Check Python and dependencies
    print_step(1, total_steps, "Check Python and Dependencies")

    if not check_python_version():
        print_colored("\nPlease install Python 3.10 or higher and re-run this wizard.", Colors.FAIL)
        sys.exit(1)

    if not check_venv_exists():
        print("Virtual environment not found. Creating one...")
        create_venv()

    install_dependencies()
    install_playwright_chromium()

    # STEP 2: Configure Twitter credentials
    print_step(2, total_steps, "Configure Twitter/X Credentials")

    if check_twitter_config_exists():
        print_colored("Existing Twitter config found", Colors.GREEN)
        existing = read_twitter_config()
        if existing:
            print(f"  Username: {existing.get('username', 'N/A')}")

        if confirm("Use existing credentials?"):
            print_colored("Using existing credentials", Colors.GREEN)
        else:
            credentials = collect_twitter_credentials()
            write_twitter_config(credentials)
    else:
        credentials = collect_twitter_credentials()
        write_twitter_config(credentials)

    # STEP 3: Run initial authentication
    print_step(3, total_steps, "Initial Authentication")

    if check_cookies_exist():
        print_colored("Twitter cookies already exist", Colors.GREEN)
        if not confirm("Re-authenticate anyway?"):
            print_colored("Skipping authentication", Colors.CYAN)
        else:
            run_initial_auth()
    else:
        if confirm("Run initial authentication now? (recommended)"):
            run_initial_auth()
        else:
            print_colored("Skipping authentication - you can run it later with 'x refresh'", Colors.WARNING)

    # STEP 4: Install systemd service
    print_step(4, total_steps, "Install Systemd Service")

    if is_systemd_service_installed("twitter-scrape.service"):
        print_colored("Systemd service already installed", Colors.GREEN)
        if confirm("Reinstall service?"):
            install_systemd_service()
    else:
        install_systemd_service()

    # STEP 5: Start the service
    print_step(5, total_steps, "Start the Service")

    if not start_service():
        print_colored("\nService failed to start. Please check the logs above.", Colors.FAIL)
        sys.exit(1)

    # STEP 6: Create symlink and test
    print_step(6, total_steps, "Create CLI Symlink and Test")

    if check_x_symlink_exists():
        print_colored("'x' command already available", Colors.GREEN)
    else:
        create_x_symlink()

    # Wait a moment for the service to fully start
    time.sleep(2)

    if test_installation():
        print_colored("\nInstallation test passed", Colors.GREEN)
    else:
        print_colored("\nInstallation test had issues, but service may still work", Colors.WARNING)
        print_colored("Try running 'x status' in a few moments", Colors.WARNING)

    # Final message
    print_colored("""
✅ Setup complete!

Your Twitter/X scraper is now running as a systemd service.

Quick commands:
  x status           Check server status and cookies
  x user <username>  Scrape a user's tweets
  x search "query"   Search tweets
  x refresh          Force cookie refresh
  x help             Show all commands

Service management:
  sudo systemctl status twitter-scrape
  sudo systemctl restart twitter-scrape
  sudo journalctl -u twitter-scrape -f

Configuration files:
  Credentials: ~/.openclaw/skills/twitter_scrape/.twitter_config.json
  Cookies:     ~/.openclaw/skills/twitter_scrape/twitter_cookies.json
  Accounts:    ~/.openclaw/skills/twitter_scrape/.env (for multi-account)

""", Colors.GREEN + Colors.BOLD)

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_colored("\n\nWizard interrupted. You can re-run with:", Colors.WARNING)
        print_colored(f"  python3 {__file__}", Colors.CYAN)
        sys.exit(0)
    except Exception as e:
        print_colored(f"\n\nError: {e}", Colors.FAIL)
        import traceback
        traceback.print_exc()
        sys.exit(1)
