#!/bin/bash

# Install script for Python Audit Monitor

set -e

echo "Installing Python Audit Monitor..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)"
    exit 1
fi


# Create log directory
echo "Creating log directory..."
mkdir -p /var/log/audit
chmod 755 /var/log/audit

# Get the user who invoked sudo
REAL_USER=${SUDO_USER:-$(whoami)}
USER_HOME=$(eval echo ~$REAL_USER)

# Create virtual environment if it doesn't exist
VENV_PATH="$USER_HOME/.venv"
if [ ! -d "$VENV_PATH" ]; then
    echo "Creating virtual environment at $VENV_PATH..."
    sudo -u $REAL_USER python3 -m venv "$VENV_PATH"
else
    echo "Using existing virtual environment at $VENV_PATH"
fi

# Install packages in virtual environment
echo "Installing Python packages in virtual environment..."
sudo -u $REAL_USER "$VENV_PATH/bin/pip" install psutil watchdog

# Copy service file to systemd directory
echo "Installing systemd service for user: $REAL_USER"
cp python-audit-monitor.service /etc/systemd/system/python-audit-monitor@.service

# Make the monitor script executable
chmod +x audit_monitor.py

# Reload systemd and enable service
echo "Enabling and starting service..."
systemctl daemon-reload
systemctl enable python-audit-monitor@$REAL_USER.service
systemctl start python-audit-monitor@$REAL_USER.service

# Check service status
echo "Service status:"
systemctl status python-audit-monitor@$REAL_USER.service --no-pager

echo "Installation complete!"
echo "To check logs: journalctl -u python-audit-monitor@$REAL_USER.service -f"
echo "To stop service: sudo systemctl stop python-audit-monitor@$REAL_USER.service"
echo "To start service: sudo systemctl start python-audit-monitor@$REAL_USER.service"