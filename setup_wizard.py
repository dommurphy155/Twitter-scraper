#!/usr/bin/env python3
"""
Twitter/X Scraper Setup Wizard - Fully Automated
Creates venv, installs deps, sets up cookies, installs systemd service.
"""

import os
import sys
import json
import subprocess
import time
import shutil
import socket
from pathlib import Path
from typing import List, Tuple, Optional


class Colors:
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    CYAN = '\033[96m'
    END = '\033[0m'
    BOLD = '\033[1m'


def printc(text: str, color: str = ""):
    print(f"{color}{text}{Colors.END}" if color else text)


def run(cmd: List[str], capture: bool = True, sudo: bool = False, cwd: str = None, timeout: int = 120) -> Tuple[int, str, str]:
    if sudo and os.geteuid() != 0:
        cmd = ['sudo'] + cmd
    try:
        result = subprocess.run(cmd, capture_output=capture, text=True, cwd=cwd, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)


def get_skill_dir() -> Path:
    return Path(__file__).parent.resolve()


def find_python() -> Optional[Path]:
    """Find Python 3.10+ executable."""
    for py in ['python3.12', 'python3.11', 'python3.10', 'python3']:
        code, out, _ = run([py, '--version'], capture=True)
        if code == 0:
            try:
                ver = out.strip().split()[1]
                major, minor = map(int, ver.split('.')[:2])
                if major == 3 and minor >= 10:
                    which_path = shutil.which(py)
                    if which_path:
                        return Path(which_path)
                    return Path(f'/usr/bin/{py}')
            except:
                pass
    return None


def find_existing_venv() -> Optional[Path]:
    """Search for existing Python 3.10+ venvs to reuse."""
    home = Path.home()
    skill_dir = get_skill_dir()

    search_paths = [
        home / ".openclaw" / "skills" / "twitter_scrape" / "venv",
        home / ".openclaw" / "skills" / "reddit_scrape" / "venv",
        home / ".openclaw" / "skills" / "ebay_scrape" / "venv",
        home / "venv",
        home / ".venv",
        Path("/opt/venv"),
        Path("/var/venv"),
        skill_dir.parent / "venv",
        skill_dir.parent / ".venv",
    ]

    env_venv = os.environ.get('VIRTUAL_ENV')
    if env_venv:
        search_paths.insert(0, Path(env_venv))

    for venv_path in search_paths:
        if not venv_path.exists():
            continue
        python_exe = venv_path / "bin" / "python"
        if not python_exe.exists():
            python_exe = venv_path / "Scripts" / "python.exe"
        if python_exe.exists():
            code, out, _ = run([str(python_exe), '--version'], capture=True)
            if code == 0:
                try:
                    ver = out.strip().split()[1]
                    major, minor = map(int, ver.split('.')[:2])
                    if major == 3 and minor >= 10:
                        printc(f"Found existing venv: {venv_path} (Python {ver})", Colors.CYAN)
                        return python_exe
                except:
                    pass
    return None


def setup_venv(skill_dir: Path) -> Path:
    venv = skill_dir / "venv"
    python = venv / "bin" / "python"

    if venv.exists() and python.exists():
        code, out, _ = run([str(python), '--version'], capture=True)
        if code == 0:
            try:
                ver = out.strip().split()[1]
                major, minor = map(int, ver.split('.')[:2])
                if major == 3 and minor >= 10:
                    printc(f"Using existing venv: {venv}", Colors.GREEN)
                    return python
            except:
                pass

    existing_python = find_existing_venv()
    if existing_python:
        printc(f"Linking to existing venv: {existing_python.parent.parent}", Colors.CYAN)
        if venv.exists():
            venv.unlink() if venv.is_symlink() else shutil.rmtree(venv)
        venv.symlink_to(existing_python.parent.parent)
        return existing_python

    py = find_python()
    if not py:
        printc("Python 3.10+ not found. Install python3.10 or higher.", Colors.FAIL)
        sys.exit(1)

    printc(f"Creating venv with {py}...", Colors.CYAN)
    code, _, err = run([str(py), '-m', 'venv', str(venv)])
    if code != 0:
        printc(f"Failed to create venv: {err}", Colors.FAIL)
        sys.exit(1)

    return python


def install_deps(python: Path):
    pip = python.parent / "pip"
    printc("Installing dependencies...", Colors.CYAN)

    deps = ['rnet', 'playwright', 'httpx']
    for pkg in deps:
        printc(f" {pkg}...", Colors.CYAN)
        args = [str(pip), 'install', pkg, '--pre'] if pkg == 'rnet' else [str(pip), 'install', pkg]
        run(args, capture=True)

    printc("Installing Chromium...", Colors.CYAN)
    run([str(python), '-m', 'playwright', 'install', 'chromium'], capture=True)
    printc("Done.", Colors.GREEN)


