#!/bin/bash
# Install systemd service for twitter-scrape with auto-cookie-refresh

set -e

echo "Installing Twitter Scrape systemd service..."
echo ""

# Check if running as root (we need sudo for systemctl)
if [ "$EUID" -ne 0 ]; then
    echo "This script needs sudo privileges."
    echo "Run: sudo bash install-service.sh"
    exit 1
fi

# Get the user who ran sudo (not root)
SUDO_USER=${SUDO_USER:-$USER}
SKILL_DIR="/home/${SUDO_USER}/.openclaw/skills/twitter_scrape"

echo "Installing for user: ${SUDO_USER}"
echo "Skill directory: ${SKILL_DIR}"
echo ""

# Check skill directory exists
if [ ! -d "$SKILL_DIR" ]; then
    echo "Error: Skill directory not found at ${SKILL_DIR}"
    echo "Please clone the repo first:"
    echo "  git clone git@github.com:dommurphy155/Twitter-scraper.git ${SKILL_DIR}"
    exit 1
fi

cd "$SKILL_DIR"

# Install Playwright if not already installed
echo "Installing Playwright..."
if ! ./venv/bin/python -c "import playwright" 2>/dev/null; then
    ./venv/bin/pip install playwright
fi

# Install Chromium browser
echo "Installing Chromium browser for Playwright..."
./venv/bin/playwright install chromium

echo ""
echo "Setting up systemd service..."

# Copy service file
cat > /etc/systemd/system/twitter-scrape.service << EOF
[Unit]
Description=Twitter Scraper API Server with Auto Cookie Refresh
After=network.target

[Service]
Type=simple
User=${SUDO_USER}
WorkingDirectory=${SKILL_DIR}
Environment="TWITTER_COOKIES_PATH=${SKILL_DIR}/twitter_cookies.json"
Environment="TWITTER_SCRAPE_HOST=127.0.0.1"
Environment="TWITTER_SCRAPE_PORT=8765"
Environment="PLAYWRIGHT_BROWSERS_PATH=0"
ExecStart=${SKILL_DIR}/venv/bin/python ${SKILL_DIR}/server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
systemctl daemon-reload

# Enable and start service
systemctl enable twitter-scrape
systemctl start twitter-scrape

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║              Installation Complete!                        ║"
echo "╠════════════════════════════════════════════════════════════╣"
echo "║  Service:     sudo systemctl status twitter-scrape         ║"
echo "║  Logs:        sudo journalctl -u twitter-scrape -f         ║"
echo "║  Test:        x status                                     ║"
echo "╠════════════════════════════════════════════════════════════╣"
echo "║  IMPORTANT: Set up auto-refresh credentials:               ║"
echo "║                                                            ║"
echo "║  1. cp .twitter_config.example.json .twitter_config.json   ║"
echo "║  2. Edit .twitter_config.json with your credentials        ║"
echo "║  3. sudo systemctl restart twitter-scrape                  ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
