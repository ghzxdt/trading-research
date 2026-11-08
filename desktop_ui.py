"""Small local Windows control panel. UI actions do not place financial orders."""
from __future__ import annotations

import ctypes
import json
import os
import queue
import sys
import threading
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from app_control import Controller, ControlError

ROOT = Path(__file__).resolve().parent
TITLE = "Trading Research — Control Panel"
BG, CARD, INK, MUTED, LINE = "#0c1424", "#152238", "#eef4ff", "#a6b6cc", "#263a55"
GREEN, BLUE, AMBER = "#47d7af", "#70aaff", "#ffc16e"


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def saved_data_summary(root=ROOT):
    """Re-evaluate freshness now; never reuse a prior build's 'fresh' flag."""
    state = read_json(root / "output" / "monitor_status.json")
    day = state.get("as_of")
    if not day:
        return "No built data found", "Run a refresh to build the dashboard.", False
    try:
        from validation import freshness
        result = freshness(day)
        label = f"Saved market data through {day}"
        return label, "Current for the latest completed session" if result["ok"] else "Refresh needed: " + result["reason"], bool(result["ok"])
    except Exception:
        return f"Saved market data through {day}", "Current freshness could not be checked.", False


class ControlPanel:
    def __init__(self, window, controller=None):
        self.window = window
        self.controller = controller or Controller(ROOT, port=8766)
        self.events = queue.Queue()
        self.operation = False
        self.polling = False
        self.closed = False
        self.latest = {}
        self.log_window = None
        window.title(TITLE)
        width=min(940,max(720,window.winfo_screenwidth()-70))
        height=min(790,max(540,window.winfo_screenheight()-100))
        window.geometry(f"{width}x{height}")
        window.minsize(min(800,width),min(620,height))
        window.configure(bg=BG)
        window.protocol("WM_DELETE_WINDOW", self.close)
        try:
            window.iconbitmap(str(ROOT / "assets" / "app.ico"))
        except tk.TclError:
            pass
        self._styles()
        self._layout()
        window.after(80, self.drain)
        window.after(150, self.poll)

    def _styles(self):
        s = ttk.Style(self.window)
        s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 11))
        s.configure("Muted.TLabel", foreground=MUTED, background=BG, font=("Segoe UI", 10))
        s.configure("Card.TLabel", background=CARD, foreground=INK, font=("Segoe UI", 11))
        s.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 10))
        s.configure("Title.TLabel", font=("Segoe UI Semibold", 25), foreground=INK, background=BG)
        s.configure("Eyebrow.TLabel", font=("Segoe UI Semibold", 10), foreground=GREEN, background=BG)
        s.configure("State.TLabel", font=("Segoe UI Semibold", 18), foreground=INK, background=CARD)
        s.configure("TButton", font=("Segoe UI Semibold", 11), padding=(16, 11),
                    background="#243b5c", foreground=INK, borderwidth=0, focuscolor=BLUE)
        s.map("TButton", background=[("active", "#345278"), ("disabled", "#1a2b43")], foreground=[("disabled", "#6c819c")])
        s.configure("Primary.TButton", background="#297fdd", foreground="white")
        s.map("Primary.TButton", background=[("active", "#4397f0"), ("disabled", "#25496d")])
        s.configure("Small.TButton", font=("Segoe UI Semibold",10), padding=(9,10))
        s.configure("TProgressbar", background=GREEN, troughcolor=LINE, borderwidth=0)
        s.configure("TSeparator", background=LINE)

    def _layout(self):
        host=ttk.Frame(self.window)
        host.pack(fill="both",expand=True)
        canvas=tk.Canvas(host,bg=BG,highlightthickness=0)
        scroll=ttk.Scrollbar(host,orient="vertical",command=canvas.yview)
        scroll.pack(side="right",fill="y")
        canvas.pack(side="left",fill="both",expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        outer = ttk.Frame(canvas, padding=(30, 24, 30, 18))
        item=canvas.create_window((0,0),window=outer,anchor="nw")
        outer.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
        def resized(event):
            canvas.itemconfigure(item,width=event.width)
            def wrap(frame):
                for child in frame.winfo_children():
                    if isinstance(child,ttk.Label) and int(child.cget("wraplength") or 0)>0:
                        child.configure(wraplength=max(300,event.width-100))
                    wrap(child)
            wrap(outer)
        canvas.bind("<Configure>",resized)
        def wheel(event):
            if event.widget.winfo_toplevel()==self.window and outer.winfo_height()>canvas.winfo_height():
                canvas.yview_scroll(-int(event.delta/120),"units")
        self.window.bind_all("<MouseWheel>",wheel,add="+")
        ttk.Label(outer, text="LOCAL RESEARCH WORKSPACE", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Trading Research", style="Title.TLabel").pack(anchor="w", pady=(5, 2))
        ttk.Label(outer, text="Open your dashboard. Run updates. Restart when something gets stuck.", style="Muted.TLabel").pack(anchor="w", pady=(0, 18))

        status = ttk.Frame(outer, style="Card.TFrame", padding=20)
        status.pack(fill="x")
        self.state_text = tk.StringVar(value="Checking app…")
        self.state_label = ttk.Label(status, textvariable=self.state_text, style="State.TLabel")
        self.state_label.pack(anchor="w")
        self.state_detail = tk.StringVar(value="Connecting to the local dashboard.")
        ttk.Label(status, textvariable=self.state_detail, style="CardMuted.TLabel", wraplength=810).pack(anchor="w", pady=(4, 12))
        self.data_text = tk.StringVar()
        self.data_detail = tk.StringVar()
        ttk.Label(status, textvariable=self.data_text, style="Card.TLabel").pack(anchor="w")
        self.data_label = ttk.Label(status, textvariable=self.data_detail, style="CardMuted.TLabel", wraplength=810)
        self.data_label.pack(anchor="w", pady=(3, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(18, 8))
        actions.columnconfigure((0, 1), weight=1, uniform="primary")
        self.open_button = ttk.Button(actions, text="Open dashboard", style="Primary.TButton", command=self.open_dashboard)
        self.open_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.refresh_button = ttk.Button(actions, text="Run / Refresh data", style="Primary.TButton", command=lambda: self.run("refresh"))
        self.refresh_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        service = ttk.Frame(outer)
        service.pack(fill="x", pady=(3, 12))
        for col in range(4):
            service.columnconfigure(col, weight=1, uniform="service")
        self.start_button = ttk.Button(service, text="Start app", style="Small.TButton", command=lambda: self.run("start"))
        self.restart_button = ttk.Button(service, text="Restart app", style="Small.TButton", command=lambda: self.run("restart"))
        self.stop_button = ttk.Button(service, text="Stop app", style="Small.TButton", command=lambda: self.run("stop"))
        self.rebuild_button = ttk.Button(service, text="Rebuild saved data", style="Small.TButton", command=lambda: self.run("rebuild"))
        for i, button in enumerate((self.start_button, self.restart_button, self.stop_button, self.rebuild_button)):
            button.grid(row=0, column=i, sticky="ew", padx=(0 if i==0 else 5, 0 if i==3 else 5))

        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.pack(fill="x", pady=(2, 13))
        activity = ttk.Frame(outer, style="Card.TFrame", padding=18)
        activity.pack(fill="both", expand=True)
        ttk.Label(activity, text="Last activity", style="Card.TLabel", font=("Segoe UI Semibold", 12)).pack(anchor="w")
        self.activity_text = tk.StringVar(value="Ready. Opening this panel does not start a data download.")
        ttk.Label(activity, textvariable=self.activity_text, style="CardMuted.TLabel", wraplength=800, justify="left").pack(anchor="w", pady=(7, 0))
        self.build_text = tk.StringVar(value="No refresh requested from this panel yet.")
        ttk.Label(activity, textvariable=self.build_text, style="CardMuted.TLabel", wraplength=800, justify="left").pack(anchor="w", pady=(12, 0))

        tools = ttk.Frame(outer)
        tools.pack(fill="x", pady=(16, 12))
        ttk.Button(tools, text="View logs", command=self.view_logs).pack(side="left", padx=(0, 8))
        ttk.Button(tools, text="Repair startup", command=lambda: self.run("repair")).pack(side="left", padx=(0, 8))
        ttk.Button(tools, text="Open app folder", command=self.open_folder).pack(side="left", padx=(0, 8))
        ttk.Button(tools, text="Help", command=self.help).pack(side="right")
        ttk.Separator(outer).pack(fill="x", pady=(0, 10))
        ttk.Label(outer, text="Restart preserves data, paper records and backups. Closing this window leaves the dashboard running.",
                  style="Muted.TLabel", wraplength=830).pack(anchor="w")
        self.action_buttons = [self.open_button, self.refresh_button, self.start_button, self.restart_button, self.stop_button, self.rebuild_button]
        self.update_data()

    def update_data(self):
        title, detail, current = saved_data_summary()
        self.data_text.set(title)
        self.data_detail.set(detail)
        self.data_label.configure(foreground=GREEN if current else AMBER)

    def poll(self):
        if self.closed:
            return
        if not self.polling:
            self.polling = True
            def worker():
                try:
                    self.events.put(("status", self.controller.status()))
                except Exception as exc:
                    self.events.put(("poll_error", str(exc)))
            threading.Thread(target=worker, daemon=True).start()
        self.window.after(2000, self.poll)

    def apply_status(self, state):
        self.latest = state
        running, identity, busy = state.get("running"), state.get("identity_ok"), state.get("busy")
        if busy:
            label, color = "Updating and validating", BLUE
        elif running and identity:
            label, color = "App is running", GREEN
        elif running or state.get("occupied"):
            label, color = "Port needs attention", AMBER
        else:
            label, color = "App is stopped", AMBER
        self.state_text.set(label)
        self.state_label.configure(foreground=color)
        self.state_detail.set(state.get("message") or ("Ready to open your dashboard." if identity else "Click Open dashboard to start it."))
        build = state.get("build") or {}
        if build.get("message"):
            prefix = "Refresh in progress: " if build.get("running") else "Last refresh: "
            self.build_text.set(prefix + str(build["message"]))
        if busy or self.operation:
            self.progress.start(12)
        else:
            self.progress.stop()
        for b in self.action_buttons:
            b.configure(state="disabled" if self.operation else "normal")
        if busy and not self.operation:
            for b in (self.refresh_button, self.restart_button, self.stop_button, self.rebuild_button):
                b.configure(state="disabled")
        if running and identity:
            self.start_button.configure(state="disabled")
        elif not running:
            self.stop_button.configure(state="disabled")
        self.update_data()

    def drain(self):
        if self.closed:
            return
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind in ("status", "operation_status"):
                if kind == "status":
                    self.polling = False
                self.apply_status(value)
            elif kind == "poll_error":
                self.polling = False
                self.state_text.set("Status unavailable")
                self.state_detail.set(value)
            elif kind == "done":
                self.operation = False
                self.activity_text.set(value)
                self.apply_status(self.latest)
            elif kind == "error":
                self.operation = False
                self.activity_text.set(value)
                self.apply_status(self.latest)
                messagebox.showerror("Trading Research", value, parent=self.window)
        self.window.after(120, self.drain)

    def run(self, action, open_after=False):
        if self.operation:
            return
        self.operation = True
        labels = {"start":"Starting the dashboard…", "stop":"Stopping the local app…", "restart":"Restarting the local app…",
                  "refresh":"Starting a fresh data build…", "rebuild":"Rebuilding the saved data…", "repair":"Checking the startup lock…"}
        self.activity_text.set(labels[action])
        self.apply_status(self.latest)
        def worker():
            try:
                if action == "start":
                    result = self.controller.start()
                    text = "Dashboard is ready. Your saved data is unchanged."
                elif action == "stop":
                    result = self.controller.stop()
                    text = "App stopped. Data, reports, paper records and backups are preserved."
                elif action == "restart":
                    result = self.controller.restart()
                    text = "App restarted. Open dashboard to continue. Saved data is unchanged."
                elif action in ("refresh", "rebuild"):
                    self.controller.start()
                    result = self.controller.refresh(offline=action == "rebuild")
                    text = "Fresh data refresh started. Follow the status here or open View logs." if action == "refresh" else "Offline rebuild started. No data downloads or new paper decisions are created."
                else:
                    result = self.controller.recover_stale_lock()
                    text = result.get("message", "Startup check finished.")
                if open_after:
                    webbrowser.open(f"http://localhost:{self.controller.port}/monitor.html", new=2)
                    text = "Dashboard opened in your browser. You can leave this panel open or close it."
                self.events.put(("operation_status", self.controller.status()))
                self.events.put(("done", text))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def open_dashboard(self):
        self.run("start", open_after=True)

    def view_logs(self):
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.lift()
            return
        window = tk.Toplevel(self.window)
        self.log_window = window
        window.title("Trading Research — Logs")
        window.geometry("900x530")
        window.configure(bg=BG)
        body = ttk.Frame(window, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Latest refresh / app log", font=("Segoe UI Semibold",15)).pack(anchor="w", pady=(0,10))
        text = tk.Text(body, wrap="word", bg=CARD, fg=INK, insertbackground=INK, font=("Consolas",10), relief="flat", padx=12,pady=12)
        text.pack(fill="both", expand=True)
        def update():
            if not window.winfo_exists():
                return
            try:
                value=self.controller.last_log() or "No log yet. Run a refresh or rebuild to create one."
            except Exception as exc:
                value=str(exc)
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("end",value)
            text.see("end")
            text.configure(state="disabled")
            window.after(2000,update)
        update()

    def open_folder(self):
        if os.name == "nt":
            os.startfile(str(ROOT))

    def help(self):
        messagebox.showinfo("Trading Research — Quick guide",
            "1. Open dashboard starts the local app and opens your browser.\n\n"
            "2. Run / Refresh data downloads current market sources and validates a complete report build. Watch the status or logs.\n\n"
            "3. Restart app restarts the dashboard server. It preserves all data and does not cancel an active build.\n\n"
            "Rebuild saved data works without downloading sources. Repair startup only clears a build lock after its owning process is confirmed stopped.\n\n"
            "Closing this window leaves the dashboard running. Stop app stops the local server.\n\n"
            "This is a research app. It does not submit trading orders. Data-source access failures remain visible in the dashboard.",parent=self.window)

    def close(self):
        self.closed=True
        self.window.destroy()


def single_instance():
    """Keep repeated shortcut clicks from opening duplicate panels."""
    if os.name != "nt":
        return True, None
    import hashlib
    name="Local\\TradingResearchPanel_"+hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:24]
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    kernel.CloseHandle.restype=ctypes.c_int
    ctypes.set_last_error(0)
    mutex=kernel.CreateMutexW(None,False,name)
    if not mutex:
        raise OSError(ctypes.get_last_error(),"Could not initialize the control panel instance lock")
    if ctypes.get_last_error()==183:
        user=ctypes.WinDLL("user32",use_last_error=True)
        user.FindWindowW.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p]
        user.FindWindowW.restype=ctypes.c_void_p
        user.ShowWindow.argtypes=[ctypes.c_void_p,ctypes.c_int]
        user.ShowWindow.restype=ctypes.c_int
        user.SetForegroundWindow.argtypes=[ctypes.c_void_p]
        user.SetForegroundWindow.restype=ctypes.c_int
        hwnd=user.FindWindowW(None,TITLE)
        if hwnd:
            user.ShowWindow(hwnd,9)
            user.SetForegroundWindow(hwnd)
        kernel.CloseHandle(ctypes.c_void_p(mutex))
        return False,None
    return True,mutex


def main():
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TradingResearch.ControlPanel.v1")
        except (AttributeError,OSError):
            pass
    proceed,mutex=single_instance()
    if not proceed:
        return
    window=tk.Tk()
    ControlPanel(window)
    window.mainloop()
    if mutex and os.name=="nt":
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(mutex))


if __name__ == "__main__":
    main()
