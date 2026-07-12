"""
Cape May Weather Station – NOAA Station 8536110

Auto-refreshes every 6 minutes.
Layout (top to bottom): Atmosphere · Water Conditions · Next Tide ·
                        Tide-State Clock · Rolling 24-Hour Tide Graph

Dependencies:
    pip install requests matplotlib

On Raspberry Pi, tkinter may need: sudo apt install python3-tk
"""

import json
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, font as tkfont
from pathlib import Path
import requests
import threading
import numpy as np
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.dates as mdates
import matplotlib.image as mpimg
import matplotlib.ticker as mticker
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Polygon, Rectangle, FancyArrow
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

STATION_ID   = "8536110"
STATION_NAME = "Cape May, NJ"
BASE_URL     = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
REFRESH_MS   = 6 * 60 * 1000
WINDOW_HOURS = 12

_CONFIG_FILE = Path(__file__).with_suffix(".json")
_DEFAULTS: dict = {
    # Wind sport icons
    "windsurfer_min":  16,  "windsurfer_max": 27,
    "wingfoiler_min":  11,  "wingfoiler_max": 18,
    "windsurfer_icon":  "",
    "wingfoiler_icon":  "",
    # Fullscreen
    "controls_timeout": 15,
    # Layout
    "panel_layout":    None,
    # Font sizes
    "font_panel_title": 10,
    "font_label":       11,
    "font_value":       16,
    "font_unit":        10,
    "font_timestamp":    9,
    "font_clock_phase": 11,
    "font_clock_heading": 10,
    "font_clock_value": 16,
    "font_clock_time":  10,
    "font_clock_small":  8,
    "font_clock_wlevel": 11,
    "font_graph":        9,
    # Colors
    "color_accent":  "#44cccc",
    "color_dim":     "#bbbbbb",
    "color_fg":      "#ffffff",
    # Panel visibility (1 = shown, 0 = hidden)
    "panel_atm_visible":   1,
    "panel_water_visible": 1,
    "panel_next_visible":  1,
    "panel_clock_visible": 1,
    "panel_graph_visible": 1,
    # Title bar (1 = always show, 0 = always hide)
    "show_panel_titles":   1,
    # Inky Impression e-ink output
    "inky_orientation": "portrait",   # "portrait" (480x800) or "landscape" (800x480)
    "inky_saturation":  60,           # colour punch 0-100 mapped to 0.0-1.0
    "inky_refresh_min": 30,           # headless auto-refresh interval (minutes)
    "inky_flip":         0,           # 1 = rotate 180° for an upside-down mount
    # Per-element layout overrides from the Inky Preview editor (kept as a dict,
    # like panel_layout). Must be listed here or _load_settings() would drop it.
    "inky_layout":    None,
}

_PANEL_DEFAULTS: dict = {
    "atm":   {"x": 10,  "y": 10,  "w": 295, "h": 215},
    "water": {"x": 10,  "y": 235, "w": 295, "h": 120},
    "next":  {"x": 10,  "y": 365, "w": 295, "h": 155},
    "clock": {"x": 320, "y": 10,  "w": 320, "h": 540},
    "graph": {"x": 320, "y": 560, "w": 600, "h": 220},
}

MM_BG  = "#000000"
MM_FG  = "#ffffff"
MM_DIM = "#bbbbbb"
MM_SEP = "#2a2a2a"
MM_ACC = "#44cccc"


def _fmt_hour(x, _pos):
    dt = mdates.num2date(x)
    return f"{int(dt.strftime('%I'))}{dt.strftime('%p').lower()}"


def _hhmm(dt: datetime) -> str:
    return f"{int(dt.strftime('%I'))}:{dt.strftime('%M %p')}"


def _draw_windsurfer_icon(ax) -> None:
    """Simplified windsurfer icon: triangular striped sail, stick figure, board, waves."""
    B, W, K = MM_ACC, MM_BG, MM_FG
    ax.clear()
    ax.set_xlim(0, 10); ax.set_ylim(0, 10)
    ax.set_aspect("equal"); ax.axis("off"); ax.set_facecolor(MM_BG)

    wx = np.linspace(0.3, 8.7, 200)
    for dy in (0, 0.6):
        ax.plot(wx, 1.5 + dy + 0.22*np.sin((wx + dy*1.5)*2.3),
                color=B, lw=1.8, solid_capstyle="round")

    ax.add_patch(Polygon(
        [(1.4,2.0),(6.9,2.0),(7.4,2.25),(6.9,2.5),(1.4,2.5),(0.9,2.25)], fc=K, ec=K))

    ax.plot([5.1, 4.6], [2.3, 9.3], color=K, lw=2.0, solid_capstyle="round", zorder=6)

    sail_pts = np.array([[5.1, 2.3], [4.6, 9.3], [8.8, 4.2]])
    sail_p = Polygon(sail_pts, fc=W, ec=K, lw=1.5, zorder=4)
    ax.add_patch(sail_p)
    for i in range(7):
        y0 = 2.5 + i * 1.0
        stripe = Polygon([(2.5, y0), (9.5, y0), (9.5, y0+0.55), (2.5, y0+0.55)],
                          fc=B, ec="none", zorder=5)
        stripe.set_clip_path(sail_p)
        ax.add_patch(stripe)
    ax.add_patch(Polygon(sail_pts, fc="none", ec=K, lw=1.5, zorder=6))

    ax.plot([4.88, 3.30], [4.75, 3.30], color=K, lw=1.8, solid_capstyle="round", zorder=6)
    ax.plot([4.85, 3.30], [5.15, 3.30], color=K, lw=1.8, solid_capstyle="round", zorder=6)

    ax.add_patch(Circle((3.0, 3.85), 0.40, fc=K, ec=K, zorder=7))
    ax.plot([3.0, 3.5], [3.45, 2.60], color=K, lw=2.5, solid_capstyle="round", zorder=7)
    ax.plot([3.1, 3.30], [3.20, 3.30], color=K, lw=2.0, solid_capstyle="round", zorder=7)
    ax.plot([3.5, 2.85], [2.60, 2.30], color=K, lw=2.0, solid_capstyle="round", zorder=7)
    ax.plot([3.5, 4.10], [2.60, 2.30], color=K, lw=2.0, solid_capstyle="round", zorder=7)


def _draw_wingfoiler_icon(ax) -> None:
    """Simplified wingfoiler icon: crescent wing kite, stick figure, foil board, waves."""
    B, W, K = MM_ACC, MM_BG, MM_FG
    ax.clear()
    ax.set_xlim(0, 10); ax.set_ylim(0, 10)
    ax.set_aspect("equal"); ax.axis("off"); ax.set_facecolor(MM_BG)

    wx = np.linspace(0.3, 8.7, 200)
    for dy in (0, 0.6):
        ax.plot(wx, 2.7 + dy + 0.22*np.sin((wx + dy*1.5)*2.3),
                color=B, lw=1.8, solid_capstyle="round")

    ax.plot([5.1, 5.1], [1.5, 3.8], color=K, lw=2.5, solid_capstyle="round")
    ax.plot([3.2, 7.0], [1.5, 1.5], color=K, lw=2.5, solid_capstyle="round")
    ax.add_patch(Polygon(
        [(3.2,3.8),(6.9,3.8),(7.3,4.05),(6.9,4.3),(3.2,4.3),(2.8,4.05)], fc=K, ec=K, zorder=4))

    ax.add_patch(Circle((4.7, 6.10), 0.40, fc=K, ec=K, zorder=7))
    ax.plot([4.7, 4.7], [5.70, 4.85], color=K, lw=2.5, solid_capstyle="round", zorder=7)
    ax.plot([4.7, 5.7], [5.45, 6.10], color=K, lw=2.0, solid_capstyle="round", zorder=7)
    ax.plot([4.7, 4.1], [4.85, 4.35], color=K, lw=2.0, solid_capstyle="round", zorder=7)
    ax.plot([4.7, 5.3], [4.85, 4.35], color=K, lw=2.0, solid_capstyle="round", zorder=7)

    ax.plot([5.70, 7.0], [6.10, 9.85], color=K, lw=1.5, solid_capstyle="round", zorder=6)
    ax.plot([5.70, 9.0], [6.10, 7.40], color=K, lw=1.5, solid_capstyle="round", zorder=6)

    kx, ky = 8.0, 8.5
    r_out, r_in = 1.6, 0.90
    ang  = np.linspace(np.deg2rad(130), np.deg2rad(-50), 100)
    cx = np.concatenate([kx + r_out*np.cos(ang), kx + r_in*np.cos(ang[::-1])])
    cy = np.concatenate([ky + r_out*np.sin(ang), ky + r_in*np.sin(ang[::-1])])
    ax.fill(cx, cy, color=B, ec=K, lw=1.5, zorder=5)

    ang_w = np.linspace(np.deg2rad(20), np.deg2rad(-50), 50)
    wx2 = np.concatenate([kx + r_out*np.cos(ang_w), kx + r_in*np.cos(ang_w[::-1])])
    wy2 = np.concatenate([ky + r_out*np.sin(ang_w), ky + r_in*np.sin(ang_w[::-1])])
    ax.fill(wx2, wy2, color=W, ec="none", zorder=6)

    mid_r = (r_out + r_in) / 2
    ax.add_patch(Circle((kx + mid_r*np.cos(np.deg2rad(-20)),
                          ky + mid_r*np.sin(np.deg2rad(-20))),
                          0.22, fc=K, ec=K, zorder=7))
    ax.fill(cx, cy, color="none", ec=K, lw=1.5, zorder=8)


def _load_png_icon(ax, path: str, fig, bg: str = MM_BG) -> bool:
    """Render a PNG file onto ax over a solid background.  Returns True on success."""
    if not path:
        return False
    try:
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = _CONFIG_FILE.parent / resolved
        img = mpimg.imread(str(resolved))
        ax.clear()
        fig.set_facecolor(bg)
        ax.set_facecolor(bg)
        ax.imshow(img)
        ax.set_aspect("equal")
        ax.axis("off")
        return True
    except Exception:
        return False


# ── Draggable / resizable panel ────────────────────────────────────────────────

