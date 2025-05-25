#!/usr/bin/env python3

import os
import sys
import time
import csv
import subprocess
import threading
import psutil
import json
from datetime import datetime
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class GitPythonMonitor:
    def __init__(self, log_file="/var/log/audit/python_audit.csv"):
        self.log_file = log_file
        self.bucket_path = "gs://othertales-audit"
        self.upload_interval = 300  # 5 minutes
        self.git_dirs = set()
        self.active_processes = {}
        
        # Ensure log directory exists
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # Initialize CSV with headers if not exists
        if not os.path.exists(log_file):
            with open(log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'event_type', 'git_repo', 'file_path', 'python_command', 'output', 'user'])
    
    def find_git_directories(self):
        """Find all .git directories in the system"""
        for root, dirs, files in os.walk('/home'):
            if '.git' in dirs:
                self.git_dirs.add(os.path.join(root, '.git'))
                # Also monitor the parent directory
                self.git_dirs.add(root)
    
    def log_event(self, event_type, git_repo, file_path, python_command="", output=""):
        """Log an event to CSV"""
        timestamp = datetime.now().isoformat()
        user = os.getenv('USER', 'unknown')
        
        with open(self.log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, event_type, git_repo, file_path, python_command, output, user])
    
    def monitor_processes(self):
        """Monitor running Python processes in git directories"""
        while True:
            try:
                for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd']):
                    try:
                        proc_info = proc.info
                        if proc_info['name'] and 'python' in proc_info['name'].lower():
                            cwd = proc_info.get('cwd', '')
                            if self.is_in_git_repo(cwd):
                                pid = proc_info['pid']
                                cmdline = ' '.join(proc_info['cmdline'] or [])
                                
                                if pid not in self.active_processes:
                                    self.active_processes[pid] = {
                                        'start_time': time.time(),
                                        'cmdline': cmdline,
                                        'cwd': cwd,
                                        'logged': False
                                    }
                                    
                                    # Log the start of Python execution
                                    git_repo = self.find_git_repo(cwd)
                                    self.log_event('python_start', git_repo, cwd, cmdline)
                                    
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                
                # Clean up finished processes
                finished_pids = []
                for pid, info in self.active_processes.items():
                    if not psutil.pid_exists(pid):
                        finished_pids.append(pid)
                        # Log process completion
                        runtime = time.time() - info['start_time']
                        git_repo = self.find_git_repo(info['cwd'])
                        self.log_event('python_end', git_repo, info['cwd'], info['cmdline'], f"Runtime: {runtime:.2f}s")
                
                for pid in finished_pids:
                    del self.active_processes[pid]
                    
            except Exception as e:
                print(f"Error monitoring processes: {e}")
            
            time.sleep(2)
    
    def is_in_git_repo(self, path):
        """Check if path is within a git repository"""
        if not path:
            return False
        current = Path(path)
        for parent in [current] + list(current.parents):
            if (parent / '.git').exists():
                return True
        return False
    
    def find_git_repo(self, path):
        """Find the root of the git repository"""
        if not path:
            return ""
        current = Path(path)
        for parent in [current] + list(current.parents):
            if (parent / '.git').exists():
                return str(parent)
        return path

class GitFileHandler(FileSystemEventHandler):
    def __init__(self, monitor):
        self.monitor = monitor
    
    def on_modified(self, event):
        if not event.is_directory:
            if self.monitor.is_in_git_repo(event.src_path):
                git_repo = self.monitor.find_git_repo(event.src_path)
                self.monitor.log_event('file_edit', git_repo, event.src_path)
    
    def on_created(self, event):
        if not event.is_directory:
            if self.monitor.is_in_git_repo(event.src_path):
                git_repo = self.monitor.find_git_repo(event.src_path)
                self.monitor.log_event('file_create', git_repo, event.src_path)

class GitCommitMonitor:
    def __init__(self, monitor):
        self.monitor = monitor
    
    def monitor_git_commands(self):
        """Monitor git commands by watching git directories"""
        while True:
            try:
                for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd']):
                    try:
                        proc_info = proc.info
                        if proc_info['name'] == 'git':
                            cwd = proc_info.get('cwd', '')
                            if self.monitor.is_in_git_repo(cwd):
                                cmdline = ' '.join(proc_info['cmdline'] or [])
                                if 'commit' in cmdline:
                                    git_repo = self.monitor.find_git_repo(cwd)
                                    self.monitor.log_event('git_commit', git_repo, cwd, cmdline)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception as e:
                print(f"Error monitoring git commands: {e}")
            
            time.sleep(1)

def upload_logs(monitor):
    """Upload logs to Google Cloud Storage every 5 minutes"""
    while True:
        try:
            time.sleep(monitor.upload_interval)
            if os.path.exists(monitor.log_file):
                filename = f"python_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                remote_path = f"{monitor.bucket_path}/{filename}"
                
                # Copy current log to timestamped file
                timestamped_file = f"/tmp/{filename}"
                subprocess.run(['cp', monitor.log_file, timestamped_file], check=True)
                
                # Upload to GCS
                result = subprocess.run(['gsutil', 'cp', timestamped_file, remote_path], 
                                      capture_output=True, text=True)
                
                if result.returncode == 0:
                    print(f"Successfully uploaded {filename} to GCS")
                    # Clean up temp file
                    os.remove(timestamped_file)
                else:
                    print(f"Failed to upload to GCS: {result.stderr}")
                    
        except Exception as e:
            print(f"Error uploading logs: {e}")

def main():
    monitor = GitPythonMonitor()
    
    # Start process monitoring thread
    process_thread = threading.Thread(target=monitor.monitor_processes, daemon=True)
    process_thread.start()
    
    # Start git command monitoring thread
    git_monitor = GitCommitMonitor(monitor)
    git_thread = threading.Thread(target=git_monitor.monitor_git_commands, daemon=True)
    git_thread.start()
    
    # Start file watching
    observer = Observer()
    handler = GitFileHandler(monitor)
    
    # Watch home directory and subdirectories
    observer.schedule(handler, '/home', recursive=True)
    observer.start()
    
    # Start log upload thread
    upload_thread = threading.Thread(target=upload_logs, args=(monitor,), daemon=True)
    upload_thread.start()
    
    print("Python audit monitor started")
    
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        observer.stop()
        print("Python audit monitor stopped")
    
    observer.join()

if __name__ == "__main__":
    main()