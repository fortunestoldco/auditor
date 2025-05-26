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
    def __init__(self, log_file="/tmp/audit/python_audit.csv"):
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
                writer.writerow(['timestamp', 'event_type', 'git_repo', 'file_path', 'command', 'output', 'user', 'tool', 'prompt'])
    
    def find_git_directories(self):
        """Find all .git directories in the system"""
        for root, dirs, files in os.walk('/home'):
            if '.git' in dirs:
                self.git_dirs.add(os.path.join(root, '.git'))
                # Also monitor the parent directory
                self.git_dirs.add(root)
    
    def log_event(self, event_type, git_repo, file_path, command="", output="", tool="", prompt=""):
        """Log an event to CSV"""
        timestamp = datetime.now().isoformat()
        user = os.getenv('USER', 'unknown')
        
        with open(self.log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, event_type, git_repo, file_path, command, output, user, tool, prompt])
    
    def monitor_processes(self):
        """Monitor running Python and Node.js processes in git directories"""
        while True:
            try:
                for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd']):
                    try:
                        proc_info = proc.info
                        proc_name = proc_info['name'] or ''
                        
                        # Check for Python, Node.js, npm, yarn processes
                        is_monitored = (
                            'python' in proc_name.lower() or
                            proc_name.lower() in ['node', 'npm', 'yarn', 'npx', 'pnpm'] or
                            'code' in proc_name.lower()  # VSCode processes
                        )
                        
                        if is_monitored:
                            cwd = proc_info.get('cwd', '')
                            if self.is_in_git_repo(cwd):
                                pid = proc_info['pid']
                                cmdline = ' '.join(proc_info['cmdline'] or [])
                                
                                if pid not in self.active_processes:
                                    self.active_processes[pid] = {
                                        'start_time': time.time(),
                                        'cmdline': cmdline,
                                        'cwd': cwd,
                                        'logged': False,
                                        'proc_type': self._get_process_type(proc_name, cmdline)
                                    }
                                    
                                    # Log the start of process execution
                                    git_repo = self.find_git_repo(cwd)
                                    event_type = f"{self.active_processes[pid]['proc_type']}_start"
                                    tool = self._get_tool_name(proc_name, cmdline)
                                    self.log_event(event_type, git_repo, cwd, cmdline, tool=tool)
                                    
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
                        event_type = f"{info['proc_type']}_end"
                        tool = self._get_tool_name_from_cmdline(info['cmdline'])
                        self.log_event(event_type, git_repo, info['cwd'], info['cmdline'], f"Runtime: {runtime:.2f}s", tool=tool)
                
                for pid in finished_pids:
                    del self.active_processes[pid]
                    
            except Exception as e:
                print(f"Error monitoring processes: {e}")
            
            time.sleep(2)
    
    def _get_process_type(self, proc_name, cmdline):
        """Determine the type of process for logging"""
        proc_name_lower = proc_name.lower()
        if 'python' in proc_name_lower:
            return 'python'
        elif proc_name_lower in ['node', 'npm', 'yarn', 'npx', 'pnpm']:
            return 'nodejs'
        elif 'code' in proc_name_lower:
            return 'vscode'
        elif 'claude' in cmdline.lower():
            return 'claude_code'
        return 'unknown'
    
    def _get_tool_name(self, proc_name, cmdline):
        """Extract tool name from process info"""
        proc_name_lower = proc_name.lower()
        if 'code' in proc_name_lower:
            return 'vscode'
        elif 'claude' in cmdline.lower():
            return 'claude_code'
        elif proc_name_lower in ['npm', 'yarn', 'npx', 'pnpm']:
            return proc_name_lower
        elif proc_name_lower == 'node':
            return 'node'
        elif 'python' in proc_name_lower:
            return 'python'
        return proc_name
    
    def _get_tool_name_from_cmdline(self, cmdline):
        """Extract tool name from command line"""
        cmdline_lower = cmdline.lower()
        if 'claude' in cmdline_lower:
            return 'claude_code'
        elif 'code' in cmdline_lower:
            return 'vscode'
        elif any(tool in cmdline_lower for tool in ['npm', 'yarn', 'npx', 'pnpm']):
            for tool in ['npm', 'yarn', 'npx', 'pnpm']:
                if tool in cmdline_lower:
                    return tool
        elif 'node' in cmdline_lower:
            return 'node'
        elif 'python' in cmdline_lower:
            return 'python'
        return 'unknown'
    
    def monitor_claude_code_prompts(self):
        """Monitor Claude Code activity by watching for prompt inputs"""
        claude_log_dirs = [
            '/tmp/claude_code',
            f'/home/{os.getenv("USER", "ubuntu")}/.cache/claude_code',
            f'/home/{os.getenv("USER", "ubuntu")}/.local/share/claude_code'
        ]
        
        for log_dir in claude_log_dirs:
            if os.path.exists(log_dir):
                try:
                    for file in os.listdir(log_dir):
                        if file.endswith('.log') or 'session' in file:
                            log_path = os.path.join(log_dir, file)
                            self._parse_claude_logs(log_path)
                except Exception as e:
                    continue
    
    def _parse_claude_logs(self, log_path):
        """Parse Claude Code logs for user prompts"""
        try:
            with open(log_path, 'r') as f:
                for line in f:
                    if 'user:' in line.lower() or 'prompt:' in line.lower():
                        if self.is_in_git_repo(os.getcwd()):
                            git_repo = self.find_git_repo(os.getcwd())
                            prompt_text = line.strip()[:200]  # Limit prompt length
                            self.log_event('claude_prompt', git_repo, os.getcwd(), 
                                         command='', output='', tool='claude_code', prompt=prompt_text)
        except Exception:
            pass
    
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
        self.last_modified = {}  # Track to avoid duplicate events
    
    def on_modified(self, event):
        if not event.is_directory:
            # Skip temporary files and system files
            if self._should_skip_file(event.src_path):
                return
                
            if self.monitor.is_in_git_repo(event.src_path):
                # Debounce rapid file changes
                current_time = time.time()
                if event.src_path in self.last_modified:
                    if current_time - self.last_modified[event.src_path] < 1.0:
                        return
                self.last_modified[event.src_path] = current_time
                
                git_repo = self.monitor.find_git_repo(event.src_path)
                tool = self._detect_editing_tool(event.src_path)
                self.monitor.log_event('file_edit', git_repo, event.src_path, tool=tool)
    
    def on_created(self, event):
        if not event.is_directory:
            if self._should_skip_file(event.src_path):
                return
                
            if self.monitor.is_in_git_repo(event.src_path):
                git_repo = self.monitor.find_git_repo(event.src_path)
                tool = self._detect_editing_tool(event.src_path)
                self.monitor.log_event('file_create', git_repo, event.src_path, tool=tool)
    
    def _should_skip_file(self, file_path):
        """Skip temporary files, lock files, and system files"""
        skip_patterns = [
            '.git/', '.swp', '.tmp', '.lock', '.DS_Store', 
            '__pycache__/', 'node_modules/', '.vscode/',
            '~', '.bak'
        ]
        return any(pattern in file_path for pattern in skip_patterns)
    
    def _detect_editing_tool(self, file_path):
        """Detect which tool is likely editing the file"""
        # Check for VSCode temp files or workspace files
        if '.vscode' in file_path or file_path.endswith('.code-workspace'):
            return 'vscode'
        
        # Check running processes to see what might be editing
        try:
            for proc in psutil.process_iter(['name', 'open_files']):
                try:
                    proc_info = proc.info
                    if proc_info['name'] and 'code' in proc_info['name'].lower():
                        open_files = proc_info.get('open_files', [])
                        if any(f.path == file_path for f in open_files if hasattr(f, 'path')):
                            return 'vscode'
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
            
        return 'unknown'

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
    
    # Start Claude Code prompt monitoring thread
    def claude_monitor_loop():
        while True:
            monitor.monitor_claude_code_prompts()
            time.sleep(10)
    
    claude_thread = threading.Thread(target=claude_monitor_loop, daemon=True)
    claude_thread.start()
    
    # Start file watching
    observer = Observer()
    handler = GitFileHandler(monitor)
    
    # Watch home directory and subdirectories
    observer.schedule(handler, '/home', recursive=True)
    observer.start()
    
    # Start log upload thread
    upload_thread = threading.Thread(target=upload_logs, args=(monitor,), daemon=True)
    upload_thread.start()
    
    print("Multi-language audit monitor started (Python, Node.js, VSCode, Claude Code)")
    
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        observer.stop()
        print("Multi-language audit monitor stopped")
    
    observer.join()

if __name__ == "__main__":
    main()