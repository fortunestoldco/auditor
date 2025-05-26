#!/bin/bash

# Install script for Python Audit Monitor

set -e

echo "Installing Python Audit Monitor..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)"
    exit 1
fi

# Install required Python packages
echo "Installing required Python packages..."
pip3 install psutil watchdog

# Create log directory
echo "Creating log directory..."
mkdir -p /var/log/audit
chmod 755 /var/log/audit

# Get the user who invoked sudo
REAL_USER=${SUDO_USER:-$(whoami)}

# Copy service file to systemd directory
echo "Installing systemd service for user: $REAL_USER"
cp python-audit-monitor.service /etc/systemd/system/

# Make the monitor script executable
chmod +x audit_monitor.py

# Reload systemd and enable service
echo "Enabling and starting service..."
systemctl daemon-reload
systemctl enable python-audit-monitor.service
systemctl start python-audit-monitor@$REAL_USER.service

# Check service status
echo "Service status:"
systemctl status python-audit-monitor@$REAL_USER.service --no-pager

echo "Installation complete!"
echo "To check logs: journalctl -u python-audit-monitor@$REAL_USER.service -f"
echo "To stop service: sudo systemctl stop python-audit-monitor@$REAL_USER.service"
echo "To start service: sudo systemctl start python-audit-monitor@$REAL_USER.service"