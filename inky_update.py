#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Headless Inky updater for the Cape May Weather dashboard.

Runs with NO display/X server — fetch NOAA data → render → push to the Inky
Impression over SPI.  This is what keeps the panel updating when the Pi has no
HDMI monitor attached.  The GUI (cape_may_weather.py) is only needed for config.

Usage:
    inky_update.py --once      # single update, then exit  (good for cron)
    inky_update.py --loop      # update forever, sleeping inky_refresh_min between
    inky_update.py --dry-run   # render to /tmp PNG only, do NOT touch the panel

Config is read from cape_may_weather.json (same folder) each cycle, so changing
settings in the GUI takes effect on the next refresh.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import noaa_data
import inky_render

CONFIG_FILE = Path(__file__).with_name("cape_may_weather.json")

_DEFAULTS = {
    "inky_orientation": "portrait",
    "inky_saturation":  60,
    "inky_refresh_min": 30,
    "inky_flip":        0,
    # per-element layout overrides from the editor — MUST be loaded so the
    # headless panel matches what you arranged in the GUI
    "inky_layout":    None,
    # sport thresholds (mirrors the app; used for the "Good for" line)
    "paddle_min":     0, "paddle_max":      5,
    "hobie_min":      5, "hobie_max":      10,
    "wingfoiler_min": 11, "wingfoiler_max": 18,
    "windsurfer_min": 16, "windsurfer_max": 27,
    # activity icon paths (relative paths resolve next to inky_render.py)
    "paddle_icon": "", "hobie_icon": "",
    "windsurfer_icon": "", "wingfoiler_icon": "",
    # sunset graphic (blank → bundled sunset_icon.png)
    "sunset_icon": "",
    # decorative seagull (top layer): blank icon → bundled seagull_icon.png;
    # seagull_odds is the % chance it shows on each reload
    "seagull_icon": "", "seagull_odds": 30,
}


def load_config() -> dict:
    cfg = dict(_DEFAULTS)
    try:
        raw = json.loads(CONFIG_FILE.read_text())
        for k in _DEFAULTS:
            if k in raw:
                cfg[k] = raw[k]
    except Exception:
        pass  # fall back to defaults if config missing/unreadable
    return cfg


def prepare_for_panel(img, resolution, flip: bool):
    """Fit a rendered image to the panel's native (landscape) buffer."""
    res = tuple(resolution)
    out = img
    if out.size != res:                       # portrait render → rotate to fit
        out = out.rotate(90, expand=True)
    if flip:                                   # for an upside-down mount
        out = out.rotate(180)
    if out.size != res:                        # final safety
        out = out.resize(res)
    return out


def send_to_inky(img, saturation: float = 0.6, flip: bool = False) -> tuple:
    """Push a PIL image to the panel. Returns (ok, message). Imports inky lazily
    so the GUI still loads on machines without the driver."""
    try:
        from inky.auto import auto
    except Exception as e:
        return False, f"inky driver not available: {e}"
    try:
        panel = auto(ask_user=False, verbose=False)
        panel.set_image(prepare_for_panel(img, panel.resolution, flip),
                        saturation=saturation)
        panel.show()
        return True, "sent"
    except Exception as e:
        return False, f"panel error: {e}"


def update_once(cfg: dict, dry_run: bool = False) -> bool:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] fetching NOAA data…", flush=True)
    payload = noaa_data.fetch_payload(cfg)
    orient = cfg.get("inky_orientation", "portrait")
    # Roll the seagull once per reload from the configured odds (0-100%).
    odds = max(0, min(100, int(cfg.get("seagull_odds", 30))))
    payload["show_seagull"] = random.random() < (odds / 100.0)
    print(f"[{stamp}] seagull: {'shown' if payload['show_seagull'] else 'hidden'} "
          f"(odds {odds}%)", flush=True)
    img = inky_render.render_eink(payload, orient, settings=cfg)
    print(f"[{stamp}] rendered {orient} {img.size}  "
          f"air={payload['conditions'].get('air_temp')}  "
          f"tide={payload['tide'].get('type')}", flush=True)

    if dry_run:
        out = f"/tmp/inky_update_{orient}.png"
        img.save(out)
        print(f"[{stamp}] --dry-run: wrote {out} (panel not touched)", flush=True)
        return True

    ok, msg = send_to_inky(img, cfg.get("inky_saturation", 60) / 100.0,
                           bool(cfg.get("inky_flip", 0)))
    print(f"[{stamp}] push: {'OK' if ok else 'FAILED'} — {msg}", flush=True)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Headless Inky updater")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--once", action="store_true", help="update once and exit")
    g.add_argument("--loop", action="store_true", help="update forever on a timer")
    ap.add_argument("--dry-run", action="store_true",
                    help="render to /tmp PNG, do not push to the panel")
    args = ap.parse_args()

    if args.loop:
        while True:
            cfg = load_config()
            try:
                update_once(cfg, dry_run=args.dry_run)
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] update error: {e}", flush=True)
            mins = max(1, int(cfg.get("inky_refresh_min", 30)))
            print(f"sleeping {mins} min until next refresh…", flush=True)
            time.sleep(mins * 60)
    else:
        # default is a single update
        ok = update_once(load_config(), dry_run=args.dry_run)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