class _DraggablePanel:
    """Floating panel on a tk.Canvas that the user can drag by its title bar
    and resize by dragging any corner handle."""

    MIN_W  = 150
    MIN_H  = 80
    HANDLE = 10

    # Corner resize cursors. Windows uses "size_*"; X11 (Linux) / macOS use
    # directional corner names. Picked per-platform so the app runs on the Pi.
    import sys as _sys
    _CURSORS = ({"nw": "size_nw_se", "se": "size_nw_se",
                 "ne": "size_ne_sw", "sw": "size_ne_sw"}
                if _sys.platform.startswith("win") else
                {"nw": "top_left_corner",  "se": "bottom_right_corner",
                 "ne": "top_right_corner", "sw": "bottom_left_corner"})
    del _sys

    def __init__(self, canvas: tk.Canvas, title: str,
                 x: int, y: int, w: int, h: int,
                 on_moved=None, on_focus=None) -> None:
        self.canvas   = canvas
        self.title    = title
        self.x = x;  self.y = y
        self.w = w;  self.h = h
        self.on_moved = on_moved
        self.on_focus = on_focus
        self._active           = False
        self._titlebar_visible = True

        # ── Outer frame (border via highlightbackground) ───────────────────
        self.frame = tk.Frame(canvas, bg=MM_BG,
                              highlightbackground=MM_SEP,
                              highlightthickness=1)
        self.win_id = canvas.create_window(x, y, window=self.frame,
                                           anchor="nw", width=w, height=h)

        # ── Title bar ──────────────────────────────────────────────────────
        self._bar = tk.Frame(self.frame, bg="#0d1117", cursor="fleur")
        self._bar.pack(fill=tk.X, side=tk.TOP)
        self._lbl = tk.Label(self._bar, text=title.upper(),
                             bg="#0d1117", fg=MM_ACC,
                             font=("Arial", 10, "bold"), pady=4, padx=6)
        self._lbl.pack(side=tk.LEFT)

        # ── Content area ───────────────────────────────────────────────────
        self.content = tk.Frame(self.frame, bg=MM_BG)
        self.content.pack(fill=tk.BOTH, expand=True)

        # ── Drag bindings ──────────────────────────────────────────────────
        for w_ in (self._bar, self._lbl):
            w_.bind("<ButtonPress-1>",   self._drag_start)
            w_.bind("<B1-Motion>",       self._drag_motion)
            w_.bind("<ButtonRelease-1>", self._drag_end)

        # ── Focus-on-click bindings (frame + content propagate up) ────────
        for w_ in (self.frame, self.content):
            w_.bind("<ButtonPress-1>", self._on_click, add="+")

        # ── Corner resize handles ──────────────────────────────────────────
        self._handles: dict[str, tk.Frame] = {}
        for corner in ("nw", "ne", "sw", "se"):
            try:
                hf = tk.Frame(self.frame, bg=MM_ACC,
                              width=self.HANDLE, height=self.HANDLE,
                              cursor=self._CURSORS[corner])
            except tk.TclError:
                # Unknown cursor name on this platform — fall back to default.
                hf = tk.Frame(self.frame, bg=MM_ACC,
                              width=self.HANDLE, height=self.HANDLE)
            rx = 1.0 if "e" in corner else 0.0
            ry = 1.0 if "s" in corner else 0.0
            hf.place(relx=rx, rely=ry, anchor=corner)
            hf.bind("<ButtonPress-1>",   lambda e, c=corner: self._resize_start(e, c))
            hf.bind("<B1-Motion>",       lambda e, c=corner: self._resize_motion(e, c))
            hf.bind("<ButtonRelease-1>", lambda e, c=corner: self._resize_end(e))
            self._handles[corner] = hf

        # ── Drag state ─────────────────────────────────────────────────────
        self._dx = self._dy = 0

        # ── Resize state ───────────────────────────────────────────────────
        self._rx = self._ry = 0
        self._rw = self._rh = 0
        self._rpx = self._rpy = 0
        self._rcorner = ""

    # ── Drag ──────────────────────────────────────────────────────────────────

    def _on_click(self, event) -> None:
        if self.on_focus:
            self.on_focus(self)

    def set_active(self, active: bool) -> None:
        self._active = active
        bar_bg = "#1c3a5c" if active else "#0d1117"
        self._bar.config(bg=bar_bg)
        self._lbl.config(bg=bar_bg)
        border = MM_ACC if active else MM_SEP
        self.frame.config(highlightbackground=border, highlightthickness=1)

    def _drag_start(self, event) -> None:
        self._dx = event.x_root
        self._dy = event.y_root
        self.frame.lift()
        if self.on_focus:
            self.on_focus(self)

    def _drag_motion(self, event) -> None:
        self.x += event.x_root - self._dx
        self.y += event.y_root - self._dy
        self._dx = event.x_root
        self._dy = event.y_root
        self.canvas.coords(self.win_id, self.x, self.y)

    def _drag_end(self, event) -> None:
        if self.on_moved:
            self.on_moved()

    # ── Resize ────────────────────────────────────────────────────────────────

    def _resize_start(self, event, corner: str) -> None:
        self._rcorner = corner
        self._rx, self._ry   = event.x_root, event.y_root
        self._rw, self._rh   = self.w, self.h
        self._rpx, self._rpy = self.x, self.y
        self.frame.lift()

    def _resize_motion(self, event, corner: str) -> None:
        dx = event.x_root - self._rx
        dy = event.y_root - self._ry

        nw, nh = self._rw, self._rh
        nx, ny = self._rpx, self._rpy

        if "e" in corner:
            nw = max(self.MIN_W, self._rw + dx)
        else:
            nw = max(self.MIN_W, self._rw - dx)
            nx = self._rpx + (self._rw - nw)

        if "s" in corner:
            nh = max(self.MIN_H, self._rh + dy)
        else:
            nh = max(self.MIN_H, self._rh - dy)
            ny = self._rpy + (self._rh - nh)

        self.x, self.y = nx, ny
        self.w, self.h = nw, nh
        self.canvas.coords(self.win_id, nx, ny)
        self.canvas.itemconfig(self.win_id, width=nw, height=nh)

    def _resize_end(self, event) -> None:
        if self.on_moved:
            self.on_moved()

    def geometry(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    def set_titlebar_visible(self, visible: bool) -> None:
        self._titlebar_visible = visible
        if visible:
            if not self._bar.winfo_ismapped():
                self._bar.pack(fill=tk.X, side=tk.TOP, before=self.content)
        else:
            self._bar.pack_forget()

    def set_panel_visible(self, visible: bool) -> None:
        self.canvas.itemconfig(self.win_id,
                               state="normal" if visible else "hidden")

    def hide_drag_ui(self) -> None:
        # Hides corner handles and border; title bar obeys _titlebar_visible
        for hf in self._handles.values():
            hf.place_forget()
        self.frame.config(highlightthickness=0)

    def show_drag_ui(self) -> None:
        for corner, hf in self._handles.items():
            rx = 1.0 if "e" in corner else 0.0
            ry = 1.0 if "s" in corner else 0.0
            hf.place(relx=rx, rely=ry, anchor=corner)
        self.set_active(self._active)   # restore border colour
        self.set_titlebar_visible(self._titlebar_visible)


# ── Main application ───────────────────────────────────────────────────────────

class WeatherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"NOAA – {STATION_NAME}  (Station {STATION_ID})")
        self.root.resizable(True, True)
        self._refresh_job   = None
        self._countdown_job = None
        self._next_refresh  = None
        self.vars: dict[str, tk.StringVar] = {}
        self._scroll_canvas       = None
        self._wind_startup_done   = False
        self._last_wind_speed     = None
        self._is_fullscreen       = False
        self._pre_fs_geometry     = None
        self._controls_hide_job   = None
        self._active_panel        = None
        self._arrow_save_job      = None
        self._tracked_labels: list = []   # [(widget, role), …]
        self._last_gd: dict | None = None
        self.settings             = self._load_settings()
        self._build_ui()
        self.root.after(300, self._start_fetch)

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.root.configure(bg=MM_BG)

        # ── Controls bar (hidden in fullscreen) ───────────────────────────
        self._controls_frame = tk.Frame(self.root, bg=MM_BG)
        self._controls_frame.pack(fill=tk.X)

        ctrl = tk.Frame(self._controls_frame, bg=MM_BG, pady=6)
        ctrl.pack()
        self.btn = tk.Button(ctrl, text="  Refresh  ",
                             command=self._manual_refresh,
                             bg="#1a3a5c", fg=MM_FG, activebackground="#2255aa",
                             font=("Arial", 10, "bold"), relief=tk.FLAT,
                             padx=8, pady=4, cursor="hand2")
        self.btn.pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(ctrl, text="⟳  Sync Inky",
                  command=self._open_inky_preview,
                  bg="#3a1a4c", fg=MM_FG, activebackground="#5522aa",
                  font=("Arial", 10, "bold"), relief=tk.FLAT,
                  padx=8, pady=4, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(ctrl, text="⚙  Settings",
                  command=self._open_settings,
                  bg="#1a2a1a", fg=MM_FG, activebackground="#2a3a2a",
                  font=("Arial", 10), relief=tk.FLAT,
                  padx=8, pady=4, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(ctrl, text="⛶",
                  command=self._toggle_fullscreen,
                  bg="#1a1a2a", fg=MM_FG, activebackground="#2a2a3a",
                  font=("Arial", 10), relief=tk.FLAT,
                  padx=8, pady=4, cursor="hand2").pack(side=tk.LEFT, padx=(0, 14))
        self.countdown_var = tk.StringVar(value="")
        tk.Label(ctrl, textvariable=self.countdown_var,
                 bg=MM_BG, font=("Arial", 9), fg=MM_DIM).pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Starting up…")
        tk.Label(self._controls_frame, textvariable=self.status_var,
                 bg=MM_BG, fg=MM_DIM, font=("Arial", 9)).pack()

        # ── Body: free-form canvas for draggable panels ───────────────────
        self._body_frame = tk.Frame(self.root, bg=MM_BG)
        self._body_frame.pack(fill=tk.BOTH, expand=True)

        self._layout_canvas = tk.Canvas(self._body_frame, bg=MM_BG,
                                        highlightthickness=0)
        self._layout_canvas.pack(fill=tk.BOTH, expand=True)

        # Resolve saved panel positions
        saved = self.settings.get("panel_layout") or {}

        def _g(key):
            d = dict(_PANEL_DEFAULTS[key])
            d.update({k: v for k, v in saved.get(key, {}).items()
                      if k in ("x", "y", "w", "h")})
            return d

        # ── Atmosphere panel ──────────────────────────────────────────────
        g = _g("atm")
        atm_p = _DraggablePanel(self._layout_canvas, "Atmosphere",
                                g["x"], g["y"], g["w"], g["h"],
                                on_moved=self._save_panel_layout,
                                on_focus=self._on_panel_focus)
        self._panels = {"atm": atm_p}

        self._make_panel(atm_p.content, [
            ("Air Temp",   "air_temp",   "°F"),
            ("Wind Speed", "wind_speed", "kt"),
            ("Wind Gusts", "wind_gust",  "kt"),
            ("Wind Dir",   "wind_dir",   ""),
        ])

        self._icon_frame = tk.Frame(atm_p.content, bg=MM_BG)
        self._icon_frame.pack(pady=(2, 2))

        self._fig_ws = Figure(figsize=(1.4, 1.4), dpi=90)
        self._fig_ws.set_facecolor(MM_BG)
        self._fig_ws.subplots_adjust(0, 0, 1, 1)
        self._ax_ws = self._fig_ws.add_subplot(111)
        self._ws_canvas = FigureCanvasTkAgg(self._fig_ws, master=self._icon_frame)

        self._fig_wf = Figure(figsize=(1.4, 1.4), dpi=90)
        self._fig_wf.set_facecolor(MM_BG)
        self._fig_wf.subplots_adjust(0, 0, 1, 1)
        self._ax_wf = self._fig_wf.add_subplot(111)
        self._wf_canvas = FigureCanvasTkAgg(self._fig_wf, master=self._icon_frame)

        self._refresh_icon_display()
        self._ws_canvas.get_tk_widget().pack(side=tk.LEFT, padx=(4, 4))
        self._wf_canvas.get_tk_widget().pack(side=tk.LEFT, padx=(4, 4))
        self.root.after(5000, self._end_startup_icons)

        # ── Water Conditions panel ────────────────────────────────────────
        g = _g("water")
        water_p = _DraggablePanel(self._layout_canvas, "Water Conditions",
                                  g["x"], g["y"], g["w"], g["h"],
                                  on_moved=self._save_panel_layout,
                                  on_focus=self._on_panel_focus)
        self._panels["water"] = water_p
        self._make_panel(water_p.content, [
            ("Water Level", "water_level", "ft MLLW"),
            ("Water Temp",  "water_temp",  "°F"),
        ])

        # ── Next Tide panel ───────────────────────────────────────────────
        g = _g("next")
        next_p = _DraggablePanel(self._layout_canvas, "Next Tide",
                                 g["x"], g["y"], g["w"], g["h"],
                                 on_moved=self._save_panel_layout,
                                 on_focus=self._on_panel_focus)
        self._panels["next"] = next_p
        self._make_panel(next_p.content, [
            ("Type",   "tide_type",   ""),
            ("Time",   "tide_time",   ""),
            ("Height", "tide_height", "ft MLLW"),
        ])

        self.updated_var = tk.StringVar(value="")
        ts_lbl = tk.Label(next_p.content, textvariable=self.updated_var,
                          bg=MM_BG, fg=self.settings.get("color_dim", MM_DIM),
                          font=("Arial", self.settings.get("font_timestamp", 9)))
        ts_lbl.pack(anchor="w", padx=8)
        self._tracked_labels.append((ts_lbl, "timestamp"))

        # ── Tide Clock panel ──────────────────────────────────────────────
        g = _g("clock")
        clock_p = _DraggablePanel(self._layout_canvas, "Tide Clock",
                                  g["x"], g["y"], g["w"], g["h"],
                                  on_moved=self._save_panel_layout,
                                  on_focus=self._on_panel_focus)
        self._panels["clock"] = clock_p

        self._fig_clock = Figure(figsize=(4.2, 7.0), dpi=96)
        self._fig_clock.set_facecolor(MM_BG)
        self._fig_clock.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.ax_clock = self._fig_clock.add_subplot(111)

        self.canvas_clock = FigureCanvasTkAgg(self._fig_clock, master=clock_p.content)
        self.canvas_clock.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas_clock.get_tk_widget().bind("<Configure>", self._on_clock_resize)
        self.canvas_clock.get_tk_widget().bind(
            "<ButtonPress-1>", lambda e, p=clock_p: self._on_panel_focus(p), add="+")
        self._placeholder_clock()

        # ── Tide Graph panel ──────────────────────────────────────────────
        g = _g("graph")
        graph_p = _DraggablePanel(self._layout_canvas, "Tide Graph — 24h",
                                  g["x"], g["y"], g["w"], g["h"],
                                  on_moved=self._save_panel_layout,
                                  on_focus=self._on_panel_focus)
        self._panels["graph"] = graph_p

        self._fig_graph = Figure(figsize=(6.8, 2.8), dpi=96)
        self._fig_graph.set_facecolor(MM_BG)
        self._fig_graph.subplots_adjust(left=0.07, right=0.98, top=0.87, bottom=0.17)
        self.ax = self._fig_graph.add_subplot(111)

        self.canvas = FigureCanvasTkAgg(self._fig_graph, master=graph_p.content)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas.get_tk_widget().bind("<Configure>", self._on_graph_resize)
        self.canvas.get_tk_widget().bind(
            "<ButtonPress-1>", lambda e, p=graph_p: self._on_panel_focus(p), add="+")
        self._placeholder_graph()

        # ── Canvas background click deactivates active panel ──────────────
        self._layout_canvas.bind("<ButtonPress-1>", self._deactivate_panel)

        # ── Arrow keys move active panel ──────────────────────────────────
        for key in ("<Left>", "<Right>", "<Up>", "<Down>",
                    "<Shift-Left>", "<Shift-Right>", "<Shift-Up>", "<Shift-Down>"):
            self.root.bind(key, self._on_arrow_key)

        # ── Apply initial visibility from settings ────────────────────────
        self._apply_panel_visibility()
        self._apply_titlebar_visibility()

        # ── Fullscreen overlay bar + keyboard shortcuts ───────────────────
        self._build_overlay_bar()
        self.root.bind("<F11>",    lambda e: self._toggle_fullscreen())
        self.root.bind("<Escape>", lambda e: self._exit_fullscreen()
                                             if self._is_fullscreen else None)

    # ── Resize handlers ────────────────────────────────────────────────────────

    def _on_clock_resize(self, event) -> None:
        w = event.width / self._fig_clock.get_dpi()
        h = event.height / self._fig_clock.get_dpi()
        if w > 0.5 and h > 0.5:
            self._fig_clock.set_size_inches(w, h)
            self.canvas_clock.draw_idle()

    def _on_graph_resize(self, event) -> None:
        w = event.width / self._fig_graph.get_dpi()
        h = event.height / self._fig_graph.get_dpi()
        if w > 0.5 and h > 0.5:
            self._fig_graph.set_size_inches(w, h)
            self.canvas.draw_idle()

    def _save_panel_layout(self) -> None:
        layout = {k: p.geometry() for k, p in self._panels.items()}
        new = dict(self.settings)
        new["panel_layout"] = layout
        self.settings = new
        try:
            _CONFIG_FILE.write_text(json.dumps(new, indent=2))
        except Exception:
            pass

    def _apply_panel_visibility(self) -> None:
        for key, panel in self._panels.items():
            panel.set_panel_visible(bool(self.settings.get(f"panel_{key}_visible", 1)))

    def _apply_titlebar_visibility(self) -> None:
        show = bool(self.settings.get("show_panel_titles", 1))
        for panel in self._panels.values():
            panel.set_titlebar_visible(show)

    def _on_panel_focus(self, panel) -> None:
        if self._active_panel is panel:
            return
        if self._active_panel:
            self._active_panel.set_active(False)
        self._active_panel = panel
        panel.set_active(True)
        panel.frame.lift()

    def _deactivate_panel(self, event=None) -> None:
        if self._active_panel:
            self._active_panel.set_active(False)
            self._active_panel = None

    def _on_arrow_key(self, event) -> None:
        if not self._active_panel:
            return
        step = 50 if (event.state & 0x1) else 5   # Shift → 50 px, normal → 5 px
        sym  = event.keysym   # e.g. "Left", "Shift-Right" → keysym is just "Right"
        dx   = -step if "Left"  in sym else (step if "Right" in sym else 0)
        dy   = -step if "Up"    in sym else (step if "Down"  in sym else 0)

        p = self._active_panel
        p.x += dx
        p.y += dy
        p.canvas.coords(p.win_id, p.x, p.y)

        # Debounce layout save (only write after key activity stops)
        if self._arrow_save_job:
            self.root.after_cancel(self._arrow_save_job)
        self._arrow_save_job = self.root.after(400, self._save_panel_layout)

    def _apply_font_settings(self) -> None:
        """Update all tracked tkinter labels and redraw matplotlib figures."""
        s   = self.settings
        lf  = s.get("font_label",       11)
        vf  = s.get("font_value",       16)
        uf  = s.get("font_unit",        10)
        tf  = s.get("font_timestamp",    9)
        ptf = s.get("font_panel_title", 10)
        acc = s.get("color_accent", MM_ACC)
        dim = s.get("color_dim",   MM_DIM)
        fg  = s.get("color_fg",    MM_FG)

        for p in self._panels.values():
            p._lbl.config(font=("Arial", ptf, "bold"), fg=acc)

        for widget, role in self._tracked_labels:
            try:
                if role == "label":
                    widget.config(font=("Arial", lf, "bold"), fg=dim)
                elif role == "value":
                    widget.config(font=("Arial", vf, "bold"), fg=fg)
                elif role == "unit":
                    widget.config(font=("Arial", uf), fg=dim)
                elif role == "timestamp":
                    widget.config(font=("Arial", tf), fg=dim)
            except tk.TclError:
                pass

        if self._last_gd is not None:
            self._redraw_graph(self._last_gd)
            self._draw_tide_clock(self._last_gd)

    # ── Panel builder ──────────────────────────────────────────────────────────

    def _make_panel(self, parent: tk.Widget, fields: list) -> None:
        s = self.settings
        grid = tk.Frame(parent, bg=MM_BG)
        grid.pack(fill=tk.X, padx=8, pady=6)
        grid.columnconfigure(1, weight=1)
        for row, (label, key, unit) in enumerate(fields):
            lbl = tk.Label(grid, text=f"{label}:", bg=MM_BG,
                           fg=s.get("color_dim", MM_DIM),
                           font=("Arial", s.get("font_label", 11), "bold"),
                           anchor="w")
            lbl.grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
            self._tracked_labels.append((lbl, "label"))

            var = tk.StringVar(value="—")
            self.vars[key] = var
            val_lbl = tk.Label(grid, textvariable=var, bg=MM_BG,
                               fg=s.get("color_fg", MM_FG),
                               font=("Arial", s.get("font_value", 16), "bold"),
                               anchor="w")
            val_lbl.grid(row=row, column=1, sticky="w")
            self._tracked_labels.append((val_lbl, "value"))

            if unit:
                u_lbl = tk.Label(grid, text=unit, bg=MM_BG,
                                 fg=s.get("color_dim", MM_DIM),
                                 font=("Arial", s.get("font_unit", 10)),
                                 anchor="w")
                u_lbl.grid(row=row, column=2, sticky="w", padx=(4, 0))
                self._tracked_labels.append((u_lbl, "unit"))

    # ── Placeholders ───────────────────────────────────────────────────────────

    def _placeholder_clock(self) -> None:
        ax = self.ax_clock
        ax.clear()
        ax.axis("off")
        ax.set_facecolor(MM_BG)
        ax.set_xlim(-1.5, 1.5)
        ax.set_ylim(-2.4, 2.6)
        ax.text(0, 0, "Waiting for data…",
                ha="center", va="center", color=MM_DIM, fontsize=13)
        self.canvas_clock.draw()

    def _placeholder_graph(self) -> None:
        self.ax.clear()
        self.ax.set_facecolor(MM_BG)
        self.ax.axis("off")
        self.ax.text(0.5, 0.5, "Waiting for data…",
                     ha="center", va="center",
                     transform=self.ax.transAxes, color=MM_DIM, fontsize=11)
        self.canvas.draw()

    # ── Refresh scheduling ─────────────────────────────────────────────────────

    def _manual_refresh(self) -> None:
        for job in (self._refresh_job, self._countdown_job):
            if job:
                self.root.after_cancel(job)
        self._refresh_job = self._countdown_job = None
        self._next_refresh = None
        self._start_fetch()

    def _schedule_next(self) -> None:
        self._next_refresh = datetime.now() + timedelta(milliseconds=REFRESH_MS)
        self._refresh_job  = self.root.after(REFRESH_MS, self._auto_refresh)
        self._tick_countdown()

    def _auto_refresh(self) -> None:
        self._refresh_job = None
        self._start_fetch()

    def _tick_countdown(self) -> None:
        if not self._next_refresh:
            return
        secs = int((self._next_refresh - datetime.now()).total_seconds())
        if secs > 0:
            m, s = divmod(secs, 60)
            self.countdown_var.set(f"Next refresh in {m}:{s:02d}")
            self._countdown_job = self.root.after(1000, self._tick_countdown)
        else:
            self.countdown_var.set("")

    # ── Data fetching (background thread) ─────────────────────────────────────

    def _start_fetch(self) -> None:
        self.btn.config(state=tk.DISABLED)
        self._set_status("Fetching data from NOAA…", "#0055aa")
        for v in self.vars.values():
            v.set("…")
        threading.Thread(target=self._fetch_thread, daemon=True).start()

    def _fetch_thread(self) -> None:
        now     = datetime.now()
        results: dict = {}

        try:
            d = self._api(product="air_temperature", date="latest")
            results["air_temp"] = f"{float(d['data'][0]['v']):.1f}"
        except Exception:
            results["air_temp"] = "N/A"

        try:
            d = self._api(product="wind", date="latest")
            w = d["data"][0]
            results["wind_speed"] = f"{float(w['s']):.1f}"
            results["wind_gust"]  = f"{float(w['g']):.1f}"
            results["wind_dir"]   = f"{w.get('dr','?')}  ({w.get('d','?')}°)"
        except Exception:
            results["wind_speed"] = results["wind_gust"] = results["wind_dir"] = "N/A"

        try:
            d = self._api(product="water_level", date="latest", datum="MLLW")
            results["water_level"] = f"{float(d['data'][0]['v']):+.2f}"
        except Exception:
            results["water_level"] = "N/A"

        try:
            d = self._api(product="water_temperature", date="latest")
            results["water_temp"] = f"{float(d['data'][0]['v']):.1f}"
        except Exception:
            results["water_temp"] = "N/A"

        try:
            d = self._api(product="predictions",
                          begin_date=now.strftime("%Y%m%d"),
                          end_date=(now + timedelta(days=2)).strftime("%Y%m%d"),
                          interval="hilo", datum="MLLW")
            nxt = next((p for p in d.get("predictions", [])
                        if datetime.strptime(p["t"], "%Y-%m-%d %H:%M") > now), None)
            if nxt:
                t = datetime.strptime(nxt["t"], "%Y-%m-%d %H:%M")
                results["tide_type"]   = "High Tide" if nxt["type"] == "H" else "Low Tide"
                results["tide_time"]   = t.strftime("%a %b %d  %I:%M %p")
                results["tide_height"] = f"{float(nxt['v']):.2f}"
            else:
                results["tide_type"] = results["tide_time"] = results["tide_height"] = "N/A"
        except Exception:
            results["tide_type"] = results["tide_time"] = results["tide_height"] = "N/A"

        results["_graph"] = self._fetch_graph(now)

        self.root.after(0, self._apply_results, results)

    def _fetch_graph(self, now: datetime) -> dict:
        w_start = now - timedelta(hours=WINDOW_HOURS)
        w_end   = now + timedelta(hours=WINDOW_HOURS)

        obs_t,  obs_v          = [], []
        pred_t, pred_v         = [], []
        hilo_t, hilo_v, hilo_k = [], [], []

        try:
            d = self._api(product="water_level",
                          begin_date=w_start.strftime("%Y%m%d %H:%M"),
                          end_date=now.strftime("%Y%m%d %H:%M"),
                          datum="MLLW")
            for pt in d.get("data", []):
                try:
                    obs_t.append(datetime.strptime(pt["t"], "%Y-%m-%d %H:%M"))
                    obs_v.append(float(pt["v"]))
                except (ValueError, KeyError):
                    pass
        except Exception:
            pass

        try:
            d = self._api(product="predictions",
                          begin_date=now.strftime("%Y%m%d %H:%M"),
                          end_date=w_end.strftime("%Y%m%d %H:%M"),
                          interval="6", datum="MLLW")
            for pt in d.get("predictions", []):
                try:
                    pred_t.append(datetime.strptime(pt["t"], "%Y-%m-%d %H:%M"))
                    pred_v.append(float(pt["v"]))
                except (ValueError, KeyError):
                    pass
        except Exception:
            pass

        # Fetch HILO for graph window + 1 extra day so the clock always has
        # a future event to switch to after passing ebb/flood maximum.
        try:
            d = self._api(product="predictions",
                          begin_date=w_start.strftime("%Y%m%d"),
                          end_date=(w_end + timedelta(days=1)).strftime("%Y%m%d"),
                          interval="hilo", datum="MLLW")
            for pt in d.get("predictions", []):
                try:
                    hilo_t.append(datetime.strptime(pt["t"], "%Y-%m-%d %H:%M"))
                    hilo_v.append(float(pt["v"]))
                    hilo_k.append(pt["type"])
                except (ValueError, KeyError):
                    pass
        except Exception:
            pass

        return {
            "now": now, "w_start": w_start, "w_end": w_end,
            "obs":  (obs_t,  obs_v),
            "pred": (pred_t, pred_v),
            "hilo": (hilo_t, hilo_v, hilo_k),
        }

    def _api(self, **params) -> dict:
        defaults = {
            "station":   STATION_ID,
            "units":     "english",
            "time_zone": "lst_ldt",
            "format":    "json",
        }
        defaults.update(params)
        r = requests.get(BASE_URL, params=defaults, timeout=15)
        r.raise_for_status()
        data: dict = r.json()
        if "error" in data:
            raise ValueError(data["error"]["message"])
        return data

    # ── UI update (main thread) ────────────────────────────────────────────────

    def _apply_results(self, results: dict) -> None:
        for key, val in results.items():
            if key in self.vars:
                self.vars[key].set(val)
        if "_graph" in results:
            self._last_gd = results["_graph"]
            self._redraw_graph(self._last_gd)
            self._draw_tide_clock(self._last_gd)
        ts = datetime.now().strftime("%Y-%m-%d  %I:%M:%S %p")
        self.updated_var.set(f"Last updated: {ts}")
        self._set_status("Live  •  Auto-refreshes every 6 minutes", MM_DIM)
        self.btn.config(state=tk.NORMAL)
        try:
            self._last_wind_speed = float(self.vars["wind_speed"].get())
        except (ValueError, TypeError):
            self._last_wind_speed = None
        if self._wind_startup_done:
            self._apply_wind_icon_rules()
        self._schedule_next()

    def _redraw_graph(self, gd: dict) -> None:
        s   = self.settings
        gf  = s.get("font_graph", 9)
        acc = s.get("color_accent", MM_ACC)
        dim = s.get("color_dim",   MM_DIM)

        ax = self.ax
        ax.clear()
        ax.set_facecolor(MM_BG)

        now     = gd["now"]
        w_start = gd["w_start"]
        w_end   = gd["w_end"]
        obs_t,  obs_v          = gd["obs"]
        pred_t, pred_v         = gd["pred"]
        hilo_t, hilo_v, hilo_k = gd["hilo"]

        if obs_t:
            ax.plot(obs_t, obs_v, color=acc, linewidth=2,
                    label="Observed", zorder=3, solid_capstyle="round")
            ax.fill_between(obs_t, obs_v, alpha=0.15, color=acc)

        if pred_t:
            ax.plot(pred_t, pred_v, color=acc, linewidth=1.5,
                    linestyle="--", alpha=0.5, label="Predicted", zorder=2)

        for t, v, k in zip(hilo_t, hilo_v, hilo_k):
            if t < w_start or t > w_end:
                continue
            is_high = k == "H"
            color   = "#ff6666" if is_high else "#66ff99"
            offset  = (0, 14) if is_high else (0, -18)
            lbl     = f"{'H' if is_high else 'L'}\n{v:.1f} ft"
            ax.scatter([t], [v], color=color, s=36, zorder=5)
            ax.annotate(lbl, xy=(t, v), xytext=offset,
                        textcoords="offset points",
                        ha="center", fontsize=gf, fontweight="bold", color=color,
                        arrowprops=dict(arrowstyle="-", color=color, lw=0.7))

        ax.axvline(now, color="#ff9900", linewidth=1.8, linestyle="-",
                   zorder=4, label="Now")

        ax.set_xlim(w_start, w_end)
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=3))
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(_fmt_hour))
        ax.set_ylabel("ft  (MLLW)", fontsize=gf + 1, color=dim, labelpad=4)
        ax.tick_params(axis="both", labelsize=gf, colors=dim)
        ax.grid(axis="y", linestyle=":", alpha=0.3, color=dim)
        ax.grid(axis="x", linestyle=":", alpha=0.15, color=dim)
        for spine in ax.spines.values():
            spine.set_edgecolor(MM_SEP)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        if obs_t or pred_t:
            legend = ax.legend(fontsize=gf, loc="upper left", framealpha=0.0,
                               handlelength=1.6)
            for text in legend.get_texts():
                text.set_color(dim)

        date_str = now.strftime("%b %d, %Y")
        ax.set_title(
            f"{date_str}  —  {w_start.strftime('%I:%M %p')} → {w_end.strftime('%I:%M %p')}",
            fontsize=gf + 1, color=dim, pad=4,
        )
        self.canvas.draw()

    # ── Tide-state clock ───────────────────────────────────────────────────────

    def _draw_tide_clock(self, gd: dict) -> None:
        """
        Card-style tide clock.  Layout (top → bottom):
          header bar  ·  HIGH TIDE  ·  clock face  ·  LOW TIDE

        Hand spins counter-clockwise:
          12 o'clock = HIGH tide    6 o'clock = LOW tide
           9 o'clock = Ebb max      3 o'clock = Flood max
        """
        s  = self.settings
        CF = s.get("font_clock_phase",   11)
        CH = s.get("font_clock_heading", 10)
        CV = s.get("font_clock_value",   16)
        CT = s.get("font_clock_time",    10)
        CS = s.get("font_clock_small",    8)
        CW = s.get("font_clock_wlevel",  11)

        ax = self.ax_clock
        ax.clear()
        ax.axis("off")
        ax.set_xlim(-1.5, 1.5)
        ax.set_ylim(-2.4, 2.6)

        CARD  = MM_BG
        TEAL  = s.get("color_accent", MM_ACC)
        WATER = "#051a22"
        SAND  = "#1a0e05"
        BEZEL = "#151f25"
        EBB_F = "#1a1205"
        FLD_F = "#051520"

        ax.set_facecolor(CARD)

        now                     = gd["now"]
        hilo_t, hilo_v, hilo_k  = gd["hilo"]
        water_level_str         = self.vars.get(
            "water_level", tk.StringVar(value="N/A")).get()

        if not hilo_t:
            ax.text(0, 0, "No tide data", ha="center", va="center",
                    fontsize=13, color=TEAL)
            self.canvas_clock.draw()
            return

        events  = sorted(zip(hilo_t, hilo_v, hilo_k), key=lambda e: e[0])
        prev_ev = next((e for e in reversed(events) if e[0] <= now), None)
        next_ev = next((e for e in events          if e[0] >  now), None)

        def first_after(typ, ref):
            return next((e for e in events if e[2] == typ and e[0] > ref), None)

        display_high = first_after("H", now)
        display_low  = first_after("L", now)

        hand_angle = None
        phase_text = "—"
        progress   = 0.0

        if prev_ev and next_ev:
            elapsed  = (now - prev_ev[0]).total_seconds()
            total    = (next_ev[0] - prev_ev[0]).total_seconds()
            progress = max(0.0, min(1.0, elapsed / total)) if total > 0 else 0.0
            pct      = int(progress * 100)

            if prev_ev[2] == "H":
                display_low = next_ev
                if progress < 0.5:
                    display_high = prev_ev
                else:
                    display_high = first_after("H", next_ev[0])
                hand_angle = np.pi / 2 + progress * np.pi
                phase_text = f"↓  EBBING  {pct}%"
            else:
                display_high = next_ev
                if progress < 0.5:
                    display_low = prev_ev
                else:
                    display_low = first_after("L", next_ev[0])
                hand_angle = 3 * np.pi / 2 + progress * np.pi
                phase_text = f"↑  FLOODING  {pct}%"

        elif next_ev:
            if next_ev[2] == "L":
                display_low  = next_ev
                hand_angle   = np.pi / 2
                phase_text   = "↓  EBBING"
            else:
                display_high = next_ev
                hand_angle   = 3 * np.pi / 2
                phase_text   = "↑  FLOODING"

        # ── Wave background scene ─────────────────────────────────────────
        x_bg   = np.linspace(-1.5, 1.5, 400)
        wave_y = 0.09 * np.sin(x_bg * 3.8)
        ax.fill_between(x_bg,  wave_y,  2.6,  color=WATER, alpha=0.5, zorder=0)
        ax.fill_between(x_bg, -2.4,    wave_y, color=SAND,  alpha=0.4, zorder=0)

        # ── Header bar ────────────────────────────────────────────────────
        ax.add_patch(Rectangle((-1.5, 2.08), 3.0, 0.52, color=TEAL, zorder=10))
        ax.plot([0.12, 0.12], [2.10, 2.58],
                color="white", alpha=0.35, linewidth=1, zorder=11)
        ax.text(-1.38, 2.34, phase_text,
                ha="left", va="center", fontsize=CF, fontweight="bold",
                color="white", zorder=11)
        ax.text(0.26, 2.46, "WATER LEVEL",
                ha="left", va="center", fontsize=max(5, CW - 4),
                color="white", alpha=0.9, zorder=11)
        ax.text(0.26, 2.24, f"{water_level_str} ft",
                ha="left", va="center", fontsize=CW, fontweight="bold",
                color="white", zorder=11)

        # ── HIGH TIDE label ───────────────────────────────────────────────
        wx = np.linspace(-0.25, 0.25, 80)
        ax.plot(wx, 0.038 * np.sin(wx * 25) + 1.92,
                color=TEAL, lw=1.8, alpha=0.7, zorder=5)
        ax.text(0, 1.73, "HIGH TIDE", ha="center", va="center",
                fontsize=CH, fontweight="bold", color=TEAL, zorder=5)
        if display_high:
            ax.text(0, 1.52, f"{display_high[1]:+.2f} ft",
                    ha="center", va="center", fontsize=CV,
                    fontweight="bold", color=TEAL, zorder=5)
            ax.text(0, 1.33, f"at  {_hhmm(display_high[0])}",
                    ha="center", va="center", fontsize=CT,
                    color=TEAL, alpha=0.9, zorder=5)

        # ── Clock face ────────────────────────────────────────────────────
        R  = 0.90
        BZ = 0.13

        ax.add_patch(Circle((0, 0), R + BZ, color=BEZEL, zorder=6))
        ax.add_patch(Circle((0, 0), R + BZ,
                             fill=False, edgecolor=TEAL,
                             linewidth=1.5, zorder=7))

        for theta, fc in [
            (np.linspace(np.pi / 2, 3 * np.pi / 2, 200), EBB_F),
            (np.linspace(-np.pi / 2, np.pi / 2,    200), FLD_F),
        ]:
            xs = np.concatenate([[0], R * np.cos(theta), [0]])
            ys = np.concatenate([[0], R * np.sin(theta), [0]])
            ax.fill(xs, ys, color=fc, zorder=8)

        t_ring = np.linspace(0, 2 * np.pi, 360)
        ax.plot(R * np.cos(t_ring), R * np.sin(t_ring),
                color=TEAL, linewidth=1.5, zorder=9)

        for i in range(12):
            ta    = np.pi / 2 - i * (np.pi / 6)
            major = (i % 3 == 0)
            r_in  = R - (0.12 if major else 0.06)
            ax.plot([r_in * np.cos(ta), R * np.cos(ta)],
                    [r_in * np.sin(ta), R * np.sin(ta)],
                    color=TEAL, linewidth=(2.0 if major else 1.0), zorder=9)

        LX = R + BZ + 0.07
        ax.text(-LX, 0, "EBB\nMAX",   ha="right", va="center",
                fontsize=CS, fontweight="bold", color=TEAL, zorder=5)
        ax.text( LX, 0, "FLOOD\nMAX", ha="left",  va="center",
                fontsize=CS, fontweight="bold", color=TEAL, zorder=5)

        # ── Clock hand ────────────────────────────────────────────────────
        if hand_angle is not None:
            sr  = 0.08
            tip = R * 0.86
            ax.add_patch(FancyArrow(
                -sr  * np.cos(hand_angle),
                -sr  * np.sin(hand_angle),
                (tip + sr) * np.cos(hand_angle),
                (tip + sr) * np.sin(hand_angle),
                width=0.032, head_width=0.088, head_length=0.095,
                fc=TEAL, ec=TEAL, length_includes_head=True, zorder=12,
            ))

        ax.add_patch(Circle((0, 0), 0.052, color=TEAL, zorder=13))

        # ── LOW TIDE label ────────────────────────────────────────────────
        ax.plot(wx, 0.038 * np.sin(wx * 25) - 1.23,
                color=TEAL, lw=1.8, alpha=0.7, zorder=5)
        ax.text(0, -1.43, "LOW TIDE", ha="center", va="center",
                fontsize=CH, fontweight="bold", color=TEAL, zorder=5)
        if display_low:
            ax.text(0, -1.63, f"{display_low[1]:+.2f} ft",
                    ha="center", va="center", fontsize=CV,
                    fontweight="bold", color=TEAL, zorder=5)
            ax.text(0, -1.83, f"at  {_hhmm(display_low[0])}",
                    ha="center", va="center", fontsize=CT,
                    color=TEAL, alpha=0.9, zorder=5)

        self.canvas_clock.draw()

    def _end_startup_icons(self) -> None:
        self._wind_startup_done = True
        self._apply_wind_icon_rules()

    def _apply_wind_icon_rules(self) -> None:
        spd = self._last_wind_speed
        s   = self.settings
        show_ws = spd is not None and s["windsurfer_min"] <= spd <= s["windsurfer_max"]
        show_wf = spd is not None and s["wingfoiler_min"] <= spd <= s["wingfoiler_max"]

        ws_w = self._ws_canvas.get_tk_widget()
        wf_w = self._wf_canvas.get_tk_widget()
        ws_w.pack_forget()
        wf_w.pack_forget()
        if show_ws:
            ws_w.pack(side=tk.LEFT, padx=(4, 4))
        if show_wf:
            wf_w.pack(side=tk.LEFT, padx=(4, 4))

        if show_ws or show_wf:
            self._icon_frame.pack(pady=(4, 2))
        else:
            self._icon_frame.pack_forget()

    # ── Fullscreen + auto-hide controls ───────────────────────────────────────

    def _build_overlay_bar(self) -> None:
        """Dark control bar placed over the window in fullscreen; hidden by default."""
        BAR = "#111827"
        self._overlay_bar = tk.Frame(self.root, bg=BAR, pady=5)

        left = tk.Frame(self._overlay_bar, bg=BAR)
        left.pack(side=tk.LEFT, padx=(10, 0))
        tk.Button(left, text="↺  Refresh", command=self._manual_refresh,
                  bg="#1a4a8a", fg="white", activebackground="#2266bb",
                  font=("Arial", 9, "bold"), relief=tk.FLAT,
                  padx=8, pady=3, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(left, text="⚙  Settings", command=self._open_settings,
                  bg="#334455", fg="white", activebackground="#445566",
                  font=("Arial", 9), relief=tk.FLAT,
                  padx=8, pady=3, cursor="hand2").pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(left, textvariable=self.countdown_var,
                 bg=BAR, fg="#aaaaaa", font=("Arial", 8)).pack(side=tk.LEFT)

        right = tk.Frame(self._overlay_bar, bg=BAR)
        right.pack(side=tk.RIGHT, padx=(0, 6))
        for label, cmd, hover in [
            ("  —  ", self.root.iconify,      "#334466"),
            ("  ⛶  ", self._exit_fullscreen,  "#334466"),
            ("  ✕  ", self.root.destroy,      "#992222"),
        ]:
            tk.Button(right, text=label, command=cmd,
                      bg=BAR, fg="white", activebackground=hover,
                      font=("Arial", 10), relief=tk.FLAT,
                      pady=3, cursor="hand2").pack(side=tk.LEFT, padx=1)

    def _toggle_fullscreen(self) -> None:
        if self._is_fullscreen:
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _get_monitor_geometry(self) -> tuple:
        """Return (x, y, w, h) of the monitor the window currently occupies."""
        import platform
        if platform.system() == "Windows":
            try:
                import ctypes

                class _RECT(ctypes.Structure):
                    _fields_ = [("left",   ctypes.c_long), ("top",    ctypes.c_long),
                                ("right",  ctypes.c_long), ("bottom", ctypes.c_long)]

                class _MONITORINFO(ctypes.Structure):
                    _fields_ = [("cbSize",    ctypes.c_ulong),
                                ("rcMonitor", _RECT),
                                ("rcWork",    _RECT),
                                ("dwFlags",   ctypes.c_ulong)]

                hwnd = self.root.winfo_id()
                mon  = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)
                info = _MONITORINFO()
                info.cbSize = ctypes.sizeof(_MONITORINFO)
                ctypes.windll.user32.GetMonitorInfoW(mon, ctypes.byref(info))
                r = info.rcMonitor
                return r.left, r.top, r.right - r.left, r.bottom - r.top
            except Exception:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _enter_fullscreen(self) -> None:
        self._is_fullscreen = True
        self._pre_fs_geometry = self.root.geometry()
        mx, my, mw, mh = self._get_monitor_geometry()
        self.root.overrideredirect(True)
        self.root.geometry(f"{mw}x{mh}+{mx}+{my}")
        self.root.lift()
        self.root.focus_force()
        self._controls_frame.pack_forget()
        self._show_controls()
        self.root.bind_all("<Motion>", self._on_mouse_move)
        self._schedule_controls_hide()

    def _exit_fullscreen(self) -> None:
        self._is_fullscreen = False
        self.root.overrideredirect(False)
        if self._pre_fs_geometry:
            self.root.geometry(self._pre_fs_geometry)
        self._overlay_bar.place_forget()
        if self._controls_hide_job:
            self.root.after_cancel(self._controls_hide_job)
            self._controls_hide_job = None
        self.root.unbind_all("<Motion>")
        self._controls_frame.pack(before=self._body_frame)
        for p in self._panels.values():
            p.show_drag_ui()

    def _show_controls(self) -> None:
        self._overlay_bar.place(x=0, y=0, relwidth=1.0)
        self._overlay_bar.lift()
        for p in self._panels.values():
            p.show_drag_ui()

    def _hide_controls(self) -> None:
        self._controls_hide_job = None
        if self._is_fullscreen:
            self._overlay_bar.place_forget()
            for p in self._panels.values():
                p.hide_drag_ui()

    def _on_mouse_move(self, event=None) -> None:
        if not self._is_fullscreen:
            return
        self._show_controls()
        self._schedule_controls_hide()

    def _schedule_controls_hide(self) -> None:
        if self._controls_hide_job:
            self.root.after_cancel(self._controls_hide_job)
        ms = self.settings.get("controls_timeout", 15) * 1000
        self._controls_hide_job = self.root.after(ms, self._hide_controls)

    # ── Settings persistence ───────────────────────────────────────────────────

    def _load_settings(self) -> dict:
        try:
            raw = json.loads(_CONFIG_FILE.read_text())
            result = dict(_DEFAULTS)
            for k, default in _DEFAULTS.items():
                if k not in raw:
                    continue
                if default is None:
                    result[k] = raw[k] if isinstance(raw[k], dict) else None
                elif isinstance(default, int):
                    result[k] = int(raw[k])
                else:
                    result[k] = str(raw[k])
            return result
        except Exception:
            return dict(_DEFAULTS)

    def _save_settings(self, new: dict) -> None:
        self.settings = new
        try:
            _CONFIG_FILE.write_text(json.dumps(new, indent=2))
        except Exception:
            pass
        self._refresh_icon_display()
        self._apply_font_settings()
        self._apply_panel_visibility()
        self._apply_titlebar_visibility()

    def _refresh_icon_display(self) -> None:
        if not _load_png_icon(self._ax_ws, self.settings.get("windsurfer_icon", ""),
                               self._fig_ws, MM_BG):
            self._fig_ws.set_facecolor(MM_BG)
            _draw_windsurfer_icon(self._ax_ws)
        if not _load_png_icon(self._ax_wf, self.settings.get("wingfoiler_icon", ""),
                               self._fig_wf, MM_BG):
            self._fig_wf.set_facecolor(MM_BG)
            _draw_wingfoiler_icon(self._ax_wf)
        self._ws_canvas.draw()
        self._wf_canvas.draw()

    def _open_settings(self) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("Settings")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.focus_set()

        nb = ttk.Notebook(dlg)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))

        # ── helpers ──────────────────────────────────────────────────────────
        def _spinbox(parent, row, col, key, lo, hi, label, unit=""):
            tk.Label(parent, text=f"{label}:", font=("Arial", 10),
                     anchor="w").grid(row=row, column=col,
                                      sticky="w", padx=(0, 8), pady=3)
            sb = tk.Spinbox(parent, from_=lo, to=hi, width=5,
                            font=("Arial", 10), justify="center")
            sb.delete(0, "end")
            sb.insert(0, str(self.settings.get(key, _DEFAULTS[key])))
            sb.grid(row=row, column=col + 1, sticky="w")
            if unit:
                tk.Label(parent, text=unit, font=("Arial", 9),
                         fg="#555555").grid(row=row, column=col + 2,
                                            sticky="w", padx=(4, 0))
            return sb

        color_vars: dict[str, tk.StringVar] = {}

        def _color_row(parent, row, key, label):
            var = tk.StringVar(value=self.settings.get(key, _DEFAULTS[key]))
            color_vars[key] = var
            tk.Label(parent, text=f"{label}:", font=("Arial", 10),
                     anchor="w").grid(row=row, column=0,
                                      sticky="w", padx=(0, 10), pady=3)
            btn = tk.Button(parent, text=var.get(),
                            bg=var.get(), fg="white",
                            font=("Arial", 9), width=9, relief=tk.FLAT)

            def _pick(b=btn, v=var):
                res = colorchooser.askcolor(color=v.get(), parent=dlg)
                if res[1]:
                    v.set(res[1].lower())
                    b.config(text=res[1].lower(), bg=res[1])

            btn.config(command=_pick)
            btn.grid(row=row, column=1, sticky="w")

        # ── Tab 1: Wind Icons ─────────────────────────────────────────────
        tab_icons = tk.Frame(nb, padx=14, pady=10)
        nb.add(tab_icons, text="  Wind Icons  ")

        spb:       dict[str, tk.Spinbox]   = {}
        path_vars: dict[str, tk.StringVar] = {}

        for sport, icon_key, speed_keys in [
            ("Windsurfer", "windsurfer_icon", ("windsurfer_min", "windsurfer_max")),
            ("Wingfoiler", "wingfoiler_icon", ("wingfoiler_min", "wingfoiler_max")),
        ]:
            lf = ttk.LabelFrame(tab_icons, text=f"  {sport}  ", padding=(12, 6))
            lf.pack(fill=tk.X, pady=(0, 8))
            lf.columnconfigure(1, weight=1)
            for row, (key, lbl) in enumerate(
                    zip(speed_keys, ("Min speed", "Max speed"))):
                spb[key] = _spinbox(lf, row, 0, key, 0, 99, lbl, "knots")

            tk.Label(lf, text="Icon PNG:", font=("Arial", 10),
                     anchor="w").grid(row=2, column=0, sticky="w",
                                      padx=(0, 10), pady=(8, 2))
            pv = tk.StringVar(value=self.settings.get(icon_key, ""))
            path_vars[icon_key] = pv
            tk.Entry(lf, textvariable=pv, font=("Arial", 9),
                     width=30).grid(row=2, column=1, columnspan=2,
                                    sticky="ew", pady=(8, 2))

            def _browse(var=pv):
                p = filedialog.askopenfilename(
                    title="Select icon PNG",
                    filetypes=[("PNG images", "*.png"), ("All files", "*.*")])
                if p:
                    var.set(p)

            tk.Button(lf, text="Browse…", command=_browse,
                      font=("Arial", 9), padx=6).grid(row=3, column=1,
                                                       sticky="w", pady=(0, 4))

        # ── Tab 2: Display ────────────────────────────────────────────────
        tab_disp = tk.Frame(nb, padx=14, pady=10)
        nb.add(tab_disp, text="  Display  ")

        # Inky Impression (e-ink) output
        lf_inky = ttk.LabelFrame(tab_disp, text="  Inky Impression (E-Ink)  ",
                                 padding=(12, 6))
        lf_inky.pack(fill=tk.X, pady=(0, 10))
        tk.Label(lf_inky, text="Orientation:", font=("Arial", 10),
                 anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        inky_orient_var = tk.StringVar(
            value=self.settings.get("inky_orientation", "portrait"))
        ttk.Combobox(lf_inky, textvariable=inky_orient_var, state="readonly",
                     width=22, font=("Arial", 10),
                     values=["portrait (480×800)", "landscape (800×480)"]
                     ).grid(row=0, column=1, sticky="w")
        # Show the friendly label but keep the stored value clean
        inky_orient_var.set("landscape (800×480)"
                            if self.settings.get("inky_orientation") == "landscape"
                            else "portrait (480×800)")
        inky_sat_sb = _spinbox(lf_inky, 1, 0, "inky_saturation", 0, 100,
                               "Colour saturation", "%")
        inky_refresh_sb = _spinbox(lf_inky, 2, 0, "inky_refresh_min", 1, 1440,
                                   "Auto-refresh every", "min")
        inky_flip_var = tk.IntVar(value=self.settings.get("inky_flip", 0))
        tk.Checkbutton(lf_inky, text="Flip 180° (upside-down mount)",
                       variable=inky_flip_var, font=("Arial", 10)
                       ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        tk.Label(lf_inky,
                 text="Refresh rate controls the headless updater "
                      "(runs with no monitor attached).",
                 font=("Arial", 8), fg="#777777", wraplength=320, justify="left"
                 ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # Auto-hide
        lf_t = ttk.LabelFrame(tab_disp,
                               text="  Auto-hide Controls (Full Screen)  ",
                               padding=(12, 6))
        lf_t.pack(fill=tk.X, pady=(0, 10))
        timeout_sb = _spinbox(lf_t, 0, 0, "controls_timeout", 1, 300,
                              "Hide after", "seconds")

        # Font sizes — Data Panels
        lf_fp = ttk.LabelFrame(tab_disp, text="  Font Sizes — Data Panels  ",
                                padding=(12, 6))
        lf_fp.pack(fill=tk.X, pady=(0, 8))
        font_spb: dict[str, tk.Spinbox] = {}
        font_spb["font_panel_title"] = _spinbox(lf_fp, 0, 0, "font_panel_title",
                                                4, 40, "Panel title",  "pt")
        font_spb["font_label"]       = _spinbox(lf_fp, 1, 0, "font_label",
                                                4, 40, "Field labels", "pt")
        font_spb["font_value"]       = _spinbox(lf_fp, 2, 0, "font_value",
                                                4, 60, "Data values",  "pt")
        font_spb["font_unit"]        = _spinbox(lf_fp, 3, 0, "font_unit",
                                                4, 40, "Units",        "pt")
        font_spb["font_timestamp"]   = _spinbox(lf_fp, 4, 0, "font_timestamp",
                                                4, 24, "Timestamp",    "pt")

        # Font sizes — Tide Clock
        lf_fc = ttk.LabelFrame(tab_disp, text="  Font Sizes — Tide Clock  ",
                                padding=(12, 6))
        lf_fc.pack(fill=tk.X, pady=(0, 8))
        font_spb["font_clock_phase"]   = _spinbox(lf_fc, 0, 0, "font_clock_phase",
                                                  4, 40, "Phase text",      "pt")
        font_spb["font_clock_heading"] = _spinbox(lf_fc, 1, 0, "font_clock_heading",
                                                  4, 40, "HIGH/LOW heading", "pt")
        font_spb["font_clock_value"]   = _spinbox(lf_fc, 2, 0, "font_clock_value",
                                                  4, 60, "Tide heights",     "pt")
        font_spb["font_clock_time"]    = _spinbox(lf_fc, 3, 0, "font_clock_time",
                                                  4, 40, "Tide times",       "pt")
        font_spb["font_clock_wlevel"]  = _spinbox(lf_fc, 4, 0, "font_clock_wlevel",
                                                  4, 40, "Water level",      "pt")
        font_spb["font_clock_small"]   = _spinbox(lf_fc, 5, 0, "font_clock_small",
                                                  4, 24, "EBB/FLOOD labels", "pt")
        font_spb["font_graph"]         = _spinbox(lf_fc, 6, 0, "font_graph",
                                                  4, 24, "Graph text",       "pt")

        # Colors
        lf_c = ttk.LabelFrame(tab_disp, text="  Colors  ", padding=(12, 6))
        lf_c.pack(fill=tk.X, pady=(0, 8))
        _color_row(lf_c, 0, "color_accent", "Accent")
        _color_row(lf_c, 1, "color_dim",    "Dim text")
        _color_row(lf_c, 2, "color_fg",     "Main text")

        # Panel visibility
        lf_pv = ttk.LabelFrame(tab_disp, text="  Panel Visibility  ", padding=(12, 6))
        lf_pv.pack(fill=tk.X, pady=(0, 8))
        panel_vis_vars: dict[str, tk.IntVar] = {}
        PANEL_LABELS = [
            ("atm",   "Atmosphere"),
            ("water", "Water Conditions"),
            ("next",  "Next Tide"),
            ("clock", "Tide Clock"),
            ("graph", "Tide Graph"),
        ]
        for col, (key, label) in enumerate(PANEL_LABELS):
            var = tk.IntVar(value=self.settings.get(f"panel_{key}_visible", 1))
            panel_vis_vars[key] = var
            tk.Checkbutton(lf_pv, text=label, variable=var,
                           font=("Arial", 10)).grid(row=0, column=col,
                                                    sticky="w", padx=(0, 14))

        # Title bar visibility
        lf_tb = ttk.LabelFrame(tab_disp, text="  Panel Title Bars  ", padding=(12, 6))
        lf_tb.pack(fill=tk.X, pady=(0, 8))
        show_titles_var = tk.IntVar(value=self.settings.get("show_panel_titles", 1))
        tk.Checkbutton(lf_tb, text="Show title bars (never auto-hide)",
                       variable=show_titles_var,
                       font=("Arial", 10)).grid(row=0, column=0, sticky="w")

        # ── Save / Cancel ─────────────────────────────────────────────────
        def _save():
            new: dict = dict(self.settings)  # carry over panel_layout etc.
            for key, sb in spb.items():
                try:
                    new[key] = max(0, min(99, int(sb.get())))
                except ValueError:
                    new[key] = _DEFAULTS[key]
            for mn, mx in (("windsurfer_min", "windsurfer_max"),
                            ("wingfoiler_min", "wingfoiler_max")):
                if new[mn] > new[mx]:
                    new[mn], new[mx] = new[mx], new[mn]
            for key, pv in path_vars.items():
                new[key] = pv.get().strip()
            try:
                new["controls_timeout"] = max(1, min(300, int(timeout_sb.get())))
            except ValueError:
                new["controls_timeout"] = _DEFAULTS["controls_timeout"]
            for key, sb in font_spb.items():
                lo, hi = (4, 60) if "value" in key else (4, 40)
                try:
                    new[key] = max(lo, min(hi, int(sb.get())))
                except ValueError:
                    new[key] = _DEFAULTS[key]
            for key, var in color_vars.items():
                new[key] = var.get().strip() or _DEFAULTS[key]
            for key, var in panel_vis_vars.items():
                new[f"panel_{key}_visible"] = var.get()
            new["show_panel_titles"] = show_titles_var.get()
            new["inky_orientation"] = ("landscape"
                                       if inky_orient_var.get().startswith("landscape")
                                       else "portrait")
            try:
                new["inky_saturation"] = max(0, min(100, int(inky_sat_sb.get())))
            except ValueError:
                new["inky_saturation"] = _DEFAULTS["inky_saturation"]
            try:
                new["inky_refresh_min"] = max(1, min(1440, int(inky_refresh_sb.get())))
            except ValueError:
                new["inky_refresh_min"] = _DEFAULTS["inky_refresh_min"]
            new["inky_flip"] = inky_flip_var.get()
            self._save_settings(new)
            if self._wind_startup_done:
                self._apply_wind_icon_rules()
            dlg.destroy()

        btn_row = tk.Frame(dlg)
        btn_row.pack(pady=10)
        tk.Button(btn_row, text="Cancel", command=dlg.destroy,
                  font=("Arial", 10), padx=14, pady=4).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(btn_row, text="Save", command=_save,
                  bg="#0055aa", fg="white", activebackground="#0077cc",
                  font=("Arial", 10, "bold"), padx=14, pady=4).pack(side=tk.LEFT)

    # ── Inky Impression (e-ink) export ─────────────────────────────────────────

    def _gather_inky_payload(self) -> dict:
        """Collect already-fetched data into the payload the renderer expects."""
        s = self.settings

        def gv(key):
            try:
                return self.vars[key].get()
            except Exception:
                return "N/A"

        spd = self._last_wind_speed
        sports = []
        if spd is not None:
            if s["windsurfer_min"] <= spd <= s["windsurfer_max"]:
                sports.append("Windsurf")
            if s["wingfoiler_min"] <= spd <= s["wingfoiler_max"]:
                sports.append("Wingfoil")

        return {
            "station":   STATION_NAME,
            "timestamp": datetime.now().strftime("%b %d  %-I:%M %p"),
            "conditions": {
                "air_temp":    gv("air_temp"),
                "wind_speed":  gv("wind_speed"),
                "wind_gust":   gv("wind_gust"),
                "wind_dir":    gv("wind_dir"),
                "water_level": gv("water_level"),
                "water_temp":  gv("water_temp"),
            },
            "tide": {
                "type":   gv("tide_type"),
                "time":   gv("tide_time"),
                "height": gv("tide_height"),
            },
            "graph": self._last_gd,
            "sport": " + ".join(sports) if sports else None,
        }

    def _render_inky_image(self, return_meta=False):
        """Build the full-resolution PIL image for the panel (current settings)."""
        import inky_render
        orient = self.settings.get("inky_orientation", "portrait")
        out = inky_render.render_eink(self._gather_inky_payload(), orient,
                                      settings=self.settings, return_meta=return_meta)
        if return_meta:
            img, meta = out
            return img, meta, orient
        return out, orient

    # ── Inky Preview / Layout Editor ───────────────────────────────────────────

    def _open_inky_preview(self) -> None:
        """Interactive layout editor: click text fields to select (Shift or drag a
        box to multi-select), arrow keys nudge, +/- resize font. Saved to config."""
        from tkinter import messagebox
        try:
            from PIL import ImageTk  # noqa: F401
            img, meta, orient = self._render_inky_image(return_meta=True)
        except Exception as e:
            messagebox.showerror("Inky Preview",
                                 f"Could not render preview:\n{e}", parent=self.root)
            return

        sh = self.root.winfo_screenheight()
        sw = self.root.winfo_screenwidth()
        scale = min((sh - 200) / img.height, (sw - 380) / img.width, 1.6)

        dlg = tk.Toplevel(self.root)
        dlg.title("Inky Preview — Layout Editor")
        dlg.configure(bg="#222222")
        # Wayland/XWayland tends to open Tk pop-ups behind the parent — force it
        # to a visible spot and bring it to the front.
        dlg.geometry("+60+40")
        dlg.lift()
        dlg.attributes("-topmost", True)
        dlg.after(400, lambda: dlg.winfo_exists() and dlg.attributes("-topmost", False))
        dlg.focus_force()

        body = tk.Frame(dlg, bg="#222222")
        body.pack(padx=12, pady=12)

        canvas = tk.Canvas(body, bg="#dddddd", highlightthickness=1,
                           highlightbackground="#000000",
                           width=int(img.width * scale), height=int(img.height * scale),
                           cursor="hand2")
        canvas.grid(row=0, column=0, rowspan=2)

        # ── right-hand control column ──────────────────────────────────────────
        side = tk.Frame(body, bg="#222222")
        side.grid(row=0, column=1, sticky="n", padx=(12, 0))
        tk.Label(side, text="LAYOUT EDITOR", bg="#222222", fg="#ffffff",
                 font=("Arial", 11, "bold")).pack(anchor="w")
        help_txt = ("Click a field to select it.\n"
                    "Shift-click adds to selection.\n"
                    "Drag a box to select several.\n\n"
                    "Arrow keys — nudge (1 px)\n"
                    "Shift+Arrow — nudge (10 px)\n"
                    "+ / −  — font size\n"
                    "  (graph: +/− resizes it)\n"
                    "Esc / click empty — deselect\n\n"
                    "Every change auto-saves to\ncape_may_weather.json and\n"
                    "is what the panel shows.")
        tk.Label(side, text=help_txt, bg="#222222", fg="#bbbbbb", justify="left",
                 font=("Arial", 9)).pack(anchor="w", pady=(4, 10))

        ed_status = tk.StringVar(value="Nothing selected.")
        tk.Label(side, textvariable=ed_status, bg="#222222", fg="#88cc88",
                 justify="left", wraplength=210, font=("Arial", 9)).pack(anchor="w")

        btns = tk.Frame(side, bg="#222222")
        btns.pack(anchor="w", pady=(14, 0))
        send_btn = tk.Button(btns, text="  Send to Inky ▶  ",
                             bg="#5522aa", fg="white", activebackground="#6633bb",
                             font=("Arial", 11, "bold"), relief=tk.FLAT,
                             padx=12, pady=6, cursor="hand2")
        send_btn.pack(anchor="w", pady=(0, 6))
        tk.Button(btns, text="↻ Refresh data", command=lambda: self._ed_render(),
                  bg="#333", fg="white", relief=tk.FLAT, font=("Arial", 10),
                  padx=10, pady=5, cursor="hand2").pack(anchor="w", pady=(0, 6))
        tk.Button(btns, text="⟲ Reset layout", command=self._ed_reset,
                  bg="#333", fg="white", relief=tk.FLAT, font=("Arial", 10),
                  padx=10, pady=5, cursor="hand2").pack(anchor="w", pady=(0, 6))
        tk.Button(btns, text="Close", command=dlg.destroy,
                  bg="#333", fg="white", relief=tk.FLAT, font=("Arial", 10),
                  padx=10, pady=5, cursor="hand2").pack(anchor="w")

        # editor state
        self._ed = {
            "dlg": dlg, "canvas": canvas, "scale": scale, "orient": orient,
            "img": img, "meta": meta, "tkimg": None, "img_item": None,
            "sel": set(), "status": ed_status, "send_btn": send_btn,
            "render_job": None, "save_job": None, "press": None, "band": None,
        }
        send_btn.config(command=lambda: self._push_to_inky(
            self._ed["img"], ed_status, send_btn))

        canvas.bind("<ButtonPress-1>", self._ed_on_press)
        canvas.bind("<B1-Motion>", self._ed_on_motion)
        canvas.bind("<ButtonRelease-1>", self._ed_on_release)
        for key in ("<Left>", "<Right>", "<Up>", "<Down>",
                    "<Shift-Left>", "<Shift-Right>", "<Shift-Up>", "<Shift-Down>"):
            dlg.bind(key, self._ed_on_arrow)
        for key in ("<plus>", "<KP_Add>", "<equal>"):
            dlg.bind(key, lambda e: self._ed_font(+1))
        for key in ("<minus>", "<KP_Subtract>", "<underscore>"):
            dlg.bind(key, lambda e: self._ed_font(-1))
        dlg.bind("<Escape>", lambda e: self._ed_set_selection(set()))
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.focus_set()

        self._ed_blit()          # show current render on the canvas

    # -- editor internals ---------------------------------------------------------

    def _ed_over_root(self) -> dict:
        """The per-orientation override dict inside settings["inky_layout"]."""
        lay = self.settings.get("inky_layout")
        if not isinstance(lay, dict):
            lay = {}
            self.settings["inky_layout"] = lay
        o = self._ed["orient"]
        if not isinstance(lay.get(o), dict):
            lay[o] = {}
        return lay[o]

    def _ed_blit(self) -> None:
        """Push the current PIL image + selection overlay onto the canvas."""
        from PIL import ImageTk
        ed = self._ed
        s = ed["scale"]
        disp = ed["img"].resize((max(1, int(ed["img"].width * s)),
                                 max(1, int(ed["img"].height * s))))
        ed["tkimg"] = ImageTk.PhotoImage(disp)
        c = ed["canvas"]
        if ed["img_item"] is None:
            ed["img_item"] = c.create_image(0, 0, anchor="nw", image=ed["tkimg"])
        else:
            c.itemconfig(ed["img_item"], image=ed["tkimg"])
        self._ed_draw_overlay()

    def _ed_draw_overlay(self) -> None:
        ed = self._ed
        c = ed["canvas"]
        s = ed["scale"]
        c.delete("sel")
        for eid in ed["sel"]:
            m = ed["meta"].get(eid)
            if not m:
                continue
            l, t, r, b = m["bbox"]
            c.create_rectangle(l * s - 2, t * s - 2, r * s + 2, b * s + 2,
                               outline="#ff2266", width=2, tags="sel")
        n = len(ed["sel"])
        if n == 0:
            ed["status"].set("Nothing selected.")
        else:
            ed["status"].set(f"{n} selected: " + ", ".join(sorted(ed["sel"])))

    def _ed_render(self) -> None:
        """Re-fetch layout from settings, re-render the image, refresh canvas."""
        ed = self._ed
        ed["render_job"] = None
        try:
            img, meta, _ = self._render_inky_image(return_meta=True)
        except Exception as e:
            ed["status"].set(f"Render error: {e}")
            return
        ed["img"], ed["meta"] = img, meta
        self._ed_blit()

    def _ed_schedule_render(self) -> None:
        ed = self._ed
        if ed["render_job"]:
            ed["dlg"].after_cancel(ed["render_job"])
        ed["render_job"] = ed["dlg"].after(90, self._ed_render)

    def _ed_save(self) -> None:
        try:
            _CONFIG_FILE.write_text(json.dumps(self.settings, indent=2))
        except Exception:
            pass

    def _ed_schedule_save(self) -> None:
        ed = self._ed
        if ed["save_job"]:
            ed["dlg"].after_cancel(ed["save_job"])
        ed["save_job"] = ed["dlg"].after(400, self._ed_save)

    def _ed_hit(self, ix, iy):
        """Return the id of the smallest element whose box contains image px (ix,iy)."""
        best, best_area = None, None
        for eid, m in self._ed["meta"].items():
            l, t, r, b = m["bbox"]
            if l <= ix <= r and t <= iy <= b:
                area = (r - l) * (b - t)
                if best_area is None or area < best_area:
                    best, best_area = eid, area
        return best

    def _ed_set_selection(self, ids) -> None:
        self._ed["sel"] = set(ids)
        self._ed_draw_overlay()

    def _ed_on_press(self, event) -> None:
        ed = self._ed
        s = ed["scale"]
        ix, iy = event.x / s, event.y / s
        ed["press"] = (event.x, event.y, bool(event.state & 0x0001))  # shift?
        hit = self._ed_hit(ix, iy)
        ed["_press_hit"] = hit
        ed["band"] = None

    def _ed_on_motion(self, event) -> None:
        ed = self._ed
        if ed.get("_press_hit") is not None or ed["press"] is None:
            return  # started on an element → treat as click, not a band
        c = ed["canvas"]
        x0, y0, _shift = ed["press"]
        if ed["band"] is None:
            if abs(event.x - x0) < 4 and abs(event.y - y0) < 4:
                return
            ed["band"] = c.create_rectangle(x0, y0, event.x, event.y,
                                            outline="#3399ff", dash=(4, 3), tags="band")
        c.coords(ed["band"], x0, y0, event.x, event.y)

    def _ed_on_release(self, event) -> None:
        ed = self._ed
        s = ed["scale"]
        c = ed["canvas"]
        if ed["press"] is None:
            return
        x0, y0, shift = ed["press"]
        if ed["band"] is not None:                       # rubber-band select
            l, t = min(x0, event.x) / s, min(y0, event.y) / s
            r, b = max(x0, event.x) / s, max(y0, event.y) / s
            inside = {eid for eid, m in ed["meta"].items()
                      if not (m["bbox"][2] < l or m["bbox"][0] > r
                              or m["bbox"][3] < t or m["bbox"][1] > b)}
            ed["sel"] = (ed["sel"] | inside) if shift else inside
            c.delete("band")
            ed["band"] = None
        else:                                            # click select
            hit = ed.get("_press_hit")
            if hit is None:
                if not shift:
                    ed["sel"] = set()
            elif shift:
                ed["sel"] ^= {hit}
            else:
                ed["sel"] = {hit}
        ed["press"] = None
        ed["_press_hit"] = None
        self._ed_draw_overlay()

    def _ed_on_arrow(self, event) -> str:
        step = 10 if (event.state & 0x0001) else 1     # Shift = bigger step
        dx = {"Left": -step, "Right": step}.get(event.keysym, 0)
        dy = {"Up": -step, "Down": step}.get(event.keysym, 0)
        self._ed_nudge(dx, dy)
        return "break"

    def _ed_nudge(self, dxpx, dypx) -> None:
        import inky_render
        ed = self._ed
        if not ed["sel"]:
            return
        W, H = ed["img"].width, ed["img"].height
        dxn, dyn = dxpx / W, dypx / H
        cur = inky_render._resolve_layout(ed["orient"], self.settings)
        over = self._ed_over_root()
        for eid in ed["sel"]:
            v = cur[eid]
            if eid == "graph":
                over[eid] = {"x": v[0] + dxn, "y": v[1] + dyn, "w": v[2], "h": v[3]}
            else:
                over[eid] = {"x": v[0] + dxn, "y": v[1] + dyn, "size": v[2]}
        ed["canvas"].move("sel", dxpx * ed["scale"], dypx * ed["scale"])  # instant feedback
        self._ed_schedule_save()
        self._ed_schedule_render()

    def _ed_font(self, delta) -> str:
        import inky_render
        ed = self._ed
        if not ed["sel"]:
            return "break"
        cur = inky_render._resolve_layout(ed["orient"], self.settings)
        over = self._ed_over_root()
        for eid in ed["sel"]:
            v = cur[eid]
            if eid == "graph":       # no font — scale the box instead
                f = 1.0 + 0.03 * delta
                over[eid] = {"x": v[0], "y": v[1],
                             "w": max(0.1, v[2] * f), "h": max(0.1, v[3] * f)}
            else:
                over[eid] = {"x": v[0], "y": v[1], "size": max(4, int(v[2]) + delta)}
        self._ed_schedule_save()
        self._ed_schedule_render()
        return "break"

    def _ed_reset(self) -> None:
        from tkinter import messagebox
        if not messagebox.askyesno("Reset layout",
                                   "Reset all positions and font sizes to defaults "
                                   f"for {self._ed['orient']} orientation?",
                                   parent=self._ed["dlg"]):
            return
        lay = self.settings.get("inky_layout")
        if isinstance(lay, dict):
            lay.pop(self._ed["orient"], None)
        self._ed["sel"] = set()
        self._ed_save()
        self._ed_render()

    def _push_to_inky(self, img, status_var, send_btn) -> None:
        """Push the rendered image to the panel on a background thread (~35s).

        Delegates to inky_update.send_to_inky so the GUI and the headless
        updater share one code path (rotation, flip, saturation)."""
        sat  = self.settings.get("inky_saturation", 60) / 100.0
        flip = bool(self.settings.get("inky_flip", 0))
        send_btn.config(state=tk.DISABLED)
        status_var.set("Sending to Inky… (~35s, panel will flash — normal)")

        def _work():
            try:
                import inky_update
                ok, msg = inky_update.send_to_inky(img, saturation=sat, flip=flip)
                text = ("✓ Sent to Inky — panel updated." if ok
                        else f"✗ Inky error: {msg}")
            except Exception as e:
                text = f"✗ Inky error: {e}"
            self.root.after(0, lambda: status_var.set(text))
            self.root.after(0, lambda: send_btn.config(state=tk.NORMAL))

        threading.Thread(target=_work, daemon=True).start()

    def _set_status(self, msg: str, color: str = "#555555") -> None:
        self.status_var.set(msg)
        self.root.update_idletasks()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    root.minsize(580, 600)
    WeatherApp(root)
    root.mainloop()
