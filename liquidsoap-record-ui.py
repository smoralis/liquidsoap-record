#!/usr/bin/env python3

import sys
import argparse
import json
import os
import queue
import re
import signal
import socket
import http.client
import subprocess
import shutil
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse


if sys.platform == "win32":
    from ctypes import windll
    try:
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


# ============================================================
# DEFAULTS
# ============================================================

DEFAULT_WEB_HOST = "0.0.0.0"
DEFAULT_WEB_PORT = 8080

PARAMETERS_FILE = os.path.join(
    os.path.expanduser("~"),
    ".liquidsoap_record_parameters.json"
)

LIQUIDSOAP_HOST = "127.0.0.1"
LIQUIDSOAP_PORT = 1234

GRACEFUL_STOP_TIMEOUT = 15
FORCE_TERMINATE_TIMEOUT = 3


# ============================================================
# WEB SERVER
# ============================================================

class RecorderWebServer:

    def __init__(
        self,
        app,
        host=DEFAULT_WEB_HOST,
        port=DEFAULT_WEB_PORT
    ):
        self.app = app
        self.host = host
        self.port = port
        self.httpd = None
        self.thread = None

    def start(self):

        if self.httpd is not None:
            return

        app = self.app

        class Handler(BaseHTTPRequestHandler):

            def log_message(self, format_string, *args):
                pass

            def send_json(self, data, status=200):

                body = json.dumps(
                    data,
                    ensure_ascii=False
                ).encode("utf-8")

                self.send_response(status)

                self.send_header(
                    "Content-Type",
                    "application/json; charset=utf-8"
                )

                self.send_header(
                    "Content-Length",
                    str(len(body))
                )

                self.send_header(
                    "Cache-Control",
                    "no-cache, no-store, must-revalidate"
                )

                self.send_header(
                    "Pragma",
                    "no-cache"
                )

                self.end_headers()

                try:
                    self.wfile.write(body)
                except (
                    BrokenPipeError,
                    ConnectionResetError
                ):
                    pass

            def send_html(self, content):

                body = content.encode("utf-8")

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "text/html; charset=utf-8"
                )

                self.send_header(
                    "Content-Length",
                    str(len(body))
                )

                self.send_header(
                    "Cache-Control",
                    "no-cache, no-store, must-revalidate"
                )

                self.send_header(
                    "Pragma",
                    "no-cache"
                )

                self.end_headers()

                try:
                    self.wfile.write(body)
                except (
                    BrokenPipeError,
                    ConnectionResetError
                ):
                    pass

            def read_json(self):

                try:

                    length = int(
                        self.headers.get(
                            "Content-Length",
                            "0"
                        )
                    )

                    if length <= 0:
                        return {}

                    raw = self.rfile.read(length)

                    if not raw:
                        return {}

                    value = json.loads(
                        raw.decode("utf-8")
                    )

                    return (
                        value
                        if isinstance(value, dict)
                        else {}
                    )

                except Exception:
                    return {}

            def do_GET(self):

                path = urlparse(self.path).path

                if path == "/":
                    self.send_html(
                        app.web_page()
                    )
                    return

                if path == "/api/status":
                    self.send_json(
                        app.get_status()
                    )
                    return

                if path == "/api/parameters":
                    self.send_json(
                        app.get_parameters()
                    )
                    return

                if path == "/api/log":
                    self.send_json(
                        {"log": app.get_log()}
                    )
                    return

                if path == "/favicon.ico":
                    self.send_response(204)
                    self.end_headers()
                    return

                self.send_json(
                    {"error": "Not found"},
                    404
                )

            def do_POST(self):

                path = urlparse(self.path).path
                data = self.read_json()

                if path == "/api/start":

                    result = app.web_start(data)

                    self.send_json(
                        result,
                        200 if result.get("ok")
                        else 400
                    )

                    return

                if path == "/api/stop":

                    result = app.web_stop()

                    self.send_json(
                        result,
                        200 if result.get("ok")
                        else 400
                    )

                    return

                if path == "/api/parameters":

                    result = (
                        app.web_update_parameters(data)
                    )

                    self.send_json(
                        result,
                        200 if result.get("ok")
                        else 400
                    )

                    return

                self.send_json(
                    {"error": "Not found"},
                    404
                )

        self.httpd = ThreadingHTTPServer(
            (self.host, self.port),
            Handler
        )

        self.httpd.daemon_threads = True

        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            daemon=True
        )

        self.thread.start()

        self.app.write_log(
            f"[WEB] Server started on "
            f"{self.host}:{self.port}"
        )

    def stop(self):

        if self.httpd is None:
            return

        httpd = self.httpd
        self.httpd = None

        try:
            httpd.shutdown()
        except Exception:
            pass

        try:
            httpd.server_close()
        except Exception:
            pass

        self.thread = None

        self.app.write_log(
            "[WEB] Server stopped."
        )


# ============================================================
# MAIN APPLICATION
# ============================================================

