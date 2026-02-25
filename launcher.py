#!/usr/bin/env python3
"""OCDR Launcher - Desktop app to manage the OCDR Flask server."""

import os
import sys
import signal
import subprocess
import threading
import tkinter as tk
from tkinter import scrolledtext

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
RUN_SCRIPT = os.path.join(APP_DIR, 'run.py')
REQUIREMENTS = os.path.join(APP_DIR, 'requirements.txt')
URL = 'http://localhost:5000'


class OCDRLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title('OCDR Launcher')
        self.root.geometry('680x480')
        self.root.configure(bg='#0f1117')
        self.root.resizable(True, True)

        self.server_proc = None

        # --- Header ---
        hdr = tk.Frame(root, bg='#1a1d23', pady=10, padx=16)
        hdr.pack(fill='x')

        tk.Label(hdr, text='OCDR', font=('Segoe UI', 18, 'bold'),
                 fg='#4f8cff', bg='#1a1d23').pack(side='left')
        tk.Label(hdr, text='Billing Reconciliation System',
                 font=('Segoe UI', 10), fg='#8b8d93', bg='#1a1d23').pack(side='left', padx=(8, 0))

        self.status_label = tk.Label(hdr, text='  STOPPED', font=('Segoe UI', 10, 'bold'),
                                     fg='#f77', bg='#1a1d23')
        self.status_label.pack(side='right')

        # --- Button row ---
        btn_frame = tk.Frame(root, bg='#0f1117', pady=8, padx=16)
        btn_frame.pack(fill='x')

        btn_style = dict(font=('Segoe UI', 10), relief='flat', cursor='hand2',
                         padx=14, pady=6, borderwidth=0)

        self.start_btn = tk.Button(btn_frame, text='Start Server', bg='#22863a', fg='white',
                                   activebackground='#2ea44f', command=self.start_server, **btn_style)
        self.start_btn.pack(side='left', padx=(0, 6))

        self.stop_btn = tk.Button(btn_frame, text='Stop Server', bg='#6c757d', fg='white',
                                  activebackground='#5a6268', command=self.stop_server,
                                  state='disabled', **btn_style)
        self.stop_btn.pack(side='left', padx=(0, 6))

        self.restart_btn = tk.Button(btn_frame, text='Restart', bg='#4f8cff', fg='white',
                                     activebackground='#6da0ff', command=self.restart_server, **btn_style)
        self.restart_btn.pack(side='left', padx=(0, 6))

        self.install_btn = tk.Button(btn_frame, text='Install Deps', bg='#8b5cf6', fg='white',
                                     activebackground='#a78bfa', command=self.install_deps, **btn_style)
        self.install_btn.pack(side='left', padx=(0, 6))

        self.open_btn = tk.Button(btn_frame, text='Open Browser', bg='#1a1d23', fg='#4f8cff',
                                  activebackground='#2d3039', command=self.open_browser, **btn_style)
        self.open_btn.pack(side='right')

        # --- Log output ---
        log_frame = tk.Frame(root, bg='#0f1117', padx=16, pady=(0, 12))
        log_frame.pack(fill='both', expand=True)

        self.log = scrolledtext.ScrolledText(
            log_frame, wrap='word', font=('Consolas', 9), fg='#e4e6eb',
            bg='#1a1d23', insertbackground='#e4e6eb',
            selectbackground='#4f8cff', borderwidth=1, relief='solid',
            highlightthickness=0
        )
        self.log.pack(fill='both', expand=True)

        self._log('OCDR Launcher ready.')
        self._log(f'App directory: {APP_DIR}')
        self._log(f'Python: {PYTHON}')
        self._log('')

        # Handle window close
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

    def _log(self, msg):
        self.log.insert('end', msg + '\n')
        self.log.see('end')

    def _set_status(self, running):
        if running:
            self.status_label.config(text='  RUNNING', fg='#6d6')
            self.start_btn.config(state='disabled')
            self.stop_btn.config(state='normal')
        else:
            self.status_label.config(text='  STOPPED', fg='#f77')
            self.start_btn.config(state='normal')
            self.stop_btn.config(state='disabled')

    def start_server(self):
        if self.server_proc and self.server_proc.poll() is None:
            self._log('Server is already running.')
            return

        self._log('Starting OCDR server...')
        try:
            self.server_proc = subprocess.Popen(
                [PYTHON, RUN_SCRIPT],
                cwd=APP_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._set_status(True)
            self._log(f'Server started (PID {self.server_proc.pid})')
            self._log(f'Open {URL} in your browser')
            self._log('')

            # Stream output in background thread
            t = threading.Thread(target=self._stream_output, daemon=True)
            t.start()

        except Exception as e:
            self._log(f'ERROR: {e}')

    def _stream_output(self):
        try:
            for line in self.server_proc.stdout:
                self.root.after(0, self._log, line.rstrip())
        except Exception:
            pass
        finally:
            self.root.after(0, self._on_server_exit)

    def _on_server_exit(self):
        code = self.server_proc.returncode if self.server_proc else '?'
        self._log(f'Server exited (code {code})')
        self._set_status(False)

    def stop_server(self):
        if not self.server_proc or self.server_proc.poll() is not None:
            self._log('Server is not running.')
            self._set_status(False)
            return

        self._log('Stopping server...')
        try:
            self.server_proc.terminate()
            try:
                self.server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_proc.kill()
                self.server_proc.wait(timeout=3)
            self._log('Server stopped.')
        except Exception as e:
            self._log(f'ERROR stopping server: {e}')
        self._set_status(False)

    def restart_server(self):
        self._log('--- Restarting ---')
        self.stop_server()
        self.start_server()

    def install_deps(self):
        self._log('Installing dependencies...')
        self.install_btn.config(state='disabled')

        def _run():
            try:
                proc = subprocess.Popen(
                    [PYTHON, '-m', 'pip', 'install', '-r', REQUIREMENTS],
                    cwd=APP_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                for line in proc.stdout:
                    self.root.after(0, self._log, line.rstrip())
                proc.wait()
                self.root.after(0, self._log,
                                f'Install finished (exit code {proc.returncode})')
                self.root.after(0, self._log, '')
            except Exception as e:
                self.root.after(0, self._log, f'ERROR: {e}')
            finally:
                self.root.after(0, lambda: self.install_btn.config(state='normal'))

        threading.Thread(target=_run, daemon=True).start()

    def open_browser(self):
        import webbrowser
        webbrowser.open(URL)

    def on_close(self):
        self.stop_server()
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    app = OCDRLauncher(root)
    root.mainloop()
