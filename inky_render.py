#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Headless e-ink renderer for the Cape May Weather dashboard.

Every text field is a named, individually-positionable element with its own
font size, read from the config ("inky_layout").  This lets the GUI's Inky
Preview act as a WYSIWYG layout editor (click / nudge / resize font) whose
result is the very image pushed to the panel.

render_eink(payload, orientation, settings, return_meta=True) also returns each
element's pixel bounding box so the editor can hit-test and draw selections.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # no display / no Tk — safe to import headless
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from PIL import Image

# ── Spectra-6-friendly palette ────────────────────────────────────────────────
E_BG      = "#ffffff"
E_FG      = "#000000"
E_DIM     = "#333333"
E_ACCENT  = "#0033cc"
E_HIGH    = "#cc0000"
E_LOW     = "#007000"
E_NOW     = "#cc0000"
E_SEP     = "#000000"

RESOLUTIONS = {"portrait": (480, 800), "landscape": (800, 480)}
DPI = 100


def resolution_for(orientation: str) -> tuple[int, int]:
    return RESOLUTIONS.get(orientation, RESOLUTIONS["portrait"])


# ── Text elements ─────────────────────────────────────────────────────────────
# Each: (id, getter(payload, g) -> str, color, weight)  — all left/top-anchored.
def _cond(key):
    return lambda p, g: g(key)


TEXT_ELEMENTS = [
    ("station",     lambda p, g: p.get("station", "Cape May, NJ"),          E_FG,    "bold"),
    ("timestamp",   lambda p, g: f"Updated {p.get('timestamp', '')}",       E_DIM,   "normal"),
    ("temp",        lambda p, g: f"{g('air_temp')}°F",                       E_FG,    "bold"),
    ("wind_label",  lambda p, g: "Wind",                                     E_FG,    "normal"),
    ("wind_val",    lambda p, g: f"{g('wind_speed')} kt",                    E_FG,    "bold"),
    ("gusts_label", lambda p, g: "Gusts",                                    E_FG,    "normal"),
    ("gusts_val",   lambda p, g: f"{g('wind_gust')} kt",                     E_FG,    "bold"),
    ("dir_label",   lambda p, g: "Dir",                                      E_FG,    "normal"),
    ("dir_val",     lambda p, g: g("wind_dir"),                              E_FG,    "bold"),
    ("water_label", lambda p, g: "Water",                                    E_FG,    "normal"),
    ("water_val",   lambda p, g: f"{g('water_level')} ft",                   E_FG,    "bold"),
    ("wtemp_label", lambda p, g: "Temp",                                     E_FG,    "normal"),
    ("wtemp_val",   lambda p, g: f"{g('water_temp')}°F",                     E_FG,    "bold"),
    ("sport",       lambda p, g: (f"► Good for: {p['sport']}" if p.get("sport") else ""), E_LOW, "bold"),
    ("next_header", lambda p, g: "NEXT TIDE",                                E_ACCENT, "bold"),
    ("tide_type",   lambda p, g: p.get("tide", {}).get("type", "N/A"),       None,    "bold"),
    ("tide_time",   lambda p, g: p.get("tide", {}).get("time", "N/A"),       E_FG,    "normal"),
    ("tide_height", lambda p, g: f"{p.get('tide', {}).get('height', 'N/A')} ft MLLW", E_DIM, "normal"),
]