def is_chrome_debug_port_open() -> bool:
    """Check if Chrome is running with debugging port 9222."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('127.0.0.1', 9222))
        sock.close()
        return result == 0
    except:
        return False


def start_chrome_debug():
    """Start Chrome with debugging port."""
    printc("\nChrome debugging port 9222 not found.", Colors.WARNING)
    printc("Please start Chrome with remote debugging:", Colors.CYAN)
    printc("\n  google-chrome --remote-debugging-port=9222 &", Colors.BOLD)
    printc("\nOr if already running, restart it with the flag.", Colors.CYAN)

    resp = input("\nHave you started Chrome with debugging? [y/N]: ").strip().lower()
    if resp != 'y':
        printc("Cannot continue without Chrome debugging port.", Colors.FAIL)
        sys.exit(1)

    # Wait for port to be available
    for i in range(10):
        if is_chrome_debug_port_open():
            printc("Chrome debugging port detected.", Colors.GREEN)
            return True
        time.sleep(1)

    printc("Chrome debugging port still not available.", Colors.FAIL)
    sys.exit(1)


def get_cookies_manual(skill_dir: Path) -> bool:
    """Get cookies from Chrome manually."""
    printc("\n=== Cookie Setup ===", Colors.CYAN)
    printc("1. Open Chrome and log into x.com (must be logged in)")
    printc("2. Press F12 -> Application -> Cookies -> https://x.com")
    printc("3. Copy these cookies:\n")

    cookies = {}

    auth_token = input("auth_token: ").strip()
    if auth_token:
        cookies['auth_token'] = auth_token

    ct0 = input("ct0: ").strip()
    if ct0:
        cookies['ct0'] = ct0

    if not cookies:
        printc("At least one cookie required.", Colors.FAIL)
        return False

    # Save cookies in the format expected by the server
    cookies_path = skill_dir / "twitter_cookies.json"
    cookie_list = [{"name": k, "value": v} for k, v in cookies.items()]

    with open(cookies_path, 'w') as f:
        json.dump(cookie_list, f, indent=2)
    os.chmod(cookies_path, 0o600)

    printc(f"Saved {len(cookies)} cookies.", Colors.GREEN)
    return True


def install_service(skill_dir: Path, python: Path):
    user = os.environ.get('SUDO_USER') or os.environ.get('USER') or os.getlogin()

    service = f"""[Unit]
Description=Twitter Scraper API
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={skill_dir}
Environment="TWITTER_COOKIES_PATH={skill_dir}/twitter_cookies.json"
Environment="TWITTER_SCRAPE_HOST=127.0.0.1"
Environment="TWITTER_SCRAPE_PORT=8765"
Environment="PLAYWRIGHT_BROWSERS_PATH=0"
ExecStart={python} {skill_dir}/server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""

    temp = Path("/tmp/twitter-scrape.service")
    temp.write_text(service)

    code, _, err = run(['cp', str(temp), '/etc/systemd/system/twitter-scrape.service'], sudo=True)
    if code != 0:
        printc(f"Service install failed: {err}", Colors.FAIL)
        return False

    run(['systemctl', 'daemon-reload'], sudo=True)
    run(['systemctl', 'enable', 'twitter-scrape'], sudo=True)
    printc("Service installed.", Colors.GREEN)
    return True


def start_service():
    printc("Starting service...", Colors.CYAN)
    run(['systemctl', 'stop', 'twitter-scrape'], sudo=True, capture=True)
    time.sleep(1)
    run(['systemctl', 'start', 'twitter-scrape'], sudo=True)
    time.sleep(3)

    code, out, _ = run(['systemctl', 'is-active', 'twitter-scrape'], sudo=True)
    return 'active' in out


def test_server():
    import urllib.request
    for i in range(5):
        try:
            req = urllib.request.Request("http://127.0.0.1:8765/health")
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode())
                if data.get('status') == 'ok':
                    printc("Server healthy.", Colors.GREEN)
                    return True
        except:
            time.sleep(2)
    return False


def create_x_symlink(skill_dir: Path):
    local_bin = Path.home() / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)

    x_script = skill_dir / "x"
    link = local_bin / "x"

    if link.exists() or link.is_symlink():
        link.unlink()

    if x_script.exists():
        link.symlink_to(x_script)
        printc(f"CLI at {link}", Colors.GREEN)

    for profile in [Path.home() / ".bashrc", Path.home() / ".zshrc"]:
        if profile.exists():
            content = profile.read_text()
            if '.local/bin' not in content:
                with open(profile, 'a') as f:
                    f.write('\nexport PATH="$HOME/.local/bin:$PATH"\n')

def main():
    skill_dir = get_skill_dir()
    printc("="*60, Colors.CYAN)
    printc(" Twitter/X Scraper Setup", Colors.BOLD + Colors.CYAN)
    printc("="*60, Colors.CYAN)

    # Step 1: Venv
    python = setup_venv(skill_dir)
    printc(f"Python: {python}", Colors.GREEN)

    # Step 2: Deps
    install_deps(python)

    # Step 3: Check Chrome debugging port
    if not is_chrome_debug_port_open():
        start_chrome_debug()
    else:
        printc("Chrome debugging port 9222 is active.", Colors.GREEN)

    # Step 4: Cookies (manual only)
    cookies_path = skill_dir / "twitter_cookies.json"
    if cookies_path.exists():
        printc("Existing cookies found.", Colors.GREEN)
        resp = input("Update cookies? [y/N]: ").strip().lower()
        if resp == 'y':
            if not get_cookies_manual(skill_dir):
                printc("Cookie setup failed.", Colors.FAIL)
                sys.exit(1)
    else:
        printc("No cookies found.", Colors.WARNING)
        if not get_cookies_manual(skill_dir):
            printc("Cookie setup failed.", Colors.FAIL)
            sys.exit(1)

    # Step 5: Service
    if install_service(skill_dir, python):
        if start_service():
            test_server()
        else:
            printc("Service started but may still be initializing.", Colors.WARNING)

    # Step 6: CLI
    create_x_symlink(skill_dir)

    printc("\n" + "="*60, Colors.GREEN)
    printc(" Setup Complete!", Colors.BOLD + Colors.GREEN)
    printc("="*60, Colors.GREEN)
    printc("\nCommands:", Colors.CYAN)
    printc(" x status - Check server")
    printc(" x user <name> - Scrape user")
    printc(" x search \"q\" - Search tweets")
    printc(" x refresh - Refresh cookies")
    printc("="*60, Colors.GREEN)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        printc("\nInterrupted.", Colors.WARNING)
    except Exception as e:
        printc(f"\nError: {e}", Colors.FAIL)
        import traceback
        traceback.print_exc()
