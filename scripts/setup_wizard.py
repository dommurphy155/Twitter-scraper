#!/usr/bin/env python3
"""Twitter Scraper — first-run setup.

1. Creates venv + installs deps.
2. Attaches to existing Chrome on :9222 (your VNC desktop Chrome).
3. If Chrome isn't logged in to x.com, opens the login tab in that
   Chrome and waits for you to finish logging in.
4. Saves cookies + leaves Chrome alive (the session persists in the
   profile forever).
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent


# --- Terminal colors -------------------------------------------------------

class C:
    G = "\033[92m"
    Y = "\033[93m"
    R = "\033[91m"
    B = "\033[96m"
    X = "\033[0m"
    BLD = "\033[1m"


def cprint(text: str, color: str = "") -> None:
    if color and sys.stdout.isatty():
        print(f"{color}{text}{C.X}")
    else:
        print(text)


def step(msg: str) -> None:
    cprint(f"\n{C.BLD}==> {msg}{C.X}", C.B)


def ok(msg: str) -> None:
    cprint(f"    {msg}", C.G)


def warn(msg: str) -> None:
    cprint(f"    {msg}", C.Y)


def fail(msg: str) -> None:
    cprint(f"    {msg}", C.R)


def _stdin_interactive() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


# --- Subprocess helpers ----------------------------------------------------

def run(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 300,
        check: bool = False) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=str(cwd) if cwd else None, timeout=timeout)
        if check and r.returncode != 0:
            raise RuntimeError(
                f"Command failed: {' '.join(cmd)}\n{r.stderr.strip()}"
            )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", e.stderr or ""


def port_listening(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


# --- Python / venv --------------------------------------------------------

def find_python() -> Optional[Path]:
    for name in ("python3.12", "python3.11", "python3.10", "python3"):
        path = shutil.which(name)
        if not path:
            for cand in (f"/usr/bin/{name}", f"/usr/local/bin/{name}"):
                if Path(cand).exists():
                    path = cand
                    break
        if not path:
            continue
        code, out, _ = run([path, "--version"])
        if code != 0:
            continue
        try:
            ver = out.strip().split()[1]
            major, minor = map(int, ver.split(".")[:2])
            if major == 3 and minor >= 10:
                return Path(path)
        except Exception:
            continue
    return None


def setup_venv() -> Path:
    venv_dir = PROJECT_DIR / "venv"
    py = venv_dir / "bin" / "python"

    if venv_dir.exists() and py.exists():
        code, out, _ = run([str(py), "--version"])
        if code == 0:
            try:
                ver = out.strip().split()[1]
                major, minor = map(int, ver.split(".")[:2])
                if major == 3 and minor >= 10:
                    ok(f"Reusing existing venv (Python {ver})")
                    return py
            except Exception:
                pass

    for sibling in (
        PROJECT_DIR.parent / "venv",
        PROJECT_DIR.parent / ".venv",
        Path.home() / "venv",
        Path.home() / ".venv",
    ):
        sib_py = sibling / "bin" / "python"
        if sib_py.exists():
            code, out, _ = run([str(sib_py), "--version"])
            if code == 0:
                try:
                    ver = out.strip().split()[1]
                    major, minor = map(int, ver.split(".")[:2])
                    if major == 3 and minor >= 10:
                        ok(f"Reusing sibling venv at {sibling} (Python {ver})")
                        if venv_dir.exists() or venv_dir.is_symlink():
                            try:
                                venv_dir.unlink()
                            except IsADirectoryError:
                                shutil.rmtree(venv_dir)
                        venv_dir.symlink_to(sibling.resolve())
                        return sib_py
                except Exception:
                    continue

    py_src = find_python()
    if not py_src:
        fail("Python 3.10+ not found.")
        print("    Install with:")
        if platform.system() == "Darwin":
            print("      brew install python@3.12")
        else:
            print("      sudo apt install python3.12 python3.12-venv")
        sys.exit(1)

    ok(f"Creating venv with {py_src}")
    code, _, err = run([str(py_src), "-m", "venv", str(venv_dir)])
    if code != 0:
        fail(f"venv creation failed: {err}")
        sys.exit(1)
    return py


def install_deps(py: Path) -> None:
    step("Installing Python dependencies")
    pip = py.parent / "pip"
    pkgs = [
        ("rnet", ["install", "rnet", "--pre"]),
        ("playwright", ["install", "playwright"]),
        ("httpx", ["install", "httpx"]),
    ]
    for name, args in pkgs:
        cprint(f"    pip {name}...", C.B)
        code, out, err = run([str(pip), *args], timeout=300)
        if code != 0:
            warn(f"{name} install had warnings (continuing)")

    code, out, err = run([str(py), "-c", "import rnet, playwright"])
    if code != 0:
        fail("Dependency import failed:")
        print(f"      {err.strip() or out.strip()}")
        sys.exit(1)
    ok("rnet, playwright, httpx OK")

    step("Installing Chromium for Playwright")
    cprint("    playwright install chromium (may take a minute)...", C.B)
    code, _, err = run([str(py), "-m", "playwright", "install", "chromium"],
                       timeout=300)
    if code != 0:
        warn("playwright install chromium failed — will fall back to system Chrome")
    else:
        ok("Playwright Chromium installed")


# --- Login flow: connect-or-spawn -----------------------------------------

# Import these lazily so the wizard doesn't fail before deps are installed.
def _import_session():
    sys.path.insert(0, str(SCRIPT_DIR))
    from cookie_refresh import (
        ensure_logged_in, spawn_chrome, wait_for_chrome,
        debug_port, set_debug_port, find_free_port, port_listening,
        grab_cookies_via_cdp, find_chromium, COOKIES_PATH,
    )
    return locals()


def _detect_display() -> str:
    env = os.environ.get("DISPLAY")
    if env:
        return env
    # Check if XAUTHORITY exists and DISPLAY can be inferred.
    if Path.home().joinpath(".Xauthority").exists():
        return ":1"
    return ":0"


def setup_login_session(py: Path) -> bool:
    """Make sure the user is logged in to x.com via a live Chrome.

    Strategy:
      1. If a Chrome is on the debug port, attach. If logged in, done.
      2. If attached but not logged in, open the login tab in the same
         Chrome and wait for the user to finish.
      3. If no Chrome is up, ask whether to spawn one (headless or
         on the user's display). Default: spawn on :1 so it appears in
         the VNC desktop.
    """
    step("Login session")
    mod = _import_session()
    debug_port = mod["debug_port"]
    spawn_chrome = mod["spawn_chrome"]
    wait_for_chrome = mod["wait_for_chrome"]
    ensure_logged_in = mod["ensure_logged_in"]
    find_free_port = mod["find_free_port"]
    port_listening = mod["port_listening"]
    grab_cookies_via_cdp = mod["grab_cookies_via_cdp"]
    find_chromium = mod["find_chromium"]
    set_debug_port = mod["set_debug_port"]
    COOKIES_PATH = mod["COOKIES_PATH"]

    port = debug_port()
    display = _detect_display()
    print(f"    CDP port: {port}")
    print(f"    Display:  {display}")
    print(f"    Profile:  {SCRIPT_DIR / '.chrome-profile'}")

    # 1. Attach if a Chrome is already up.
    if port_listening("127.0.0.1", port):
        ok(f"Chrome already on :{port} — will attach")
        import asyncio
        async def _attach():
            cookies = await grab_cookies_via_cdp(port)
            return cookies

        cookies = asyncio.run(_attach())
        if cookies and len(cookies) >= 2:
            ok(f"Already logged in to x.com ({len(cookies)} cookies)")
            return True
        warn("Chrome is up but not logged in to x.com — opening login tab")

        # Drive the login flow in the existing Chrome.
        async def _login():
            return await ensure_logged_in(
                port=port, headless=False, display=display,
            )

        cookies, status = asyncio.run(_login())
        if cookies:
            ok(f"Logged in! {len(cookies)} cookies saved")
            return True
        warn("Login not completed — you can retry via POST /login later")
        return False

    # 2. No Chrome — spawn one on the user's display.
    if not find_chromium():
        fail("No Chromium browser found on this system.")
        print("    Install with:  sudo apt install google-chrome-stable")
        print("    Or run:        playwright install chromium")
        return False

    if not _stdin_interactive():
        warn("No Chrome running and no interactive stdin — skipping spawn")
        return False

    print()
    cprint("    No Chrome found on :{}.".format(port), C.Y)
    cprint("    I'll launch a Chrome window on display '{}' where you".format(display), C.B)
    cprint("    can log into x.com. The session will be kept alive forever —", C.B)
    cprint("    the server reuses this Chrome on every API call.", C.B)
    print()
    resp = input("    Launch Chrome now? [Y/n]: ").strip().lower()
    if resp in ("n", "no"):
        warn("Skipped. Run `python3 scripts/server.py` to start the service,")
        warn("then POST /login when ready.")
        return False

    print()
    cprint("    Launching Chrome...", C.B)
    proc = spawn_chrome(
        port=port, headless=False, display=display,
    )
    if not proc or not wait_for_chrome(port, timeout=15):
        fail("Chrome didn't start. Check `journalctl` or run server.py manually.")
        return False
    ok(f"Chrome up on :{port} (display {display})")

    # 3. Drive the login flow.
    async def _login():
        return await ensure_logged_in(
            port=port, headless=False, display=display,
        )

    cookies, status = asyncio.run(_login())
    if cookies:
        ok(f"Logged in! {len(cookies)} cookies saved to {COOKIES_PATH}")
        return True
    fail("Login was not completed in the browser window.")
    return False


# --- `x` CLI + service ----------------------------------------------------

X_SCRIPT = PROJECT_DIR / "x"


def write_x_wrapper(py: Path) -> None:
    content = f"""#!/usr/bin/env python3
# Auto-generated by setup_wizard.py — wraps the Twitter scraper HTTP API.
import json
import os
import sys
import urllib.request
import urllib.error

HOST = os.environ.get("TWITTER_SCRAPE_HOST", "127.0.0.1")
PORT = int(os.environ.get("TWITTER_SCRAPE_PORT", "8765"))
BASE = f"http://{{HOST}}:{{PORT}}"


def call(method, path, data=None):
    url = BASE + path
    body = json.dumps(data).encode() if data is not None else b""
    req = urllib.request.Request(url, data=body, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"Error {{e.code}}: {{e.read().decode()}}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Cannot reach server at {{BASE}}: {{e.reason}}", file=sys.stderr)
        print("Is the twitter-scrape service running?", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]

    if cmd == "status":
        print(json.dumps(call("GET", "/health"), indent=2))
        return 0

    if cmd == "session":
        print(json.dumps(call("GET", "/session"), indent=2))
        return 0

    if cmd == "accounts":
        print(json.dumps(call("GET", "/account/status"), indent=2))
        return 0

    if cmd == "login":
        print("Opening login flow — finish logging in in the browser window.")
        print(json.dumps(call("POST", "/login", {{}}), indent=2))
        return 0

    if cmd == "refresh":
        print(json.dumps(call("POST", "/refresh", {{}}), indent=2))
        return 0

    if cmd == "user" and len(sys.argv) >= 3:
        username = sys.argv[2]
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 50
        result = call("POST", "/user", {{"username": username, "limit": limit}})
        if result.get("success"):
            print(f"OK: {{result['tweets_count']}} tweets -> {{result['path']}}")
        else:
            print(json.dumps(result, indent=2))
        return 0

    if cmd == "search" and len(sys.argv) >= 3:
        query = sys.argv[2]
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 50
        result = call("POST", "/search",
                      {{"query": query, "limit": limit}})
        if result.get("success"):
            for t in result.get("tweets", [])[:10]:
                print(f"  @{{t.get('author','')}}: "
                      f"{{(t.get('text','') or '')[:120]}}")
        return 0

    if cmd == "tweet" and len(sys.argv) >= 3:
        text = " ".join(sys.argv[2:])
        result = call("POST", "/tweet", {{"text": text}})
        print(json.dumps(result, indent=2))
        return 0

    if cmd == "grok" and len(sys.argv) >= 3:
        text = " ".join(sys.argv[2:])
        result = call("POST", "/grok/chat", {{"message": text}})
        print(result.get("response", json.dumps(result, indent=2)))
        return 0

    print("Usage: x <status|session|accounts|login|refresh|user|search|tweet|grok> [args]")
    return 1


if __name__ == "__main__":
    sys.exit(main())
"""
    X_SCRIPT.write_text(content)
    X_SCRIPT.chmod(0o755)
    ok(f"Wrote CLI: {X_SCRIPT}")


def install_symlink() -> None:
    local_bin = Path.home() / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    link = local_bin / "x"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(X_SCRIPT)
    ok(f"Symlinked {link} -> {X_SCRIPT}")

    if str(local_bin) not in os.environ.get("PATH", ""):
        for rc in (Path.home() / ".bashrc", Path.home() / ".zshrc"):
            if rc.exists() and "PATH" in rc.read_text():
                if str(local_bin) not in rc.read_text():
                    with rc.open("a") as f:
                        f.write(f'\nexport PATH="{local_bin}:$PATH"\n')
                    warn(f"Added {local_bin} to PATH in {rc}")
                    break


# --- Systemd (optional) ---------------------------------------------------

def try_install_service(py: Path) -> None:
    if platform.system() != "Linux":
        return
    if not shutil.which("systemctl"):
        return
    if os.geteuid() != 0 and not shutil.which("sudo"):
        return

    step("Systemd service (optional)")
    use_sudo = os.geteuid() != 0
    user = os.environ.get("SUDO_USER") or os.environ.get("USER") or "root"

    unit = f"""[Unit]
Description=Twitter Scraper API
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={SCRIPT_DIR}
Environment="TWITTER_SCRAPE_HOST=127.0.0.1"
Environment="TWITTER_SCRAPE_PORT=8765"
Environment="DISPLAY=:1"
Environment="HOME={Path.home()}"
ExecStart={py} {SCRIPT_DIR}/server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    unit_path = Path("/etc/systemd/system/twitter-scrape.service")
    try:
        if use_sudo:
            p = subprocess.Popen(["sudo", "tee", str(unit_path)],
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            p.communicate(unit.encode())
            run(["sudo", "systemctl", "daemon-reload"])
            run(["sudo", "systemctl", "enable", "twitter-scrape"])
            run(["sudo", "systemctl", "start", "twitter-scrape"])
        else:
            unit_path.write_text(unit)
            run(["systemctl", "daemon-reload"])
            run(["systemctl", "enable", "twitter-scrape"])
            run(["systemctl", "start", "twitter-scrape"])
        ok("Service installed and started")
    except Exception as e:
        warn(f"Systemd install failed: {e}")


# --- Smoke test -----------------------------------------------------------

def smoke_test(py: Path) -> None:
    step("Smoke test")
    code, out, err = run([str(py), "-c",
        "from rnet_twitter import RnetTwitterClient; "
        "print('rnet_twitter OK')"], cwd=SCRIPT_DIR)
    if code == 0:
        ok(out.strip() or "imports OK")
    else:
        warn(f"rnet_twitter import: {(err or out).strip()}")


# --- Main -----------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    cprint(f"{C.BLD} Twitter Scraper — Setup Wizard{C.X}", C.B)
    print("=" * 60)
    print(f"  Project: {PROJECT_DIR}")
    print(f"  Python:  {sys.version.split()[0]}")
    print(f"  OS:      {platform.system()} {platform.release()}")

    py = setup_venv()
    install_deps(py)
    setup_login_session(py)
    write_x_wrapper(py)
    install_symlink()
    try_install_service(py)
    smoke_test(py)

    print()
    print("=" * 60)
    cprint(f"{C.BLD}  Setup complete!{C.X}", C.G)
    print("=" * 60)
    print()
    print("  Quick test:")
    print("    x status")
    print("    x user elonmusk 5")
    print('    x search "OpenAI" 10')
    print('    x grok "Hello Grok"')
    print()
    print("  Manual start (if not using systemd):")
    print(f"    {py} {SCRIPT_DIR}/server.py")
    print()
    print("  Add accounts for Grok rotation: edit .env in scripts/")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cprint("\nInterrupted.", C.Y)
        sys.exit(1)
