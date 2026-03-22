#!/bin/bash
# Install systemd service for twitter-scrape

set -e

echo "Installing Twitter Scrape systemd service..."

# Check if running as root (we need sudo for systemctl)
if [ "$EUID" -ne 0 ]; then
    echo "This script needs sudo privileges."
    echo "Run: sudo bash install-service.sh"
    exit 1
fi

# Copy service file
cp /home/azureuser/.openclaw/skills/twitter_scrape/twitter-scrape.service /etc/systemd/system/

# Reload systemd
systemctl daemon-reload

# Enable and start service
systemctl enable twitter-scrape
systemctl start twitter-scrape

echo ""
echo "Service installed!"
echo "Status: sudo systemctl status twitter-scrape"
echo "Logs:   sudo journalctl -u twitter-scrape -f"
echo ""
echo "Test it: x status"