class LiquidsoapRecordApp:

    def __init__(self, root, args):

        # Keep the parsed arguments so persistent settings can distinguish
        # temporary CLI overrides from normal GUI changes.
        self.args = args

        self.root = root

        # Saved parameters must be loaded before anything else that
        # depends on them (window geometry, GUI defaults, etc).
        saved = self.load_saved_parameters()
        cli_overrides = getattr(args, "_cli_overrides", set())

        # Linux desktop/taskbar identity
        self.root.title("Liquidsoap Recorder")
        self.root.iconname("Liquidsoap Recorder")
        try:
            # Set the X11/Wayland window class so desktop environments
            # identify this application as Liquidsoap Recorder rather than "tk".
            self.root.tk.call(
                "wm", "class", self.root._w,
                "LiquidsoapRecorder", "LiquidsoapRecorder"
            )
        except tk.TclError:
            pass

        # Application icon.  Keep the PNG next to this script.
        try:
            icon_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "liquidsoap-recorder.png"
            )
            if os.path.exists(icon_path):
                self._app_icon = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, self._app_icon)
        except (tk.TclError, OSError):
            self._app_icon = None

        saved_geometry = saved.get("window_geometry") if saved else None

        if (
            isinstance(saved_geometry, str)
            and re.fullmatch(r"\d+x\d+([+-]\d+[+-]\d+)?", saved_geometry)
        ):
            self.root.geometry(
                saved_geometry
            )
        else:
            self.root.geometry(
                "1000x950"
            )

        self.root.minsize(
            850,
            600
        )

        # ----------------------------------------------------
        # PROCESS
        # ----------------------------------------------------

        self.process = None
        self.output_thread = None
        self.stop_thread = None

        # Local Icecast player (mpv or ffplay)
        self.player_process = None
        self.player_backend = None
        self.player_volume_job = None
        self.player_url = tk.StringVar()
        self.player_volume = tk.DoubleVar(value=80.0)

        self.log_queue = queue.Queue()

        self.recording = False
        self.stopping = False
        self.closing = False

        self.start_time = None

        self.log_lines = []
        self.log_lock = threading.Lock()

        self.web_server = None

        # ----------------------------------------------------
        # THEMES
        # ----------------------------------------------------

        self.dark_mode = True

        self.themes = {

            "dark": {

                "bg": "#17191d",
                "panel": "#20242a",
                "panel2": "#272c33",
                "entry": "#2d333b",
                "text": "#e6edf3",
                "muted": "#8b949e",

                "green": "#20c878",
                "green_dark": "#163d2d",

                "red": "#ef5350",
                "red_dark": "#4b2222",

                "blue": "#58a6ff",

                "log_bg": "#080a0c",
                "log_fg": "#c9d1d9",

                "border": "#343a42",

                "button": "#30363d",
                "button_fg": "#e6edf3",

                "select": "#264f78"
            },

            "light": {

                "bg": "#f4f6f8",
                "panel": "#ffffff",
                "panel2": "#eef1f4",
                "entry": "#ffffff",
                "text": "#20242a",
                "muted": "#687078",

                "green": "#168a50",
                "green_dark": "#dff5e9",

                "red": "#c93632",
                "red_dark": "#fbe4e3",

                "blue": "#1769aa",

                "log_bg": "#ffffff",
                "log_fg": "#24292f",

                "border": "#c9ced4",

                "button": "#e9ecef",
                "button_fg": "#20242a",

                "select": "#b9d7f5"
            }
        }

        self.colors = self.themes["dark"]

        # ----------------------------------------------------
        # VARIABLES
        # ----------------------------------------------------

        # Saved parameters are defaults; explicit command-line arguments
        # must always take precedence over them.

        if saved:

            for key, value in saved.items():

                if (
                    hasattr(args, key)
                    and key not in cli_overrides
                ):
                    setattr(
                        args,
                        key,
                        value
                    )

        self.url = tk.StringVar(
            value=args.url or ""
        )

        self.directory = tk.StringVar(
            value=args.directory or ""
        )

        self.station = tk.StringVar(
            value=args.station or ""
        )

        self.transcode = tk.BooleanVar(
            value=args.transcode
        )

        self.samplerate = tk.StringVar(
            value=args.samplerate
        )

        self.format = tk.StringVar(
            value=args.format
        )

        self.codec = tk.StringVar(
            value=args.codec
        )

        self.bitrate = tk.StringVar(
            value=args.bitrate
        )

        self.listen = tk.BooleanVar(
            value=args.listen
        )


        self.device = tk.StringVar(
            value=args.device
        )

        self.log_level = tk.StringVar(
            value=args.log_level
        )

        self.keep = tk.BooleanVar(
            value=args.keep
        )

        self.timeout = tk.StringVar(
            value=args.timeout
        )

        self.tunein_id = tk.StringVar(
            value=args.tunein_id
        )

        self.relay = tk.BooleanVar(
            value=args.relay
        )

        self.host = tk.StringVar(
            value=args.relay_host
        )

        self.port = tk.StringVar(
            value=args.relay_port
        )

        self.password = tk.StringVar(
            value=args.password
        )

        self.m3u = tk.BooleanVar(
            value=args.m3u
        )

        self.covers = tk.BooleanVar(
            value=args.covers
        )

        self.single = tk.BooleanVar(
            value=args.single
        )

        self.web_enabled = tk.BooleanVar(
            value=args.web
        )

        self.web_host = tk.StringVar(
            value=args.web_host
        )

        self.web_port = tk.StringVar(
            value=str(args.web_port)
        )

        self.status = tk.StringVar(
            value="STOPPED"
        )

        self.elapsed = tk.StringVar(
            value="00:00:00"
        )

        self.current_file = tk.StringVar(
            value="-"
        )

        self.theme_text = tk.StringVar(
            value="☀  Light"
        )

        self.liquidsoap_version = tk.StringVar(
            value="Liquidsoap: detecting…"
        )

        self.record_liq_version = tk.StringVar(
            value="record.liq: detecting…"
        )

        # ----------------------------------------------------
        # BUILD
        # ----------------------------------------------------

        self.setup_style()

        self.create_gui()

        self.apply_theme()

        self.root.after(
            100,
            self.process_gui_queue
        )

        self.root.after(
            500,
            self.update_timer
        )

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.on_close
        )

        if self.web_enabled.get():

            self.root.after(
                300,
                self.start_web_server
            )

        # Start recording automatically when requested from the CLI.
        if getattr(args, "start_recording", False):

            self.root.after(
                500,
                self.start_recording
            )

    # ========================================================
    # STYLE
    # ========================================================

    def setup_style(self):

        self.style = ttk.Style()

        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.style.configure(
            "TLabel",
            font=("Segoe UI", 9)
        )

        self.style.configure(
            "TLabelframe",
            padding=5
        )

        self.style.configure(
            "TLabelframe.Label",
            font=("Segoe UI Semibold", 9)
        )

        self.style.configure(
            "TEntry",
            padding=5
        )

        self.style.configure(
            "TCombobox",
            insertcolor="#e6edf3",
            padding=4
        )

        self.style.configure(
            "TCheckbutton",
            font=("Segoe UI", 9)
        )

        self.style.configure(
            "TButton",
            font=("Segoe UI Semibold", 9),
            padding=(10, 6)
        )

        self.style.configure(
            "Green.TButton",
            font=("Segoe UI Semibold", 10),
            padding=(18, 9)
        )

        self.style.configure(
            "Red.TButton",
            font=("Segoe UI Semibold", 10),
            padding=(18, 9)
        )

        self.style.configure("Muted.TLabel", font=("Segoe UI", 8))
        self.style.configure("Section.TLabel", font=("Segoe UI Semibold", 11))
        self.style.configure("Log.TFrame")

        self.style.configure(
            "Muted.TLabel",
            font=("Segoe UI", 8),
        )

        self.style.configure(
            "Section.TLabel",
            font=("Segoe UI Semibold", 11),
        )

        self.style.configure(
            "Log.TFrame",
        )

    # ========================================================
    # GUI
    # ========================================================

    def create_gui(self):

        self.main = ttk.Frame(
            self.root
        )

        self.main.pack(
            fill="both",
            expand=True,
            padx=12,
            pady=10
        )

        self.main.rowconfigure(
            1,
            weight=1
        )

        self.main.columnconfigure(
            0,
            weight=1
        )

        # ----------------------------------------------------
        # HEADER
        # ----------------------------------------------------

        self.header = tk.Frame(
            self.main,
            height=48
        )

        self.header.grid(
            row=0,
            column=0,
            sticky="ew"
        )

        self.header.grid_propagate(
            False
        )

        self.header.columnconfigure(
            0,
            weight=1
        )

        self.header.columnconfigure(
            2,
            weight=1
        )

        self.title_label = tk.Label(
            self.header,
            text="Liquidsoap Record",
            font=("Segoe UI", 18, "bold"),
            relief="flat",
            bd=0,
            highlightthickness=0
        )

        self.title_label.grid(
            row=0,
            column=0,
            sticky="w",
            padx=4,
            pady=4
        )

        self.theme_button = tk.Button(
            self.header,
            textvariable=self.theme_text,
            command=self.toggle_theme,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2"
        )

        self.theme_button.grid(
            row=0,
            column=3,
            sticky="e",
            padx=4
        )

        self.version_frame = tk.Frame(
            self.header
        )

        self.version_frame.grid(
            row=0,
            column=1,
            columnspan=2,
            sticky="e",
            padx=(10, 4)
        )

        self.liquidsoap_version_label = tk.Label(
            self.version_frame,
            textvariable=self.liquidsoap_version,
            font=("Segoe UI", 8)
        )

        self.liquidsoap_version_label.pack(
            side="top",
            anchor="e"
        )

        self.record_liq_version_label = tk.Label(
            self.version_frame,
            textvariable=self.record_liq_version,
            font=("Segoe UI", 8)
        )

        self.record_liq_version_label.pack(
            side="top",
            anchor="e"
        )

        self.root.after(
            100,
            self.update_versions
        )

        # ----------------------------------------------------
        # NOTEBOOK
        # ----------------------------------------------------

        self.notebook = ttk.Notebook(
            self.main
        )

        self.notebook.grid(
            row=1,
            column=0,
            sticky="nsew",
            pady=(5, 0)
        )

        self.recorder_tab = ttk.Frame(
            self.notebook
        )

        self.notebook.add(
            self.recorder_tab,
            text="  Recorder  "
        )

        self.options_tab = ttk.Frame(
            self.notebook
        )

        self.notebook.add(
            self.options_tab,
            text="  Options  "
        )

        self.files_tab = ttk.Frame(
            self.notebook
        )

        self.notebook.add(
            self.files_tab,
            text="  Files  "
        )

        self.create_recorder_tab()

        self.create_options_tab()
        self.create_files_tab()

        self.directory.trace_add("write", self._directory_changed)
        self.notebook.bind("<<NotebookTabChanged>>", self._notebook_tab_changed)

    # ========================================================
    # FILES TAB
    # ========================================================

    def create_files_tab(self):
        tab = self.files_tab
        tab.configure(padding=10)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        header = ttk.Frame(tab)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(1, weight=1)

        ttk.Label(
            header, text="Recording directory", style="Panel.TLabel"
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))

        ttk.Label(
            header, textvariable=self.directory, style="Muted.TLabel"
        ).grid(row=0, column=1, sticky="ew")

        ttk.Button(
            header, text="Refresh", command=self.refresh_file_list
        ).grid(row=0, column=2, padx=(10, 0))

        ttk.Button(
            header, text="Expand All", command=self.expand_all_files
        ).grid(row=0, column=3, padx=(6, 0))

        ttk.Button(
            header, text="Collapse All", command=self.collapse_all_files
        ).grid(row=0, column=4, padx=(6, 0))

        ttk.Button(
            header, text="Open Directory", command=self.open_recording_directory
        ).grid(row=0, column=5, padx=(6, 0))

        self.files_count_label = ttk.Label(
            tab, text="0 files", style="Muted.TLabel"
        )
        self.files_count_label.grid(row=1, column=0, sticky="w", pady=(0, 5))

        tree_frame = ttk.Frame(tab)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        columns = ("size", "modified")
        self.file_tree = ttk.Treeview(
            tree_frame, columns=columns, show="tree headings", selectmode="browse"
        )
        self.file_tree.heading("#0", text="Name")
        self.file_tree.heading("size", text="Size")
        self.file_tree.heading("modified", text="Modified")
        self.file_tree.column("#0", anchor="w", stretch=True, width=430)
        self.file_tree.column("size", anchor="e", stretch=False, width=120)
        self.file_tree.column("modified", anchor="w", stretch=False, width=180)
        self.file_tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.file_tree.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.file_tree.configure(yscrollcommand=scrollbar.set)

        self.file_tree.bind(
            "<Double-1>", lambda event: self.open_selected_file()
        )

        ttk.Label(
            tab,
            text="Double-click a file to open it, or a folder to open it in your file manager.",
            style="Muted.TLabel"
        ).grid(row=3, column=0, sticky="w", pady=(7, 0))

        self.refresh_file_list()

    def _directory_changed(self, *_args):
        if hasattr(self, "file_tree"):
            self.refresh_file_list()

    def _notebook_tab_changed(self, _event=None):
        if hasattr(self, "files_tab") and self.notebook.select() == str(self.files_tab):
            self.refresh_file_list()

    def _format_file_size(self, size):
        units = ("B", "KB", "MB", "GB", "TB")
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"

    def refresh_file_list(self):
        if not hasattr(self, "file_tree"):
            return

        previous_open = {}

        def capture_open_state(item):
            for child in self.file_tree.get_children(item):
                if "folder" in self.file_tree.item(child, "tags"):
                    previous_open[child] = bool(
                        self.file_tree.item(child, "open")
                    )
                capture_open_state(child)

        capture_open_state("")

        for item in self.file_tree.get_children():
            self.file_tree.delete(item)

        directory = self.directory.get().strip()
        if not directory:
            self.files_count_label.configure(text="No recording directory selected")
            return

        if not os.path.isdir(directory):
            self.files_count_label.configure(text="Directory does not exist")
            return

        try:
            file_count = 0

            for root, dirs, files in os.walk(directory):
                dirs.sort(key=str.lower)
                files.sort(key=str.lower)

                rel_root = os.path.relpath(root, directory)
                parent_id = "" if rel_root == "." else rel_root

                for dirname in dirs:
                    rel_path = (
                        dirname if rel_root == "."
                        else os.path.join(rel_root, dirname)
                    )
                    self.file_tree.insert(
                        parent_id, "end", iid=rel_path, text=dirname,
                        values=("", ""),
                        open=previous_open.get(rel_path, True),
                        tags=("folder",)
                    )

                for filename in files:
                    full_path = os.path.join(root, filename)
                    try:
                        stat = os.stat(full_path)
                    except OSError:
                        continue
                    rel_path = (
                        filename if rel_root == "."
                        else os.path.join(rel_root, filename)
                    )
                    self.file_tree.insert(
                        parent_id, "end", iid=rel_path, text=filename,
                        values=(
                            self._format_file_size(stat.st_size),
                            datetime.fromtimestamp(stat.st_mtime).strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                        ),
                        tags=("file",)
                    )
                    file_count += 1

            self.files_count_label.configure(
                text=f"{file_count} file" + ("s" if file_count != 1 else "")
            )
        except OSError as exc:
            self.files_count_label.configure(text=f"Unable to read directory: {exc}")

    def _set_all_folders_open(self, is_open):
        if not hasattr(self, "file_tree"):
            return

        def recurse(item):
            for child in self.file_tree.get_children(item):
                if "folder" in self.file_tree.item(child, "tags"):
                    self.file_tree.item(child, open=is_open)
                recurse(child)

        recurse("")

    def expand_all_files(self):
        self._set_all_folders_open(True)

    def collapse_all_files(self):
        self._set_all_folders_open(False)

    def open_recording_directory(self):
        directory = self.directory.get().strip()
        if not directory or not os.path.isdir(directory):
            messagebox.showwarning("Directory", "The selected recording directory does not exist.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(directory)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", directory])
            else:
                subprocess.Popen(["xdg-open", directory])
        except Exception as exc:
            messagebox.showerror("Directory", f"Could not open directory:\n{exc}")

    def open_selected_file(self):
        selection = self.file_tree.selection()
        if not selection:
            return
        rel_path = selection[0]
        tags = self.file_tree.item(rel_path, "tags")
        path = os.path.join(self.directory.get().strip(), rel_path)
        if "folder" in tags:
            if not os.path.isdir(path):
                return
        else:
            if not os.path.isfile(path):
                return
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("Open", f"Could not open:\n{exc}")

    # ========================================================
    # RECORDER TAB
    # ========================================================

    def create_recorder_tab(self):
        tab = self.recorder_tab
        tab.configure(padding=0)
        tab.columnconfigure(0, weight=3, uniform="main")
        tab.columnconfigure(1, weight=7, uniform="main")
        tab.rowconfigure(0, weight=1)

        # LEFT 30%: recording status and vertically stacked parameter categories.
        left_host = ttk.Frame(tab)
        left_host.grid(row=0, column=0, sticky="nsew", padx=(8, 5), pady=8)
        left_host.columnconfigure(0, weight=1)
        left_host.rowconfigure(3, weight=1)

        current = ttk.LabelFrame(left_host, text="  CURRENT RECORDING  ", padding=12)
        current.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        current.columnconfigure(0, weight=1)
        self.status_label = tk.Label(current, textvariable=self.status, font=("Segoe UI", 11, "bold"),
                                     padx=10, pady=5, relief="flat", bd=0, highlightthickness=0, anchor="center")
        self.status_label.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(current, text="Elapsed", style="Muted.TLabel").grid(row=1, column=0, sticky="w")
        self.timer_label = tk.Label(current, textvariable=self.elapsed, font=("Consolas", 16, "bold"),
                                    relief="flat", bd=0, highlightthickness=0, anchor="w")
        self.timer_label.grid(row=2, column=0, sticky="w", pady=(0, 7))
        ttk.Label(current, text="Output file", style="Muted.TLabel").grid(row=3, column=0, sticky="w")
        self.file_label = tk.Label(current, textvariable=self.current_file, font=("Segoe UI", 9),
                                   anchor="w", justify="left", wraplength=300,
                                   relief="flat", bd=0, highlightthickness=0)
        self.file_label.grid(row=4, column=0, sticky="ew")

        # ACTIONS: deliberately kept directly under CURRENT RECORDING,
        # outside the scrollable parameter area.
        actions = ttk.LabelFrame(left_host, text="  ACTIONS  ", padding=10)
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.stop_button = ttk.Button(
            actions, text="■  STOP", style="Red.TButton",
            command=self.stop_recording, state="disabled"
        )
        self.stop_button.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=3)
        self.start_button = ttk.Button(
            actions, text="▶  START RECORDING", style="Green.TButton",
            command=self.start_recording
        )
        self.start_button.grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=3)
        ttk.Button(
            actions, text="Save Parameters", command=self.save_parameters
        ).grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(7, 3))
        ttk.Button(
            actions, text="Copy Command", command=self.copy_command
        ).grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(7, 3))

        # ICECAST PLAYER: local desktop player for the relay.
        player = ttk.LabelFrame(left_host, text="  ICECAST PLAYER  ", padding=10)
        player.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        player.columnconfigure(1, weight=1)

        ttk.Label(player, text="Stream URL", style="Muted.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self.player_url_entry = ttk.Entry(player, textvariable=self.player_url)
        self.player_url_entry.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(3, 7)
        )

        ttk.Button(
            player, text="▶  PLAY", command=self.play_icecast_gui
        ).grid(row=2, column=0, sticky="ew", padx=(0, 4), pady=2)

        ttk.Button(
            player, text="■  STOP", command=self.stop_icecast_gui
        ).grid(row=2, column=1, sticky="ew", padx=(4, 0), pady=2)

        ttk.Label(player, text="Volume", style="Muted.TLabel").grid(
            row=3, column=0, sticky="w", pady=(6, 0)
        )
        ttk.Scale(
            player, from_=0, to=100, variable=self.player_volume,
            orient="horizontal", command=self.on_player_volume_change
        ).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

        self.player_status_label = ttk.Label(
            player, text="Player stopped", style="Muted.TLabel"
        )
        self.player_status_label.grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(5, 0)
        )

        # STREAM SOURCE remains on the main Recorder tab.
        self.source = ttk.LabelFrame(left_host, text="  01  ·  STREAM SOURCE  ", padding=12)
        self.source.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self.source.columnconfigure(1, weight=1)
        ttk.Label(self.source, text="Stream URL", style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(self.source, textvariable=self.url).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(self.source, text="Directory", style="Panel.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(self.source, textvariable=self.directory).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(self.source, text="Browse", command=self.browse_directory).grid(row=1, column=2, padx=(7, 0), pady=4)
        ttk.Label(self.source, text="Station", style="Panel.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(self.source, textvariable=self.station).grid(row=2, column=1, sticky="ew", pady=4)

        # RIGHT 70%: full-height console.
        right = ttk.Frame(tab)
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 8), pady=8)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        log_header = ttk.Frame(right)
        log_header.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        log_header.columnconfigure(0, weight=1)
        ttk.Label(log_header, text="LIQUIDSOAP LOG", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(log_header, text="Clear", command=self.clear_log).grid(row=0, column=1, sticky="e")
        self.log_frame = ttk.Frame(right, style="Log.TFrame", padding=1)
        self.log_frame.grid(row=1, column=0, sticky="nsew")
        self.log_frame.rowconfigure(0, weight=1)
        self.log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(self.log_frame, font=("Consolas", 9), relief="flat", borderwidth=0,
                                wrap="none", padx=10, pady=10)
        scroll_y = ttk.Scrollbar(self.log_frame, orient="vertical", command=self.log_text.yview)
        scroll_x = ttk.Scrollbar(self.log_frame, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")


    # ========================================================
    # RECORDING OPTIONS TAB
    # ========================================================

    def create_options_tab(self):
        tab = self.options_tab
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

        left = ttk.Frame(tab)
        left.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        # RECORDING / ENCODING
        self.recording_frame = ttk.LabelFrame(left, text="  02  ·  RECORDING & ENCODING  ", padding=12)
        self.recording_frame.grid(row=0, column=0, sticky="new", pady=(0, 8))
        self.recording_frame.columnconfigure(1, weight=1)
        ttk.Checkbutton(self.recording_frame, text="Enable transcoding", variable=self.transcode,
                        style="Panel.TCheckbutton").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 7))
        self.add_combo(self.recording_frame, "Format", self.format, ["mp3", "m4a", "flac", "ogg", "opus"], 1)
        self.add_combo(self.recording_frame, "Codec", self.codec, ["libmp3lame", "aac", "flac", "libopus", "vorbis"], 2)
        self.add_combo(self.recording_frame, "Sample Rate", self.samplerate, ["22050", "32000", "44100", "48000", "96000"], 3)
        self.add_combo(self.recording_frame, "Bitrate", self.bitrate, ["64k", "96k", "128k", "160k", "192k", "256k", "320k"], 4)

        # OPTIONS
        self.options = ttk.LabelFrame(left, text="  03  ·  RECORDING OPTIONS  ", padding=12)
        self.options.grid(row=1, column=0, sticky="new", pady=(0, 8))
        self.options.columnconfigure(1, weight=1)
        ttk.Checkbutton(self.options, text="Listen", variable=self.listen, style="Panel.TCheckbutton").grid(row=0, column=0, sticky="w", pady=3)
        self.add_combo(self.options, "Device", self.device, ["portaudio", "alsa"], 1, column=1)
        ttk.Checkbutton(self.options, text="Keep incomplete", variable=self.keep, style="Panel.TCheckbutton").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Checkbutton(self.options, text="Create M3U", variable=self.m3u, style="Panel.TCheckbutton").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Checkbutton(self.options, text="Save covers", variable=self.covers, style="Panel.TCheckbutton").grid(row=4, column=0, sticky="w", pady=3)
        ttk.Checkbutton(self.options, text="Single track", variable=self.single, style="Panel.TCheckbutton").grid(row=5, column=0, sticky="w", pady=3)
        ttk.Label(self.options, text="Timeout", style="Panel.TLabel").grid(row=6, column=0, sticky="w", pady=3)
        ttk.Entry(self.options, textvariable=self.timeout).grid(row=6, column=1, sticky="ew", padx=(10, 0), pady=3)
        ttk.Label(self.options, text="TuneIn ID", style="Panel.TLabel").grid(row=7, column=0, sticky="w", pady=3)
        ttk.Entry(self.options, textvariable=self.tunein_id).grid(row=7, column=1, sticky="ew", padx=(10, 0), pady=3)
        ttk.Label(self.options, text="Log Level", style="Panel.TLabel").grid(row=8, column=0, sticky="w", pady=3)
        ttk.Combobox(self.options, textvariable=self.log_level, values=["0", "1", "2", "3", "4"], state="readonly").grid(row=8, column=1, sticky="ew", padx=(10, 0), pady=3)

        # ICECAST RELAY
        self.relay_frame = ttk.LabelFrame(left, text="  04  ·  ICECAST RELAY  ", padding=12)
        self.relay_frame.grid(row=2, column=0, sticky="new", pady=(0, 8))
        self.relay_frame.columnconfigure(1, weight=1)
        self.relay_frame.columnconfigure(3, weight=1)
        ttk.Checkbutton(self.relay_frame, text="Enable relay", variable=self.relay, style="Panel.TCheckbutton").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 7))
        ttk.Label(self.relay_frame, text="Host", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(self.relay_frame, textvariable=self.host).grid(row=1, column=1, sticky="ew", padx=(8, 12), pady=3)
        ttk.Label(self.relay_frame, text="Port", style="Panel.TLabel").grid(row=1, column=2, sticky="w", pady=3)
        ttk.Entry(self.relay_frame, textvariable=self.port).grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(self.relay_frame, text="Password", style="Panel.TLabel").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(self.relay_frame, textvariable=self.password, show="•").grid(row=2, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=3)

        right = ttk.Frame(tab)
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=0)
        right.rowconfigure(1, weight=0)
        right.rowconfigure(2, weight=1)

        # WEB SERVER
        web_frame = ttk.LabelFrame(right, text="  05  ·  WEB OPTIONS  ", padding=12)
        web_frame.grid(row=0, column=0, sticky="new", pady=(0, 8))
        web_frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            web_frame,
            text="Enable Web Interface",
            variable=self.web_enabled,
            style="Panel.TCheckbutton"
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ttk.Label(web_frame, text="Bind Host", style="Panel.TLabel").grid(
            row=1, column=0, sticky="w", pady=4
        )
        ttk.Entry(web_frame, textvariable=self.web_host).grid(
            row=1, column=1, sticky="ew", padx=(10, 0), pady=4
        )

        ttk.Label(web_frame, text="Port", style="Panel.TLabel").grid(
            row=2, column=0, sticky="w", pady=4
        )
        ttk.Entry(web_frame, textvariable=self.web_port).grid(
            row=2, column=1, sticky="ew", padx=(10, 0), pady=4
        )

        self.web_status_label = ttk.Label(
            web_frame,
            text="Web server: STOPPED",
            style="Panel.TLabel"
        )
        self.web_status_label.grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(10, 5)
        )

        buttons = ttk.Frame(web_frame)
        buttons.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Button(buttons, text="Start Web Server", command=self.start_web_server).pack(
            side="left", padx=(0, 5)
        )
        ttk.Button(buttons, text="Stop Web Server", command=self.stop_web_server).pack(
            side="left", padx=5
        )
        ttk.Button(buttons, text="Open Browser", command=self.open_web_browser).pack(
            side="left", padx=5
        )

        info = ttk.LabelFrame(right, text="  WEB INTERFACE  ", padding=12)
        info.grid(row=1, column=0, sticky="nsew")
        info.columnconfigure(0, weight=1)

        ttk.Label(
            info,
            text=(
                "The browser interface controls the same Liquidsoap "
                "recording process as the desktop application."
            ),
            style="Panel.TLabel",
            wraplength=450,
            justify="left"
        ).grid(row=0, column=0, sticky="w", pady=5)

        ttk.Label(
            info,
            text=(
                "For LAN access, use Bind Host 0.0.0.0 and open "
                "http://<computer-ip>:<port>/"
            ),
            style="Panel.TLabel",
            wraplength=450,
            justify="left"
        ).grid(row=1, column=0, sticky="w", pady=5)

        ttk.Label(
            info,
            text="The browser log is updated automatically every second.",
            style="Panel.TLabel",
            wraplength=450,
            justify="left"
        ).grid(row=2, column=0, sticky="w", pady=5)

    # ========================================================
    # LOCAL ICECAST PLAYER
    # ========================================================

    def get_icecast_player_url(self):
        host = str(self.host.get()).strip() or "127.0.0.1"
        port = str(self.port.get()).strip() or "8000"
        if host in ("0.0.0.0", "localhost"):
            host = "127.0.0.1"
        return f"http://{host}:{port}/stream"

    def play_icecast_gui(self):
        url = self.player_url.get().strip()
        if not url:
            url = self.get_icecast_player_url()
            self.player_url.set(url)

        self.stop_icecast_gui(silent=True)
        volume = max(0, min(100, int(float(self.player_volume.get()))))

        mpv = shutil.which("mpv")
        ffplay = shutil.which("ffplay")

        try:
            if mpv:
                cmd = [mpv, "--no-video", "--really-quiet",
                       f"--volume={volume}", url]
                player_name = "mpv"
            elif ffplay:
                cmd = [ffplay, "-nodisp", "-loglevel", "warning",
                       "-volume", str(volume), url]
                player_name = "ffplay"
            else:
                self.player_status_label.configure(
                    text="Install mpv or ffplay to use the player."
                )
                return

            # Launch the local player without creating a visible console/window.
            startupinfo = None
            creationflags = 0

            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW

            self.player_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
            self.player_backend = player_name
            self.player_status_label.configure(
                text=f"Playing relay with {player_name}"
            )
            self.root.after(1000, self.check_icecast_player)
        except Exception as exc:
            self.player_process = None
            self.player_status_label.configure(text=f"Player error: {exc}")

    def on_player_volume_change(self, _value=None):
        """Apply the GUI volume to the local Icecast player.

        ffplay only reads its -volume option when it starts, so while it is
        running we debounce the slider and restart ffplay with the new level.
        This makes the Tkinter volume slider actually control ffplay playback.
        """
        if self.player_process is None:
            return

        if self.player_volume_job is not None:
            try:
                self.root.after_cancel(self.player_volume_job)
            except Exception:
                pass

        self.player_volume_job = self.root.after(250, self._apply_player_volume)

    def _apply_player_volume(self):
        self.player_volume_job = None

        process = self.player_process
        if process is None or process.poll() is not None:
            return

        if self.player_backend not in ("ffplay", "mpv"):
            return

        url = self.player_url.get().strip() or self.get_icecast_player_url()
        volume = max(0, min(100, int(float(self.player_volume.get()))))

        # ffplay has no supported runtime volume API, so restart it with the
        # new -volume value.  A short debounce prevents repeated reconnects
        # while the slider is being dragged.
        self.stop_icecast_gui(silent=True)
        self.player_url.set(url)
        self.play_icecast_gui()

    def check_icecast_player(self):
        process = self.player_process
        if process is None:
            return
        if process.poll() is not None:
            self.player_process = None
            self.player_backend = None
            self.player_status_label.configure(text="Player stopped")
            return
        self.root.after(1000, self.check_icecast_player)

    def stop_icecast_gui(self, silent=False):
        process = self.player_process
        self.player_process = None
        self.player_backend = None
        if self.player_volume_job is not None:
            try:
                self.root.after_cancel(self.player_volume_job)
            except Exception:
                pass
            self.player_volume_job = None
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
            except Exception:
                pass
        if hasattr(self, "player_status_label") and not silent:
            self.player_status_label.configure(text="Player stopped")

    # ========================================================
    # HELPERS
    # ========================================================

    def add_combo(
        self,
        parent,
        label,
        variable,
        values,
        row,
        column=1
    ):

        ttk.Label(
            parent,
            text=label,
            style="Panel.TLabel"
        ).grid(
            row=row,
            column=0,
            sticky="w"
        )

        ttk.Combobox(
            parent,
            textvariable=variable,
            values=values,
            state="readonly"
        ).grid(
            row=row,
            column=column,
            sticky="ew",
            padx=(10, 0)
        )

    # ========================================================
    # THEME
    # ========================================================

    def toggle_theme(self):

        self.dark_mode = not self.dark_mode

        if self.dark_mode:

            self.colors = self.themes["dark"]

            self.theme_text.set(
                "☀  Light"
            )

        else:

            self.colors = self.themes["light"]

            self.theme_text.set(
                "☾  Dark"
            )

        self.apply_theme()

    def apply_theme(self):

        c = self.colors

        self.root.configure(
            bg=c["bg"]
        )

        self.root.option_add(
            "*insertBackground",
            c["text"]
        )

        self.root.option_add(
            "*insertWidth",
            2
        )

        self.header.configure(
            bg=c["bg"]
        )

        self.version_frame.configure(
            bg=c["bg"]
        )

        self.liquidsoap_version_label.configure(
            bg=c["bg"],
            fg=c["muted"]
        )

        self.record_liq_version_label.configure(
            bg=c["bg"],
            fg=c["muted"]
        )

        self.title_label.configure(
            bg=c["bg"],
            fg=c["text"]
        )

        self.theme_button.configure(
            bg=c["button"],
            fg=c["button_fg"],
            activebackground=c["select"],
            activeforeground=c["text"]
        )

        self.style.configure(
            "TFrame",
            background=c["bg"]
        )

        self.style.configure(
            "TLabel",
            background=c["bg"],
            foreground=c["text"]
        )

        self.style.configure(
            "TLabelframe",
            background=c["panel"],
            foreground=c["text"],
            bordercolor=c["border"]
        )

        self.style.configure(
            "TLabelframe.Label",
            background=c["panel"],
            foreground=c["text"]
        )

        self.style.configure(
            "Panel.TLabel",
            background=c["panel"],
            foreground=c["text"]
        )

        self.style.configure("Muted.TLabel", background=c["panel"], foreground=c["muted"])
        self.style.configure("Section.TLabel", background=c["bg"], foreground=c["text"])
        self.style.configure("Log.TFrame", background=c["border"])

        self.style.configure(
            "Muted.TLabel",
            background=c["panel"],
            foreground=c["muted"]
        )

        self.style.configure(
            "Section.TLabel",
            background=c["bg"],
            foreground=c["text"]
        )

        self.style.configure(
            "Log.TFrame",
            background=c["border"]
        )

        self.style.configure(
            "Panel.TCheckbutton",
            background=c["panel"],
            foreground=c["text"]
        )

        self.style.configure(
            "TEntry",
            fieldbackground=c["entry"],
            foreground=c["text"],
            insertcolor=c["text"]
        )

        self.style.configure(
            "TCombobox",
            fieldbackground=c["entry"],
            background=c["entry"],
            foreground=c["text"],
            insertcolor=c["text"]
        )

        self.style.map(
            "TCombobox",
            fieldbackground=[
                ("readonly", c["entry"])
            ],
            foreground=[
                ("readonly", c["text"])
            ]
        )

        self.style.configure(
            "TCheckbutton",
            background=c["panel"],
            foreground=c["text"]
        )

        self.style.configure(
            "Treeview",
            background=c["entry"],
            fieldbackground=c["entry"],
            foreground=c["text"],
            bordercolor=c["border"],
            borderwidth=0
        )

        self.style.map(
            "Treeview",
            background=[
                ("selected", c["select"])
            ],
            foreground=[
                ("selected", c["text"])
            ]
        )

        self.style.configure(
            "Treeview.Heading",
            background=c["panel2"],
            foreground=c["text"],
            bordercolor=c["border"],
            relief="flat"
        )

        self.style.map(
            "Treeview.Heading",
            background=[
                ("active", c["select"])
            ]
        )

        self.style.configure(
            "TButton",
            background=c["button"],
            foreground=c["button_fg"]
        )

        self.style.map(
            "TButton",
            background=[
                ("active", c["select"])
            ]
        )

        self.style.configure(
            "Green.TButton",
            background=c["green"],
            foreground="#ffffff"
        )

        self.style.configure(
            "Red.TButton",
            background=c["red"],
            foreground="#ffffff"
        )

        if hasattr(self, "parameter_panel"):
            self.parameter_panel.configure(style="TFrame")

        if hasattr(self, "log_frame"):
            self.log_frame.configure(style="Log.TFrame")

        self.log_text.configure(
            bg=c["log_bg"],
            fg=c["log_fg"],
            insertbackground=c["text"],
            insertwidth=2,
            selectbackground=c["select"],
            selectforeground=c["text"]
        )

        self.timer_label.configure(
            bg=c["bg"],
            fg=c["text"]
        )

        self.file_label.configure(
            bg=c["bg"],
            fg=c["text"]
        )

        if self.recording:

            self.status_label.configure(
                bg=c["green_dark"],
                fg=c["green"]
            )

        else:

            self.status_label.configure(
                bg=c["red_dark"],
                fg=c["red"]
            )

    # ========================================================
    # PARAMETER PERSISTENCE
    # ========================================================

    def load_saved_parameters(self):

        try:

            if not os.path.isfile(
                PARAMETERS_FILE
            ):
                return {}

            with open(
                PARAMETERS_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            return (
                data
                if isinstance(data, dict)
                else {}
            )

        except Exception:
            return {}

    def save_persistent_parameters(self):

        try:

            # Command-line arguments are temporary runtime overrides.
            # Do not let them overwrite the user's persistent settings
            # when the application closes.
            cli_overrides = getattr(
                getattr(self, "args", None),
                "_cli_overrides",
                set()
            )

            saved = self.load_saved_parameters()
            current = self.get_parameters()

            current["web"] = (
                self.web_enabled.get()
            )

            current["web_host"] = (
                self.web_host.get()
            )

            current["web_port"] = (
                self.web_port.get()
            )

            try:
                current["window_geometry"] = (
                    self.root.geometry()
                )
            except tk.TclError:
                pass

            # Start with the current GUI values, then restore the saved
            # value for every option explicitly supplied on the CLI.
            data = dict(current)
            for key in cli_overrides:
                if key in saved:
                    data[key] = saved[key]

            # start_recording is a command-line action, not a persistent
            # preference, so never store it.
            data.pop("start_recording", None)

            tmp = (
                PARAMETERS_FILE
                + ".tmp"
            )

            with open(
                tmp,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    data,
                    f,
                    indent=2,
                    ensure_ascii=False
                )

            os.replace(
                tmp,
                PARAMETERS_FILE
            )

            return True

        except Exception as e:

            self.write_log(
                "[GUI] Could not save persistent "
                "parameters: " + str(e)
            )

            return False

    # ========================================================
    # VERSION INFO
    # ========================================================

    def update_versions(self):

        self.liquidsoap_version.set(
            "Liquidsoap: "
            + self.detect_liquidsoap_version()
        )

        self.record_liq_version.set(
            "record.liq: "
            + self.detect_record_liq_version()
        )

    def detect_liquidsoap_version(self):

        try:

            result = subprocess.run(
                [
                    "liquidsoap",
                    "--version"
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
                check=False
            )

            output = (
                result.stdout or ""
            ).strip()

            if output:

                return (
                    output
                    .splitlines()[0]
                    .strip()
                )

            return "not found"

        except (
            FileNotFoundError,
            OSError
        ):

            return "not found"

        except Exception:

            return "unknown"

    def detect_record_liq_version(self):

        candidates = [

            os.path.join(
                os.getcwd(),
                "record.liq"
            ),

            os.path.join(
                os.path.dirname(
                    os.path.abspath(__file__)
                ),
                "record.liq"
            )
        ]

        path = next(
            (
                p
                for p in candidates
                if os.path.isfile(p)
            ),
            None
        )

        if not path:
            return "not found"

        try:

            with open(
                path,
                "r",
                encoding="utf-8",
                errors="replace"
            ) as f:

                for line in f:

                    stripped = line.strip()
                    lower = stripped.lower()

                    if "version" in lower:

                        import re

                        match = re.search(
                            r"version\s*[:=]?\s*v?"
                            r"([0-9]+(?:\.[0-9]+)+"
                            r"(?:[-+._a-zA-Z0-9]*)?)",
                            stripped,
                            re.IGNORECASE
                        )

                        if match:
                            return match.group(1)

            return "version not specified"

        except Exception:

            return "unreadable"

    # ========================================================
    # DIRECTORY
    # ========================================================

    def browse_directory(self):

        directory = filedialog.askdirectory(
            title="Select Recording Directory"
        )

        if directory:
            self.directory.set(
                directory
            )
            self.refresh_file_list()

    # ========================================================
    # COMMAND
    # ========================================================

    def build_command(self):

        url = self.url.get().strip()
        directory = self.directory.get().strip()

        if not url:
            raise ValueError(
                "Stream URL is required."
            )

        if not directory:
            raise ValueError(
                "Recording directory is required."
            )

        return [

            "liquidsoap",
            "record.liq",
            "--",

            "-url",
            url,

            "-dir",
            directory,

            "-station",
            self.station.get().strip() or " ",

            "-transcode",
            "1"
            if self.transcode.get()
            else "0",

            "-samplerate",
            self.samplerate.get().strip(),

            "-format",
            self.format.get().strip(),

            "-codec",
            self.codec.get().strip(),

            "-bitrate",
            self.bitrate.get().strip(),

            "-listen",
            "1"
            if self.listen.get()
            else "0",

            "-device",
            self.device.get().strip(),

            "-log",
            self.log_level.get().strip(),

            "-keep",
            "1"
            if self.keep.get()
            else "0",

            "-id",
            self.tunein_id.get().strip()
            or " ",

            "-relay",
            "1"
            if self.relay.get()
            else "0",

            "-host",
            self.host.get().strip(),

            "-port",
            self.port.get().strip(),

            "-password",
            self.password.get(),

            "-m3u",
            "1"
            if self.m3u.get()
            else "0",

            "-covers",
            "1"
            if self.covers.get()
            else "0",

            "-single",
            "1"
            if self.single.get()
            else "0",

            "-timeout",
            self.timeout.get().strip()
            or "0"
        ]

    def format_command(self, command):

        result = []

        for value in command:

            value = str(value)

            if (
                not value
                or " " in value
                or "\t" in value
                or '"' in value
            ):

                value = (
                    '"'
                    + value.replace(
                        '"',
                        '\\"'
                    )
                    + '"'
                )

            result.append(value)

        return " ".join(result)

    def copy_command(self):

        try:

            command = self.build_command()

        except ValueError as e:

            messagebox.showerror(
                "Configuration Error",
                str(e)
            )

            return

        self.root.clipboard_clear()

        self.root.clipboard_append(
            self.format_command(command)
        )

        self.write_log(
            "[GUI] Command copied to clipboard."
        )

    # ========================================================
    # SAVE PARAMETERS
    # ========================================================

    def save_parameters(self):

        if self.recording or self.stopping:

            messagebox.showwarning(
                "Recording Active",
                "Stop the recording before "
                "changing parameters."
            )

            return False

        result = (
            self.web_update_parameters(
                self.get_parameters()
            )
        )

        if not result.get("ok"):

            messagebox.showerror(
                "Save Parameters",
                result.get(
                    "error",
                    "Could not save parameters."
                )
            )

            return False

        self.save_persistent_parameters()

        self.write_log(
            "[GUI] Parameters saved."
        )

        messagebox.showinfo(
            "Save Parameters",
            "Parameters saved."
        )

        return True

    # ========================================================
    # START
    # ========================================================

    def start_recording(self):

        if self.process is not None:

            messagebox.showwarning(
                "Already Running",
                "Liquidsoap is already running."
            )

            return False

        if self.stopping:

            messagebox.showwarning(
                "Stopping",
                "Liquidsoap is still shutting down."
            )

            return False

        try:

            command = self.build_command()

        except ValueError as e:

            messagebox.showerror(
                "Configuration Error",
                str(e)
            )

            return False

        self._start_process(
            command
        )

        return True

    def _start_process(self, command):

        self.clear_log()

        self.current_file.set("-")

        self.write_log(
            "=" * 100
        )

        self.write_log(
            "LIQUIDSOAP RECORD"
        )

        self.write_log(
            "Started: "
            + datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        self.write_log(
            "Command:"
        )

        self.write_log(
            self.format_command(command)
        )

        self.write_log(
            "=" * 100
        )

        try:

            creationflags = 0

            if os.name == "nt":

                creationflags = (
                    subprocess.CREATE_NO_WINDOW
                    |
                    subprocess.CREATE_NEW_PROCESS_GROUP
                )

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                universal_newlines=True,
                creationflags=creationflags
            )

            self.process = process

        except FileNotFoundError:

            self.process = None

            self.write_log(
                "[ERROR] Liquidsoap was not found."
            )

            messagebox.showerror(
                "Liquidsoap Not Found",
                (
                    "Liquidsoap was not found.\n\n"
                    "Make sure liquidsoap is in PATH "
                    "or start this program from the "
                    "Liquidsoap directory."
                )
            )

            return

        except Exception as e:

            self.process = None

            self.write_log(
                "[ERROR] " + str(e)
            )

            messagebox.showerror(
                "Start Error",
                str(e)
            )

            return

        self.recording = True
        self.stopping = False

        self.start_time = datetime.now()

        self.status.set(
            "RECORDING"
        )

        self.status_label.configure(
            bg=self.colors["green_dark"],
            fg=self.colors["green"]
        )

        self.start_button.configure(
            state="disabled"
        )

        self.stop_button.configure(
            state="normal"
        )

        self.output_thread = threading.Thread(
            target=self.read_output,
            args=(process,),
            daemon=True
        )

        self.output_thread.start()

    # ========================================================
    # OUTPUT
    # ========================================================

    def read_output(self, process=None):

        if process is None:
            process = self.process

        if process is None:
            return

        try:

            if process.stdout is not None:

                for line in iter(
                    process.stdout.readline,
                    ""
                ):

                    if not line:
                        break

                    line = line.rstrip(
                        "\r\n"
                    )

                    if line:
                        self.log_queue.put(
                            line
                        )

                    self.parse_log_line(
                        line
                    )

        except Exception as e:

            self.log_queue.put(
                "[GUI] Output reader error: "
                + str(e)
            )

        finally:

            try:

                if process.stdout is not None:
                    process.stdout.close()

            except Exception:
                pass

            try:

                return_code = process.wait()

            except Exception:

                return_code = -1

            self.log_queue.put(
                "[GUI] Liquidsoap exited "
                "with code "
                + str(return_code)
            )

            self.root.after(
                0,
                lambda p=process:
                self._process_finished(p)
            )

    def parse_log_line(self, line):

        lower = line.lower()

        if "recording.." in lower:

            try:

                pos = lower.find(
                    "recording.."
                )

                value = line[
                    pos
                    + len("recording.."):
                ].strip()

                if value:

                    self.root.after(
                        0,
                        lambda v=value:
                        self.current_file.set(v)
                    )

            except Exception:
                pass

    # ========================================================
    # LIQUIDSOAP COMMAND SERVER
    # ========================================================

    def send_liquidsoap_command(
        self,
        command,
        host=LIQUIDSOAP_HOST,
        port=LIQUIDSOAP_PORT
    ):

        conn = None

        try:

            conn = http.client.HTTPConnection(
                host,
                port,
                timeout=5
            )

            conn.request(
                "GET",
                "/" + command
            )

            resp = conn.getresponse()

            try:

                response = resp.read().decode(
                    "utf-8",
                    errors="replace"
                ).strip()

            except socket.timeout:

                response = ""

            if response:

                self.log_queue.put(
                    "[GUI] Liquidsoap response: "
                    + response
                )

            return resp.status == 200

        except ConnectionRefusedError:

            self.log_queue.put(
                "[GUI] Could not connect to Liquidsoap "
                f"command server on {host}:{port}."
            )

            return False

        except (socket.timeout, TimeoutError):

            self.log_queue.put(
                "[GUI] Timeout connecting to Liquidsoap "
                f"command server on {host}:{port}."
            )

            return False

        except Exception as e:

            self.log_queue.put(
                "[GUI] Liquidsoap command error: "
                + str(e)
            )

            return False

        finally:

            if conn is not None:
                conn.close()

    # ========================================================
    # STOP
    # ========================================================

    def stop_recording(
        self,
        graceful_timeout=GRACEFUL_STOP_TIMEOUT
    ):

        process = self.process

        if process is None:
            return False

        if self.stopping:

            self.write_log(
                "[GUI] Liquidsoap shutdown "
                "already in progress."
            )

            return True

        if process.poll() is not None:

            self.root.after(
                0,
                lambda p=process:
                self._process_finished(p)
            )

            return True

        self.stopping = True

        self.write_log(
            "[GUI] Requesting graceful "
            "Liquidsoap shutdown..."
        )

        graceful_signal_sent = False

        self.write_log(
            "[GUI] Sending Liquidsoap "
            "'stop_all' command "
            f"to {LIQUIDSOAP_HOST}:{LIQUIDSOAP_PORT}..."
        )

        if self.send_liquidsoap_command(
            "stop_all"
        ):

            graceful_signal_sent = True

            self.write_log(
                "[GUI] Liquidsoap 'stop_all' "
                "command sent."
            )

        else:

            self.write_log(
                "[GUI] Could not send 'stop_all'."
            )

        if not graceful_signal_sent:

            try:

                if os.name == "nt":

                    process.send_signal(
                        signal.CTRL_BREAK_EVENT
                    )

                    self.write_log(
                        "[GUI] CTRL_BREAK_EVENT sent."
                    )

                else:

                    process.send_signal(
                        signal.SIGINT
                    )

                    self.write_log(
                        "[GUI] SIGINT sent."
                    )

                graceful_signal_sent = True

            except Exception as e:

                self.write_log(
                    "[GUI] Could not send graceful "
                    "stop signal: "
                    + str(e)
                )

        self.status.set(
            "STOPPING..."
        )

        self.stop_button.configure(
            state="disabled"
        )

        self.start_button.configure(
            state="disabled"
        )

        self.stop_thread = threading.Thread(
            target=self._wait_for_graceful_stop,
            args=(
                process,
                graceful_timeout
            ),
            daemon=True
        )

        self.stop_thread.start()

        return True

    def _wait_for_graceful_stop(
        self,
        process,
        graceful_timeout
    ):

        try:

            if process.poll() is not None:

                self.root.after(
                    0,
                    lambda p=process:
                    self._process_finished(p)
                )

                return

            if graceful_timeout > 0:

                return_code = process.wait(
                    timeout=graceful_timeout
                )

                self.log_queue.put(
                    "[GUI] Liquidsoap exited "
                    "gracefully with code "
                    f"{return_code}."
                )

                self.root.after(
                    0,
                    lambda p=process:
                    self._process_finished(p)
                )

                return

        except subprocess.TimeoutExpired:

            self.log_queue.put(
                "[GUI] Graceful shutdown timed "
                f"out after {graceful_timeout} seconds."
            )

        except Exception as e:

            self.log_queue.put(
                "[GUI] Error waiting for Liquidsoap: "
                + str(e)
            )

        if process.poll() is not None:

            self.root.after(
                0,
                lambda p=process:
                self._process_finished(p)
            )

            return

        self.log_queue.put(
            "[GUI] Liquidsoap did not exit gracefully."
        )

        self.log_queue.put(
            "[GUI] Attempting terminate()..."
        )

        try:

            process.terminate()

            return_code = process.wait(
                timeout=FORCE_TERMINATE_TIMEOUT
            )

            self.log_queue.put(
                "[GUI] Liquidsoap terminated "
                "with code "
                + str(return_code)
            )

        except subprocess.TimeoutExpired:

            self.log_queue.put(
                "[GUI] terminate() timed out."
            )

            self._force_stop_process(
                process
            )

        except Exception as e:

            self.log_queue.put(
                "[GUI] terminate() failed: "
                + str(e)
            )

            self._force_stop_process(
                process
            )

        finally:

            self.root.after(
                0,
                lambda p=process:
                self._process_finished(p)
            )

    def _force_stop_process(
        self,
        process
    ):

        if process.poll() is not None:
            return

        if os.name == "nt":

            self.log_queue.put(
                "[GUI] Attempting taskkill /T /F..."
            )

            try:

                result = subprocess.run(
                    [
                        "taskkill",
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F"
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=FORCE_TERMINATE_TIMEOUT
                )

                output = (
                    result.stdout or ""
                ).strip()

                if output:

                    self.log_queue.put(
                        "[GUI] taskkill: "
                        + output
                    )

                try:

                    return_code = process.wait(
                        timeout=FORCE_TERMINATE_TIMEOUT
                    )

                    self.log_queue.put(
                        "[GUI] Liquidsoap stopped "
                        "with code "
                        + str(return_code)
                    )

                    return

                except subprocess.TimeoutExpired:
                    pass

            except Exception as e:

                self.log_queue.put(
                    "[GUI] taskkill failed: "
                    + str(e)
                )

        try:

            if process.poll() is None:

                self.log_queue.put(
                    "[GUI] Attempting kill()..."
                )

                process.kill()

                return_code = process.wait(
                    timeout=FORCE_TERMINATE_TIMEOUT
                )

                self.log_queue.put(
                    "[GUI] Liquidsoap killed "
                    "with code "
                    + str(return_code)
                )

        except Exception as e:

            self.log_queue.put(
                "[GUI] kill() failed: "
                + str(e)
            )

    # ========================================================
    # PROCESS FINISHED
    # ========================================================

    def _process_finished(
        self,
        process
    ):

        if self.process is not process:
            return

        self.process = None

        self.recording = False
        self.stopping = False

        self.start_time = None

        self.status.set(
            "STOPPED"
        )

        self.status_label.configure(
            bg=self.colors["red_dark"],
            fg=self.colors["red"]
        )

        self.elapsed.set(
            "00:00:00"
        )

        self.start_button.configure(
            state="normal"
        )

        self.stop_button.configure(
            state="disabled"
        )

        self.write_log(
            "[GUI] Recording stopped."
        )

        if self.closing:

            self.root.after(
                0,
                self.force_close
            )

    def process_finished(self):

        if self.process is not None:

            self._process_finished(
                self.process
            )

    # ========================================================
    # TIMER
    # ========================================================

    def update_timer(self):

        if (
            self.recording
            and self.start_time
        ):

            seconds = int(
                (
                    datetime.now()
                    - self.start_time
                ).total_seconds()
            )

            hours = seconds // 3600

            minutes = (
                seconds % 3600
            ) // 60

            secs = seconds % 60

            self.elapsed.set(
                f"{hours:02d}:"
                f"{minutes:02d}:"
                f"{secs:02d}"
            )

        self.root.after(
            500,
            self.update_timer
        )

    # ========================================================
    # LOG
    # ========================================================

    def write_log(self, text):

        text = str(text)

        with self.log_lock:

            self.log_lines.append(
                text
            )

            if len(self.log_lines) > 5000:

                self.log_lines = (
                    self.log_lines[-5000:]
                )

        try:

            if (
                hasattr(self, "log_text")
                and threading.current_thread()
                is threading.main_thread()
            ):

                self.log_text.insert(
                    "end",
                    text + "\n"
                )

                self.log_text.see(
                    "end"
                )

        except Exception:
            pass

    def get_log(self):

        with self.log_lock:
            return list(
                self.log_lines
            )

    def clear_log(self):

        with self.log_lock:
            self.log_lines.clear()

        if hasattr(
            self,
            "log_text"
        ):

            self.log_text.delete(
                "1.0",
                "end"
            )

    # ========================================================
    # GUI QUEUE
    # ========================================================

    def process_gui_queue(self):

        try:

            while True:

                line = (
                    self.log_queue.get_nowait()
                )

                self.write_log(
                    line
                )

        except queue.Empty:
            pass

        try:

            self.root.after(
                100,
                self.process_gui_queue
            )

        except tk.TclError:
            pass

    # ========================================================
    # WEB SERVER CONTROL
    # ========================================================

    def start_web_server(self):

        try:

            host = (
                self.web_host.get().strip()
            )

            if not host:
                host = DEFAULT_WEB_HOST

            port = int(
                self.web_port.get().strip()
            )

            if port < 1 or port > 65535:

                raise ValueError(
                    "Web port must be between "
                    "1 and 65535."
                )

        except Exception as e:

            messagebox.showerror(
                "Web Server Error",
                str(e)
            )

            return False

        if self.web_server is not None:

            self.write_log(
                "[WEB] Server is already running."
            )

            return True

        try:

            self.web_server = (
                RecorderWebServer(
                    self,
                    host,
                    port
                )
            )

            self.web_server.start()

            self.web_enabled.set(
                True
            )

            self.web_status_label.configure(
                text=(
                    "Web server: RUNNING - "
                    f"{host}:{port}"
                )
            )

            return True

        except OSError as e:

            self.web_server = None

            self.web_status_label.configure(
                text="Web server: STOPPED"
            )

            messagebox.showerror(
                "Web Server Error",
                "Could not start web server.\n\n"
                + str(e)
            )

            return False

    def stop_web_server(self):

        if self.web_server is None:

            self.web_status_label.configure(
                text="Web server: STOPPED"
            )

            return

        self.web_server.stop()

        self.web_server = None

        self.web_status_label.configure(
            text="Web server: STOPPED"
        )

        self.web_enabled.set(
            False
        )

    def open_web_browser(self):

        try:

            port = int(
                self.web_port.get().strip()
            )

        except Exception:

            port = DEFAULT_WEB_PORT

        webbrowser.open(
            f"http://127.0.0.1:{port}/"
        )

    # ========================================================
    # WEB STATUS
    # ========================================================

    def get_status(self):

        elapsed_seconds = 0

        if (
            self.recording
            and self.start_time
        ):

            elapsed_seconds = int(
                (
                    datetime.now()
                    - self.start_time
                ).total_seconds()
            )

        hours = elapsed_seconds // 3600

        minutes = (
            elapsed_seconds % 3600
        ) // 60

        seconds = (
            elapsed_seconds
            % 60
        )

        return {

            "recording":
                self.recording,

            "stopping":
                self.stopping,

            "status": (
                "STOPPING..."
                if self.stopping
                else (
                    "RECORDING"
                    if self.recording
                    else "STOPPED"
                )
            ),

            "elapsed": (
                f"{hours:02d}:"
                f"{minutes:02d}:"
                f"{seconds:02d}"
            ),

            "elapsed_seconds":
                elapsed_seconds,

            "file":
                self.current_file.get(),

            "url":
                self.url.get(),

            "station":
                self.station.get()
        }

    # ========================================================
    # WEB PARAMETERS
    # ========================================================

    def get_parameters(self):

        return {

            "url":
                self.url.get(),

            "directory":
                self.directory.get(),

            "station":
                self.station.get(),

            "transcode":
                self.transcode.get(),

            "samplerate":
                self.samplerate.get(),

            "format":
                self.format.get(),

            "codec":
                self.codec.get(),

            "bitrate":
                self.bitrate.get(),

            "listen":
                self.listen.get(),

            "device":
                self.device.get(),

            "log_level":
                self.log_level.get(),

            "keep":
                self.keep.get(),

            "timeout":
                self.timeout.get(),

            "tunein_id":
                self.tunein_id.get(),

            "relay":
                self.relay.get(),

            "host":
                self.host.get(),

            "port":
                self.port.get(),

            "password":
                self.password.get(),

            "m3u":
                self.m3u.get(),

            "covers":
                self.covers.get(),

            "single":
                self.single.get()
        }

    @staticmethod
    def as_bool(value):

        if isinstance(
            value,
            bool
        ):
            return value

        if isinstance(
            value,
            int
        ):
            return value != 0

        if isinstance(
            value,
            str
        ):

            return (
                value.strip().lower()
                in {
                    "1",
                    "true",
                    "yes",
                    "on"
                }
            )

        return bool(value)

    def web_update_parameters(
        self,
        data
    ):

        if (
            self.recording
            or self.stopping
        ):

            return {

                "ok": False,

                "error": (
                    "Stop the recording before "
                    "changing parameters."
                )
            }

        if not isinstance(
            data,
            dict
        ):

            return {

                "ok": False,

                "error":
                    "Parameters must be a JSON object."
            }

        try:

            string_fields = [

                "url",
                "directory",
                "station",

                "samplerate",
                "format",
                "codec",
                "bitrate",

                "device",
                "log_level",
                "timeout",

                "tunein_id",

                "host",
                "port",
                "password"
            ]

            boolean_fields = [

                "transcode",
                "listen",
                "keep",
                "relay",
                "m3u",
                "covers",
                "single"
            ]

            variables = {

                "url":
                    self.url,

                "directory":
                    self.directory,

                "station":
                    self.station,

                "samplerate":
                    self.samplerate,

                "format":
                    self.format,

                "codec":
                    self.codec,

                "bitrate":
                    self.bitrate,

                "device":
                    self.device,

                "log_level":
                    self.log_level,

                "timeout":
                    self.timeout,

                "tunein_id":
                    self.tunein_id,

                "host":
                    self.host,

                "port":
                    self.port,

                "password":
                    self.password
            }

            for name in string_fields:

                if name in data:

                    variables[name].set(
                        str(data[name])
                    )

            boolean_variables = {

                "transcode":
                    self.transcode,

                "listen":
                    self.listen,

                "keep":
                    self.keep,

                "relay":
                    self.relay,

                "m3u":
                    self.m3u,

                "covers":
                    self.covers,

                "single":
                    self.single
            }

            for name in boolean_fields:

                if name in data:

                    boolean_variables[name].set(
                        self.as_bool(
                            data[name]
                        )
                    )

            self.root.after(
                0,
                self.refresh_gui
            )

            self.save_persistent_parameters()

            self.write_log(
                "[WEB] Parameters updated."
            )

            return {

                "ok": True,

                "parameters":
                    self.get_parameters()
            }

        except Exception as e:

            return {

                "ok": False,

                "error":
                    str(e)
            }

    # ========================================================
    # WEB START / STOP
    # ========================================================

    def web_start(
        self,
        data
    ):

        if self.recording:

            return {

                "ok": False,

                "error":
                    "Already recording."
            }

        if self.stopping:

            return {

                "ok": False,

                "error":
                    "Liquidsoap is still stopping."
            }

        result = (
            self.web_update_parameters(
                data
            )
        )

        if not result.get("ok"):
            return result

        try:

            command = self.build_command()

        except ValueError as e:

            return {

                "ok": False,

                "error":
                    str(e)
            }

        self.write_log(
            "[WEB] Start recording requested."
        )

        self.root.after(
            0,
            lambda cmd=command:
            self._start_process(cmd)
        )

        return {

            "ok": True,

            "message":
                "Recording start requested."
        }

    def web_stop(self):

        if not self.recording:

            if self.stopping:

                return {

                    "ok": True,

                    "message":
                        "Liquidsoap is already stopping."
                }

            return {

                "ok": False,

                "error":
                    "Not recording."
            }

        self.write_log(
            "[WEB] Stop recording requested."
        )

        self.root.after(
            0,
            self.stop_recording
        )

        return {

            "ok": True,

            "message":
                "Graceful stop requested."
        }

    def refresh_gui(self):
        pass

    # ========================================================
    # WEB PAGE
    # 30% CURRENT RECORDING / 70% LOG
    # ========================================================

    def web_page(self):

        return r"""<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>Liquidsoap Record</title>

<style>

:root {

    --bg:#111418;

    --panel:#1b2026;

    --panel2:#242a31;

    --border:#343b44;

    --text:#e6edf3;

    --muted:#8b949e;

    --green:#20c878;

    --green-dark:#163d2d;

    --red:#ef5350;

    --red-dark:#4b2222;

    --blue:#58a6ff;

    --input:#2b3139;

    --log:#080a0c;
}


/* =========================================================
   GLOBAL
   ========================================================= */

* {
    box-sizing:border-box;
}

html,
body {
    width:100%;
    height:100%;
}

body {

    margin:0;

    background:var(--bg);

    color:var(--text);

    font-family:
        Arial,
        Helvetica,
        sans-serif;

    overflow:hidden;
}


/* =========================================================
   CONTAINER
   ========================================================= */

.container {

    width:100%;

    max-width:1700px;

    height:100vh;

    margin:auto;

    padding:16px;

    display:grid;

    grid-template-columns:3fr 7fr;

    grid-template-rows:auto auto minmax(0,1fr);

    grid-template-areas:
        "header header"
        "current log"
        "parameters log";

    gap:14px;

    box-sizing:border-box;
}


/* =========================================================
   HEADER
   ========================================================= */

.header {

    grid-area:header;

    display:flex;

    justify-content:space-between;

    align-items:center;
}

.header h1 {

    margin:0;

    font-size:26px;

    letter-spacing:.2px;
}

.status {

    padding:9px 17px;

    border-radius:8px;

    font-weight:bold;

    background:var(--red-dark);

    color:var(--red);

    border:1px solid
        rgba(239,83,80,.15);
}

.status.recording {

    background:var(--green-dark);

    color:var(--green);

    border-color:
        rgba(32,200,120,.18);
}


/* =========================================================
   30 / 70 MONITOR
   ========================================================= */

.monitor {

    display:contents;
}


/* =========================================================
   CURRENT RECORDING - 30%
   ========================================================= */

.current-recording {

    grid-area:current;

    min-width:0;

    min-height:0;

    background:var(--panel);

    border:1px solid var(--border);

    border-radius:10px;

    padding:18px;

    display:flex;

    flex-direction:column;

    overflow:hidden;
}

.current-recording h2 {

    margin:0 0 16px 0;

    font-size:17px;
}

.recording-status {

    display:flex;

    align-items:center;

    gap:10px;

    padding:13px;

    margin-bottom:14px;

    background:var(--panel2);

    border-radius:8px;
}

.status-dot {

    width:10px;

    height:10px;

    flex:0 0 auto;

    border-radius:50%;

    background:var(--red);
}

.status-dot.recording {

    background:var(--green);

    box-shadow:
        0 0 0 4px
        rgba(32,200,120,.12);
}

.recording-status strong {

    font-size:14px;
}

.info {

    display:flex;

    flex-direction:column;

    gap:10px;
}

.info-box {

    background:var(--panel2);

    border-radius:8px;

    padding:13px;
}

.info-box small {

    display:block;

    color:var(--muted);

    margin-bottom:6px;

    font-size:12px;

    text-transform:uppercase;

    letter-spacing:.4px;
}

.info-box strong {

    display:block;

    word-break:break-word;

    font-size:14px;
}

#elapsed {

    font-family:Consolas,monospace;

    font-size:22px;

    letter-spacing:1px;
}

.current-buttons {

    display:flex;

    gap:8px;

    margin-top:auto;

    padding-top:16px;
}

.current-buttons button {

    flex:1;
}


/* =========================================================
   LOG - 70%
   ========================================================= */

.log-panel {

    grid-area:log;

    min-width:0;

    min-height:0;

    height:100%;

    background:var(--panel);

    border:1px solid var(--border);

    border-radius:10px;

    padding:14px;

    display:flex;

    flex-direction:column;
}

.log-header {

    flex:0 0 auto;

    display:flex;

    justify-content:space-between;

    align-items:center;

    margin-bottom:9px;
}

.log-header h2 {

    margin:0;

    font-size:17px;
}

.log-state {

    color:var(--muted);

    font-size:12px;
}

.log {

    flex:1 1 auto;

    min-height:0;

    background:var(--log);

    color:#c9d1d9;

    border-radius:7px;

    border:1px solid var(--border);

    padding:12px;

    overflow:auto;

    white-space:pre-wrap;

    font-family:Consolas,monospace;

    font-size:12px;

    line-height:1.45;

    tab-size:4;
}


/* =========================================================
   PARAMETERS
   ========================================================= */

.parameters {

    grid-area:parameters;

    min-width:0;

    min-height:0;

    display:grid;

    grid-template-columns:1fr;

    grid-auto-rows:max-content;

    gap:10px;

    height:100%;

    overflow-y:auto;
    overflow-x:hidden;

    padding-right:2px;
}

.card {

    background:var(--panel);

    border:1px solid var(--border);

    border-radius:10px;

    padding:14px;

    min-width:0;
}

.card h2 {

    margin:0 0 12px 0;

    font-size:16px;
}

.field {

    margin-bottom:10px;
}

.field:last-child {

    margin-bottom:0;
}

.field label {

    display:block;

    color:var(--muted);

    margin-bottom:5px;

    font-size:12px;
}

input,
select {

    width:100%;

    background:var(--input);

    color:var(--text);

    border:1px solid var(--border);

    border-radius:6px;

    padding:8px;

    font-size:13px;

    outline:none;
}

input:focus,
select:focus {

    border-color:var(--blue);

    box-shadow:
        0 0 0 2px
        rgba(88,166,255,.10);
}

.check {

    display:flex;

    align-items:center;

    gap:8px;

    margin:8px 0;
}

.check input {

    width:auto;
}

.buttons {

    display:flex;

    gap:8px;

    margin-top:12px;

    flex-wrap:wrap;
}

button {

    border:0;

    border-radius:7px;

    padding:10px 15px;

    cursor:pointer;

    color:white;

    font-weight:bold;

    transition:
        opacity .15s ease,
        transform .05s ease;
}

button:active {

    transform:translateY(1px);
}

.start {

    background:var(--green);
}

.stop {

    background:var(--red);
}

.save {

    background:var(--blue);
}

button:disabled {

    opacity:.45;

    cursor:not-allowed;
}


/* =========================================================
   ICECAST PLAYER
   ========================================================= */

.player-card {
    background:var(--panel);
    border:1px solid var(--border);
    border-radius:10px;
    padding:14px;
    min-width:0;
}

.player-card h2 {
    margin:0 0 12px 0;
    font-size:16px;
}

.player-row {
    display:flex;
    gap:8px;
    align-items:center;
}

.player-row input {
    flex:1;
}

.player-controls {
    display:flex;
    gap:8px;
    align-items:center;
    margin-top:10px;
}

.player-controls button {
    min-width:72px;
}

.player-volume {
    flex:1;
    min-width:80px;
}

.player-status {
    margin-top:9px;
    color:var(--muted);
    font-size:12px;
    min-height:16px;
}

.player-status.playing {
    color:var(--green);
}

/* =========================================================
   MESSAGE
   ========================================================= */

.message {

    margin-top:10px;

    padding:9px;

    border-radius:6px;

    display:none;

    font-size:13px;
}

.message.error {

    display:block;

    background:var(--red-dark);

    color:#ffb4b2;
}

.message.ok {

    display:block;

    background:var(--green-dark);

    color:#9ff0c7;
}


/* =========================================================
   SCROLLBAR
   ========================================================= */

::-webkit-scrollbar {

    width:9px;

    height:9px;
}

::-webkit-scrollbar-track {

    background:#15191d;
}

::-webkit-scrollbar-thumb {

    background:#39414a;

    border-radius:5px;
}

::-webkit-scrollbar-thumb:hover {

    background:#4a5561;
}


/* =========================================================
   RESPONSIVE
   ========================================================= */

@media(max-width:1100px) {

    body {

        overflow:auto;
    }

    .container {

        height:auto;

        min-height:100vh;

        display:flex;

        flex-direction:column;

        gap:14px;
    }

    .monitor {

        display:flex;

        flex-direction:column;

        gap:14px;
    }

    .current-recording {

        min-height:270px;
    }

    .log-panel {

        height:600px;
    }

    .parameters {

        height:auto;

        grid-template-columns:repeat(2, minmax(0,1fr));

        overflow:visible;
    }
}


@media(max-width:650px) {

    .container {

        padding:10px;
    }

    .header {

        flex-direction:column;

        align-items:flex-start;

        gap:10px;
    }

    .current-recording {

        min-height:300px;
    }

    .log-panel {

        height:500px;
    }

    .parameters {

        grid-template-columns:1fr;
    }

    .current-buttons {

        flex-direction:column;
    }

    .header h1 {

        font-size:22px;
    }
}

</style>

</head>


<body>

<div class="container">


    <!-- =====================================================
         HEADER
         ===================================================== -->

    <div class="header">

        <h1>
            Liquidsoap Record
        </h1>

        <div
            id="status"
            class="status"
        >
            STOPPED
        </div>

    </div>


    <!-- =====================================================
         30% / 70% MONITOR
         ===================================================== -->

    <div class="monitor">


        <!-- =================================================
             30% CURRENT RECORDING
             ================================================= -->

        <section class="current-recording">

            <h2>
                Current Recording
            </h2>


            <div class="recording-status">

                <span
                    id="statusDot"
                    class="status-dot"
                ></span>

                <strong
                    id="recordingState"
                >
                    STOPPED
                </strong>

            </div>


            <div class="info">


                <div class="info-box">

                    <small>
                        Elapsed
                    </small>

                    <strong id="elapsed">
                        00:00:00
                    </strong>

                </div>


                <div class="info-box">

                    <small>
                        Current File
                    </small>

                    <strong id="file">
                        -
                    </strong>

                </div>


            </div>


            <div class="current-buttons">

                <button
                    class="start"
                    id="startButton"
                    onclick="startRecording()"
                >
                    ▶ START
                </button>

                <button
                    class="stop"
                    id="stopButton"
                    onclick="stopRecording()"
                    disabled
                >
                    ■ STOP
                </button>

                <button
                    class="save"
                    id="saveButton"
                    onclick="saveParameters()"
                >
                    SAVE PARAMETERS
                </button>

            </div>

            <div
                id="message"
                class="message"
            ></div>

        </section>


        <!-- =================================================
             70% LIQUIDSOAP LOG
             ================================================= -->

        <section class="log-panel">

            <div class="log-header">

                <h2>
                    Liquidsoap Log
                </h2>

                <div
                    id="logState"
                    class="log-state"
                >
                    Waiting for log...
                </div>

            </div>


            <div
                id="log"
                class="log"
            ></div>

        </section>


    </div>


    <!-- =====================================================
         PARAMETERS
         ===================================================== -->

    <div class="parameters">


        <!-- =================================================
             STREAM SOURCE
             ================================================= -->

        <div class="card">

            <h2>
                Stream Source
            </h2>


            <div class="field">

                <label>
                    Stream URL
                </label>

                <input id="url">

            </div>


            <div class="field">

                <label>
                    Recording Directory
                </label>

                <input id="directory">

            </div>


            <div class="field">

                <label>
                    Station
                </label>

                <input id="station">

            </div>

        </div>


        <!-- =================================================
             RECORDING
             ================================================= -->

        <div class="card">

            <h2>
                Recording
            </h2>


            <div class="check">

                <input
                    type="checkbox"
                    id="transcode"
                >

                <label for="transcode">
                    Transcode
                </label>

            </div>


            <div class="field">

                <label>
                    Format
                </label>

                <select id="format">

                    <option>mp3</option>
                    <option>m4a</option>
                    <option>flac</option>
                    <option>ogg</option>
                    <option>opus</option>

                </select>

            </div>


            <div class="field">

                <label>
                    Codec
                </label>

                <select id="codec">

                    <option>libmp3lame</option>
                    <option>aac</option>
                    <option>flac</option>
                    <option>libopus</option>
                    <option>vorbis</option>

                </select>

            </div>


            <div class="field">

                <label>
                    Sample Rate
                </label>

                <select id="samplerate">

                    <option>22050</option>
                    <option>32000</option>
                    <option>44100</option>
                    <option>48000</option>
                    <option>96000</option>

                </select>

            </div>


            <div class="field">

                <label>
                    Bitrate
                </label>

                <select id="bitrate">

                    <option>64k</option>
                    <option>96k</option>
                    <option>128k</option>
                    <option>160k</option>
                    <option>192k</option>
                    <option>256k</option>
                    <option>320k</option>

                </select>

            </div>

        </div>


        <!-- =================================================
             OPTIONS
             ================================================= -->

        <div class="card">

            <h2>
                Options
            </h2>


            <div class="check">

                <input
                    type="checkbox"
                    id="listen"
                >

                <label for="listen">
                    Listen
                </label>

            </div>


            <div class="field">

                <label>
                    Device
                </label>

                <select id="device">

                    <option>portaudio</option>
                    <option>alsa</option>

                </select>

            </div>


            <div class="check">

                <input
                    type="checkbox"
                    id="keep"
                >

                <label for="keep">
                    Keep incomplete
                </label>

            </div>


            <div class="check">

                <input
                    type="checkbox"
                    id="m3u"
                >

                <label for="m3u">
                    M3U
                </label>

            </div>


            <div class="check">

                <input
                    type="checkbox"
                    id="covers"
                >

                <label for="covers">
                    Covers
                </label>

            </div>


            <div class="check">

                <input
                    type="checkbox"
                    id="single"
                >

                <label for="single">
                    Single track
                </label>

            </div>


            <div class="field">

                <label>
                    Timeout
                </label>

                <input id="timeout">

            </div>


            <div class="field">

                <label>
                    TuneIn ID
                </label>

                <input
                    id="tunein_id"
                    placeholder="Optional"
                >

            </div>


            <div class="field">

                <label>
                    Log Level
                </label>

                <select id="log_level">

                    <option>0</option>
                    <option>1</option>
                    <option>2</option>
                    <option>3</option>
                    <option>4</option>

                </select>

            </div>

        </div>


        <!-- =================================================
             ICECAST
             ================================================= -->

        <div class="card">

            <h2>
                Icecast Relay
            </h2>


            <div class="check">

                <input
                    type="checkbox"
                    id="relay"
                >

                <label for="relay">
                    Enable relay
                </label>

            </div>


            <div class="field">

                <label>
                    Host
                </label>

                <input id="host">

            </div>


            <div class="field">

                <label>
                    Port
                </label>

                <input id="port">

            </div>


            <div class="field">

                <label>
                    Password
                </label>

                <input
                    id="password"
                    type="password"
                >

            </div>


        </div>


        <!-- =================================================
             ICECAST PLAYER
             ================================================= -->

        <div class="player-card">

            <h2>Icecast Player</h2>

            <div class="field">
                <label for="player_url">Stream URL</label>
                <input
                    id="player_url"
                    type="url"
                    placeholder="http://host:8000/stream"
                >
            </div>

            <div class="player-controls">

                <button
                    class="start"
                    id="playerPlayButton"
                    type="button"
                    onclick="playRelay()"
                >PLAY</button>

                <button
                    class="stop"
                    id="playerStopButton"
                    type="button"
                    onclick="stopRelay()"
                >STOP</button>

                <input
                    class="player-volume"
                    id="playerVolume"
                    type="range"
                    min="0"
                    max="1"
                    step="0.01"
                    value="0.8"
                    title="Volume"
                    oninput="setRelayVolume()"
                >

            </div>

            <audio id="relayPlayer" preload="none"></audio>

            <div class="player-status" id="playerStatus">
                Player stopped
            </div>

        </div>


    </div>


</div>


<script>

/* =========================================================
   FIELDS
   ========================================================= */

const fields = [

    "url",
    "directory",
    "station",

    "transcode",
    "samplerate",
    "format",
    "codec",
    "bitrate",

    "listen",
    "device",

    "keep",
    "m3u",
    "covers",
    "single",

    "timeout",
    "tunein_id",

    "log_level",

    "relay",
    "host",
    "port",
    "password"

];


let logRequestInProgress = false;


/* =========================================================
   ICECAST PLAYER
   ========================================================= */

function getDefaultRelayPlayerUrl() {

    const hostElement = document.getElementById("host");
    const portElement = document.getElementById("port");

    let host = hostElement ? hostElement.value.trim() : "";
    const port = portElement ? portElement.value.trim() : "8000";

    if (!host) {
        host = window.location.hostname;
    }

    if (host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0") {
        host = window.location.hostname || "127.0.0.1";
    }

    return "http://" + host + ":" + (port || "8000") + "/stream";
}


function updateRelayPlayerUrl(force = false) {

    const input = document.getElementById("player_url");
    if (!input) {
        return;
    }

    if (force || !input.value.trim()) {
        input.value = getDefaultRelayPlayerUrl();
    }
}


function setPlayerStatus(text, playing = false) {

    const status = document.getElementById("playerStatus");
    if (!status) {
        return;
    }

    status.textContent = text;
    status.className = "player-status" + (playing ? " playing" : "");
}


function playRelay() {

    const player = document.getElementById("relayPlayer");
    const input = document.getElementById("player_url");

    if (!player || !input) {
        return;
    }

    const url = input.value.trim();
    if (!url) {
        setPlayerStatus("Enter the Icecast stream URL first.");
        return;
    }

    if (player.src !== url) {
        player.src = url;
    }

    setRelayVolume();

    const result = player.play();
    if (result && typeof result.catch === "function") {
        result.catch(function(error) {
            console.log("Player error:", error);
            setPlayerStatus("Could not play the Icecast stream. Check the URL and mount point.");
        });
    }
}


function stopRelay() {

    const player = document.getElementById("relayPlayer");
    if (!player) {
        return;
    }

    player.pause();
    player.removeAttribute("src");
    player.load();
    setPlayerStatus("Player stopped");
}


function setRelayVolume() {

    const player = document.getElementById("relayPlayer");
    const volume = document.getElementById("playerVolume");

    if (player && volume) {
        player.volume = parseFloat(volume.value) || 0;
    }
}


function initialiseRelayPlayer() {

    updateRelayPlayerUrl();

    const player = document.getElementById("relayPlayer");
    if (!player) {
        return;
    }

    player.addEventListener("playing", function() {
        setPlayerStatus("Playing Icecast relay", true);
    });

    player.addEventListener("waiting", function() {
        setPlayerStatus("Buffering Icecast relay...");
    });

    player.addEventListener("pause", function() {
        if (!player.ended) {
            setPlayerStatus("Player paused");
        }
    });

    player.addEventListener("error", function() {
        setPlayerStatus("Player error. Check the Icecast URL and mount point.");
    });
}



/* =========================================================
   MESSAGE
   ========================================================= */

function showMessage(
    text,
    ok = false
) {

    const box =
        document.getElementById(
            "message"
        );

    box.textContent = text;

    box.className =
        "message "
        + (
            ok
            ? "ok"
            : "error"
        );
}


/* =========================================================
   FORM DATA
   ========================================================= */

function getFormData() {

    const data = {};

    fields.forEach(
        function(name) {

            const element =
                document.getElementById(
                    name
                );

            if (
                element.type
                === "checkbox"
            ) {

                data[name] =
                    element.checked;

            } else {

                data[name] =
                    element.value;
            }

        }
    );

    return data;
}


/* =========================================================
   SET FORM DATA
   ========================================================= */

function setFormData(data) {

    fields.forEach(
        function(name) {

            if (!(name in data)) {
                return;
            }

            const element =
                document.getElementById(
                    name
                );

            if (
                element.type
                === "checkbox"
            ) {

                element.checked =
                    !!data[name];

            } else {

                element.value =
                    data[name];
            }

        }
    );

    updateRelayPlayerUrl();
}


/* =========================================================
   LOAD PARAMETERS
   ========================================================= */

async function loadParameters() {

    try {

        const response =
            await fetch(
                "/api/parameters",
                {
                    cache:"no-store"
                }
            );

        if (!response.ok) {

            throw new Error(
                "HTTP "
                + response.status
            );
        }

        const data =
            await response.json();

        setFormData(data);

    } catch (error) {

        showMessage(
            "Could not load parameters: "
            + error,
            false
        );
    }
}


/* =========================================================
   SAVE PARAMETERS
   ========================================================= */

async function saveParameters() {

    try {

        const response =
            await fetch(
                "/api/parameters",
                {
                    method:"POST",

                    headers:{
                        "Content-Type":
                            "application/json"
                    },

                    body:JSON.stringify(
                        getFormData()
                    )
                }
            );

        const data =
            await response.json();

        if (!data.ok) {

            showMessage(
                data.error ||
                "Could not save parameters."
            );

            return;
        }

        if (data.parameters) {

            setFormData(
                data.parameters
            );
        }

        showMessage(
            "Parameters saved.",
            true
        );

    } catch (error) {

        showMessage(
            "Error: "
            + error
        );
    }
}


/* =========================================================
   START RECORDING
   ========================================================= */

async function startRecording() {

    try {

        const response =
            await fetch(
                "/api/start",
                {
                    method:"POST",

                    headers:{
                        "Content-Type":
                            "application/json"
                    },

                    body:JSON.stringify(
                        getFormData()
                    )
                }
            );

        const data =
            await response.json();

        if (!data.ok) {

            showMessage(
                data.error ||
                "Could not start recording."
            );

            return;
        }

        showMessage(
            "Recording start requested.",
            true
        );

        setTimeout(
            updateStatus,
            250
        );

    } catch (error) {

        showMessage(
            "Error: "
            + error
        );
    }
}


/* =========================================================
   STOP RECORDING
   ========================================================= */

async function stopRecording() {

    try {

        const response =
            await fetch(
                "/api/stop",
                {
                    method:"POST"
                }
            );

        const data =
            await response.json();

        if (!data.ok) {

            showMessage(
                data.error ||
                "Could not stop recording."
            );

            return;
        }

        showMessage(
            "Graceful stop requested.",
            true
        );

        setTimeout(
            updateStatus,
            250
        );

    } catch (error) {

        showMessage(
            "Error: "
            + error
        );
    }
}


/* =========================================================
   STATUS
   ========================================================= */

async function updateStatus() {

    try {

        const response =
            await fetch(
                "/api/status",
                {
                    cache:"no-store"
                }
            );

        if (!response.ok) {
            return;
        }

        const data =
            await response.json();


        const status =
            document.getElementById(
                "status"
            );

        const start =
            document.getElementById(
                "startButton"
            );

        const stop =
            document.getElementById(
                "stopButton"
            );

        const recordingState =
            document.getElementById(
                "recordingState"
            );

        const statusDot =
            document.getElementById(
                "statusDot"
            );


        if (data.stopping) {

            status.textContent =
                "STOPPING...";

            status.className =
                "status";

            recordingState.textContent =
                "STOPPING...";

            statusDot.className =
                "status-dot";

            start.disabled = true;

            stop.disabled = true;

        } else if (data.recording) {

            status.textContent =
                "RECORDING";

            status.className =
                "status recording";

            recordingState.textContent =
                "RECORDING";

            statusDot.className =
                "status-dot recording";

            start.disabled = true;

            stop.disabled = false;

        } else {

            status.textContent =
                "STOPPED";

            status.className =
                "status";

            recordingState.textContent =
                "STOPPED";

            statusDot.className =
                "status-dot";

            start.disabled = false;

            stop.disabled = true;
        }


        document.getElementById(
            "elapsed"
        ).textContent =
            data.elapsed ||
            "00:00:00";


        document.getElementById(
            "file"
        ).textContent =
            data.file || "-";


    } catch (error) {

        console.log(
            "Status error:",
            error
        );
    }
}


/* =========================================================
   LOG
   ========================================================= */

async function updateLog() {

    if (logRequestInProgress) {
        return;
    }

    logRequestInProgress = true;

    try {

        const response =
            await fetch(
                "/api/log",
                {
                    cache:"no-store"
                }
            );

        if (!response.ok) {

            throw new Error(
                "HTTP "
                + response.status
            );
        }

        const data =
            await response.json();


        const log =
            document.getElementById(
                "log"
            );

        const state =
            document.getElementById(
                "logState"
            );


        const lines =
            Array.isArray(data.log)
            ? data.log
            : [];


        log.textContent =
            lines.join("\n");


        log.scrollTop =
            log.scrollHeight;


        state.textContent =
            lines.length
            + " log lines";


    } catch (error) {

        console.log(
            "Log error:",
            error
        );

        document.getElementById(
            "logState"
        ).textContent =
            "Log connection error";

    } finally {

        logRequestInProgress = false;
    }
}


/* =========================================================
   INITIALIZE
   ========================================================= */

initialiseRelayPlayer();
loadParameters();

updateStatus();

updateLog();


/* =========================================================
   REFRESH
   ========================================================= */

setInterval(
    updateStatus,
    1000
);

setInterval(
    updateLog,
    1000
);

</script>

</body>
</html>
"""

    # ========================================================
    # CLOSE
    # ========================================================

    def on_close(self):

        self.stop_icecast_gui(silent=True)
        self.save_persistent_parameters()

        process = self.process

        if process is None:

            self.force_close()

            return

        if self.closing:
            return

        answer = messagebox.askyesno(
            "Recording Active",
            (
                "Liquidsoap is currently recording.\n\n"
                "Stop the recording gracefully and exit?"
            )
        )

        if not answer:
            return

        self.closing = True

        self.write_log(
            "[GUI] Application closing."
        )

        self.write_log(
            "[GUI] Waiting for Liquidsoap to "
            "finalize the recording..."
        )

        self.stop_recording(
            graceful_timeout=
            GRACEFUL_STOP_TIMEOUT
        )

        self.root.after(
            100,
            self._wait_for_close
        )

    def _wait_for_close(self):

        if not self.closing:
            return

        if self.process is not None:

            self.root.after(
                100,
                self._wait_for_close
            )

            return

        self.force_close()

    def force_close(self):

        self.stop_icecast_gui(silent=True)

        process = self.process

        if process is not None:

            try:

                if process.poll() is None:
                    process.kill()

            except Exception:
                pass

            self.process = None

        if self.web_server is not None:

            try:
                self.web_server.stop()

            except Exception:
                pass

            self.web_server = None

        try:

            self.root.destroy()

        except Exception:
            pass


# ============================================================
# COMMAND LINE ARGUMENTS
# ============================================================

def parse_arguments():

    parser = argparse.ArgumentParser(
        description=(
            "Liquidsoap Record desktop application "
            "with optional web interface."
        )
    )

    # --------------------------------------------------------
    # STREAM
    # --------------------------------------------------------

    parser.add_argument(
        "--url",
        default="",
        help="Stream URL"
    )

    parser.add_argument(
        "--dir",
        "--directory",
        dest="directory",
        default="",
        help="Recording directory"
    )

    parser.add_argument(
        "--station",
        default="",
        help="Station name"
    )

    # --------------------------------------------------------
    # RECORDING
    # --------------------------------------------------------

    parser.add_argument(
        "--start-recording",
        action="store_true",
        help="Start recording automatically after the GUI starts"
    )

    parser.add_argument(
        "--transcode",
        action="store_true",
        dest="transcode",
        default=False,
        help="Enable transcoding"
    )
    parser.add_argument(
        "--no-transcode",
        "--no_transcode",
        action="store_false",
        dest="transcode",
        help="Disable transcoding"
    )

    parser.add_argument(
        "--samplerate",
        default="44100",
        help="Sample rate"
    )

    parser.add_argument(
        "--format",
        default="mp3",
        choices=[
            "mp3",
            "m4a",
            "flac",
            "ogg",
            "opus"
        ],
        help="Recording format"
    )

    parser.add_argument(
        "--codec",
        default="libmp3lame",
        help="Codec"
    )

    parser.add_argument(
        "--bitrate",
        default="320k",
        help="Bitrate"
    )

    # --------------------------------------------------------
    # OPTIONS
    # --------------------------------------------------------

    parser.add_argument(
        "--listen",
        action="store_true",
        dest="listen",
        default=False,
        help="Enable listening"
    )
    parser.add_argument(
        "--no-listen",
        "--no_listen",
        action="store_false",
        dest="listen",
        help="Disable listening"
    )


    parser.add_argument(
        "--device",
        default="portaudio",
        help="Audio device"
    )

    parser.add_argument(
        "--log-level",
        default="2",
        dest="log_level",
        help="Liquidsoap log level"
    )

    parser.add_argument(
        "--keep",
        action="store_true",
        dest="keep",
        default=False,
        help="Keep incomplete recordings"
    )
    parser.add_argument(
        "--no-keep",
        "--no_keep",
        action="store_false",
        dest="keep",
        help="Do not keep incomplete recordings"
    )

    parser.add_argument(
        "--timeout",
        default="0",
        help="Timeout in seconds"
    )

    parser.add_argument(
        "--tunein-id",
        default="",
        dest="tunein_id",
        help="TuneIn ID"
    )

    parser.add_argument(
        "--m3u",
        action="store_true",
        dest="m3u",
        default=False,
        help="Enable M3U"
    )
    parser.add_argument(
        "--no-m3u",
        "--no_m3u",
        action="store_false",
        dest="m3u",
        help="Disable M3U"
    )

    parser.add_argument(
        "--covers",
        action="store_true",
        dest="covers",
        default=False,
        help="Enable covers"
    )
    parser.add_argument(
        "--no-covers",
        "--no_covers",
        action="store_false",
        dest="covers",
        help="Disable covers"
    )

    parser.add_argument(
        "--single",
        action="store_true",
        dest="single",
        default=False,
        help="Single track mode"
    )
    parser.add_argument(
        "--no-single",
        "--no_single",
        action="store_false",
        dest="single",
        help="Disable single track mode"
    )

    # --------------------------------------------------------
    # ICECAST
    # --------------------------------------------------------

    parser.add_argument(
        "--relay",
        action="store_true",
        dest="relay",
        default=False,
        help="Enable Icecast relay"
    )
    parser.add_argument(
        "--no-relay",
        "--no_relay",
        action="store_false",
        dest="relay",
        help="Disable Icecast relay"
    )

    parser.add_argument(
        "--host",
        dest="relay_host",
        default="localhost",
        help="Icecast relay host"
    )

    parser.add_argument(
        "--port",
        dest="relay_port",
        default="8000",
        help="Icecast relay port"
    )

    parser.add_argument(
        "--password",
        default="hackme",
        help="Icecast password"
    )

    # --------------------------------------------------------
    # WEB
    # --------------------------------------------------------

    parser.add_argument(
        "--web",
        action="store_true",
        dest="web",
        default=False,
        help="Start web interface automatically"
    )
    parser.add_argument(
        "--no-web",
        "--no_web",
        action="store_false",
        dest="web",
        help="Do not start web interface automatically"
    )

    parser.add_argument(
        "--web-host",
        default=DEFAULT_WEB_HOST,
        help="Web server bind address"
    )

    parser.add_argument(
        "--web-port",
        type=int,
        default=DEFAULT_WEB_PORT,
        help="Web server port"
    )

    args = parser.parse_args()

    # Record which command-line options were explicitly supplied so that
    # saved parameters can fill in omitted values without overriding them.
    supplied = set()
    argv = sys.argv[1:]
    option_names = {}
    for action in parser._actions:
        for option in action.option_strings:
            option_names[option] = action.dest

    for token in argv:
        if token.startswith("--"):
            option = token.split("=", 1)[0]
            if option in option_names:
                supplied.add(option_names[option])

    args._cli_overrides = supplied
    return args


# ============================================================
# MAIN
# ============================================================

def main():

    args = parse_arguments()

    root = tk.Tk()

    app = LiquidsoapRecordApp(
        root,
        args
    )

    root.mainloop()


if __name__ == "__main__":
    main()