# Default layouts: id -> (x, y, size)  in normalised top-left coords; y grows down.
# "graph" -> (x, y, w, h) rectangle.
DEFAULT_LAYOUTS = {
    "portrait": {
        "station":     (0.06, 0.035, 23),
        "timestamp":   (0.06, 0.085, 11),
        "temp":        (0.06, 0.150, 44),
        "wind_label":  (0.06, 0.300, 14), "wind_val":  (0.30, 0.300, 17),
        "gusts_label": (0.06, 0.340, 14), "gusts_val": (0.30, 0.340, 17),
        "dir_label":   (0.06, 0.380, 14), "dir_val":   (0.30, 0.380, 17),
        "water_label": (0.06, 0.420, 14), "water_val": (0.30, 0.420, 17),
        "wtemp_label": (0.06, 0.460, 14), "wtemp_val": (0.30, 0.460, 17),
        "sport":       (0.06, 0.500, 15),
        "next_header": (0.06, 0.570, 13),
        "tide_type":   (0.06, 0.610, 25),
        "tide_time":   (0.06, 0.660, 15),
        "tide_height": (0.06, 0.700, 13),
        "graph":       (0.06, 0.760, 0.90, 0.215),
    },
    "landscape": {
        "station":     (0.04, 0.05, 22),
        "timestamp":   (0.04, 0.12, 11),
        "temp":        (0.04, 0.20, 40),
        "wind_label":  (0.04, 0.36, 13), "wind_val":  (0.18, 0.36, 16),
        "gusts_label": (0.04, 0.43, 13), "gusts_val": (0.18, 0.43, 16),
        "dir_label":   (0.04, 0.50, 13), "dir_val":   (0.18, 0.50, 16),
        "water_label": (0.04, 0.57, 13), "water_val": (0.18, 0.57, 16),
        "wtemp_label": (0.04, 0.64, 13), "wtemp_val": (0.18, 0.64, 16),
        "sport":       (0.04, 0.71, 14),
        "next_header": (0.04, 0.80, 12),
        "tide_type":   (0.04, 0.855, 22),
        "tide_time":   (0.04, 0.915, 13),
        "tide_height": (0.04, 0.955, 12),
        "graph":       (0.52, 0.14, 0.45, 0.78),
    },
}


def selectable_ids() -> list:
    return [e[0] for e in TEXT_ELEMENTS] + ["graph"]


def _temp_color(air_temp_str) -> str:
    """Air-temperature colour: <50°F blue, >75°F red, otherwise black."""
    try:
        t = float(air_temp_str)
    except (TypeError, ValueError):
        return E_FG
    if t < 50:
        return E_ACCENT   # blue
    if t > 75:
        return E_HIGH     # red
    return E_FG           # black


def _resolve_layout(orientation: str, settings: dict | None) -> dict:
    base = DEFAULT_LAYOUTS.get(orientation, DEFAULT_LAYOUTS["portrait"])
    over = ((settings or {}).get("inky_layout") or {}).get(orientation, {}) or {}
    out = {}
    for eid, dv in base.items():
        o = over.get(eid, {}) or {}
        if eid == "graph":
            out[eid] = (o.get("x", dv[0]), o.get("y", dv[1]),
                        o.get("w", dv[2]), o.get("h", dv[3]))
        else:
            out[eid] = (o.get("x", dv[0]), o.get("y", dv[1]), o.get("size", dv[2]))
    return out


def _fig_to_image(canvas: FigureCanvasAgg) -> Image.Image:
    w, h = canvas.get_width_height()
    return Image.frombuffer("RGBA", (w, h), canvas.buffer_rgba(),
                            "raw", "RGBA", 0, 1).convert("RGB")


def _draw_graph(ax, gd: dict) -> None:
    now, w_start, w_end = gd["now"], gd["w_start"], gd["w_end"]
    obs_t, obs_v = gd["obs"]
    pred_t, pred_v = gd["pred"]
    hilo_t, hilo_v, hilo_k = gd["hilo"]

    ax.set_facecolor(E_BG)
    if obs_t:
        ax.plot(obs_t, obs_v, color=E_ACCENT, linewidth=2.6, zorder=3,
                solid_capstyle="round")
        ax.fill_between(obs_t, obs_v, min(obs_v) - 0.5, alpha=0.12, color=E_ACCENT)
    if pred_t:
        ax.plot(pred_t, pred_v, color=E_DIM, linewidth=1.8, linestyle="--",
                alpha=0.9, zorder=2)
    for t, v, k in zip(hilo_t, hilo_v, hilo_k):
        if t < w_start or t > w_end:
            continue
        is_high = k == "H"
        color = E_HIGH if is_high else E_LOW
        offset = (0, 11) if is_high else (0, -13)
        ax.scatter([t], [v], color=color, s=40, zorder=5)
        ax.annotate(f"{'H' if is_high else 'L'} {v:.1f}", xy=(t, v), xytext=offset,
                    textcoords="offset points", ha="center", fontsize=10,
                    fontweight="bold", color=color)
    ax.axvline(now, color=E_NOW, linewidth=2.0, zorder=4)
    ax.set_xlim(w_start, w_end)
    vals = list(obs_v) + list(pred_v) + [v for t, v in zip(hilo_t, hilo_v)
                                         if w_start <= t <= w_end]
    if vals:
        lo, hi = min(vals), max(vals)
        rng = max(hi - lo, 1.0)
        ax.set_ylim(lo - 0.30 * rng, hi + 0.24 * rng)
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _p: mdates.num2date(x).strftime("%-I%p").lower()))
    ax.tick_params(axis="both", labelsize=10, colors=E_FG, length=3)
    ax.grid(axis="y", linestyle=":", alpha=0.4, color=E_DIM)
    for spine in ax.spines.values():
        spine.set_edgecolor(E_DIM)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_ylabel("ft MLLW", fontsize=10, color=E_FG)


