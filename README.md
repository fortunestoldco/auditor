# Python Audit Monitor

A systemd service that monitors Python usage in git repositories and logs activities to CSV files, automatically uploading them to Google Cloud Storage.

## Features

- Monitors Python process execution in .git directories
- Logs runtime output, file edits, and git commits
- Timestamped CSV logging
- Automatic upload to gs://othertales-audit every 5 minutes
- Runs as background systemd service

## Installation

1. Ensure you have gsutil configured for Google Cloud Storage access
2. Run the installation script as root:

```bash
sudo ./install.sh
```

## Log Format

The CSV log contains the following columns:
- timestamp: ISO format timestamp
- event_type: python_start, python_end, file_edit, file_create, git_commit
- git_repo: Path to the git repository root
- file_path: Path to the affected file
- python_command: Command line for Python processes
- output: Runtime information or command output
- user: System user who triggered the event

## Service Management

```bash
# Check status
sudo systemctl status python-audit-monitor.service

# View logs
journalctl -u python-audit-monitor.service -f

# Stop/start service
sudo systemctl stop python-audit-monitor.service
sudo systemctl start python-audit-monitor.service
```

## Requirements

- Python 3.6+
- psutil
- watchdog
- gsutil (Google Cloud SDK)
- systemd (Ubuntu/Debian)

## Files

- `audit_monitor.py`: Main monitoring script
- `python-audit-monitor.service`: Systemd service file
- `install.sh`: Installation script
- Logs stored in: `/var/log/audit/python_audit.csv`