def render_eink(payload: dict, orientation: str = "portrait",
                settings: dict | None = None, return_meta: bool = False):
    """Render to a PIL image (Spectra-6 friendly).  If return_meta, also returns a
    dict {id: {x, y, size|w/h, bbox:[l,t,r,b] in px}} for the editor."""
    w, h = resolution_for(orientation)
    layout = _resolve_layout(orientation, settings)
    fig = Figure(figsize=(w / DPI, h / DPI), dpi=DPI)
    fig.set_facecolor(E_BG)

    c = payload.get("conditions", {})

    def g(key):
        v = c.get(key, "N/A")
        return v if v not in ("", "…", None) else "N/A"

    artists = {}
    for eid, getter, color, weight in TEXT_ELEMENTS:
        txt = getter(payload, g)
        if not txt:
            continue
        x, y, size = layout[eid]
        col = color
        if eid == "tide_type":
            col = E_HIGH if "High" in txt else (E_LOW if "Low" in txt else E_FG)
        elif eid == "temp":
            col = _temp_color(g("air_temp"))
        artists[eid] = fig.text(x, 1.0 - y, txt, fontsize=size, color=col or E_FG,
                                fontweight=weight, ha="left", va="top",
                                family="DejaVu Sans")

    # Graph in its own axes rectangle (matplotlib rect uses bottom-left origin).
    gx, gy, gw, gh = layout["graph"]
    ax = fig.add_axes([gx, 1.0 - gy - gh, gw, gh])
    graph = payload.get("graph")
    if graph and (graph.get("obs", ([],))[0] or graph.get("pred", ([],))[0]):
        _draw_graph(ax, graph)
    else:
        ax.axis("off")
        ax.text(0.5, 0.5, "No tide graph data", fontsize=11, color=E_DIM,
                ha="center", va="center")

    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    img = _fig_to_image(canvas)

    if not return_meta:
        return img

    r = canvas.get_renderer()
    meta = {}
    for eid, art in artists.items():
        bb = art.get_window_extent(r)
        x, y, size = layout[eid]
        meta[eid] = {"x": x, "y": y, "size": size,
                     "bbox": [bb.x0, h - bb.y1, bb.x1, h - bb.y0]}
    meta["graph"] = {"x": gx, "y": gy, "w": gw, "h": gh,
                     "bbox": [gx * w, gy * h, (gx + gw) * w, (gy + gh) * h]}
    return img, meta


if __name__ == "__main__":
    demo = {
        "station": "Cape May, NJ", "timestamp": "Jul 12  3:45 PM",
        "conditions": {"air_temp": "78.4", "wind_speed": "12.3", "wind_gust": "18.0",
                       "wind_dir": "SW (225°)", "water_level": "+1.23", "water_temp": "71.2"},
        "tide": {"type": "High Tide", "time": "Sat Jul 12  4:10 PM", "height": "5.12"},
        "graph": None, "sport": "Windsurf",
    }
    for orient in ("portrait", "landscape"):
        img, meta = render_eink(demo, orient, return_meta=True)
        img.save(f"/tmp/inky_preview_{orient}.png")
        print(orient, img.size, "elements:", len(meta))
