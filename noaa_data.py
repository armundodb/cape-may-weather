#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared NOAA Tides & Currents fetcher for Cape May.

Used by the headless Inky updater (inky_update.py).  Returns a payload dict
in exactly the shape inky_render.render_eink() expects, mirroring the data the
Tk dashboard fetches so the panel matches the on-screen view.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import requests

import sunset as _sunset

STATION_ID   = "8536110"
STATION_NAME = "Cape May, NJ"
BASE_URL     = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
WINDOW_HOURS = 12


def _api(**params) -> dict:
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


def _fetch_graph(now: datetime) -> dict:
    w_start = now - timedelta(hours=WINDOW_HOURS)
    w_end   = now + timedelta(hours=WINDOW_HOURS)
    obs_t, obs_v, pred_t, pred_v = [], [], [], []
    hilo_t, hilo_v, hilo_k = [], [], []

    try:
        for pt in _api(product="water_level",
                       begin_date=w_start.strftime("%Y%m%d %H:%M"),
                       end_date=now.strftime("%Y%m%d %H:%M"),
                       datum="MLLW").get("data", []):
            try:
                obs_t.append(datetime.strptime(pt["t"], "%Y-%m-%d %H:%M"))
                obs_v.append(float(pt["v"]))
            except (ValueError, KeyError):
                pass
    except Exception:
        pass

    try:
        for pt in _api(product="predictions",
                       begin_date=now.strftime("%Y%m%d %H:%M"),
                       end_date=w_end.strftime("%Y%m%d %H:%M"),
                       interval="6", datum="MLLW").get("predictions", []):
            try:
                pred_t.append(datetime.strptime(pt["t"], "%Y-%m-%d %H:%M"))
                pred_v.append(float(pt["v"]))
            except (ValueError, KeyError):
                pass
    except Exception:
        pass

    try:
        for pt in _api(product="predictions",
                       begin_date=w_start.strftime("%Y%m%d"),
                       end_date=(w_end + timedelta(days=1)).strftime("%Y%m%d"),
                       interval="hilo", datum="MLLW").get("predictions", []):
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


def fetch_payload(settings: dict | None = None) -> dict:
    """Fetch everything and return a render_eink() payload dict.

    settings (optional) supplies the wind-sport speed thresholds so the
    'Good for' recommendation matches the GUI.
    """
    settings = settings or {}
    now = datetime.now()
    cond: dict = {}
    wind_speed_val = None

    try:
        d = _api(product="air_temperature", date="latest")
        cond["air_temp"] = f"{float(d['data'][0]['v']):.1f}"
    except Exception:
        cond["air_temp"] = "N/A"

    try:
        w = _api(product="wind", date="latest")["data"][0]
        wind_speed_val = float(w["s"])
        cond["wind_speed"] = f"{wind_speed_val:.1f}"
        cond["wind_gust"]  = f"{float(w['g']):.1f}"
        cond["wind_dir"]   = f"{w.get('dr', '?')} ({w.get('d', '?')}°)"
    except Exception:
        cond["wind_speed"] = cond["wind_gust"] = cond["wind_dir"] = "N/A"

    try:
        d = _api(product="water_level", date="latest", datum="MLLW")
        cond["water_level"] = f"{float(d['data'][0]['v']):+.2f}"
    except Exception:
        cond["water_level"] = "N/A"

    try:
        d = _api(product="water_temperature", date="latest")
        cond["water_temp"] = f"{float(d['data'][0]['v']):.1f}"
    except Exception:
        cond["water_temp"] = "N/A"

    tide = {"type": "N/A", "time": "N/A", "height": "N/A"}
    try:
        d = _api(product="predictions", begin_date=now.strftime("%Y%m%d"),
                 end_date=(now + timedelta(days=2)).strftime("%Y%m%d"),
                 interval="hilo", datum="MLLW")
        nxt = next((p for p in d.get("predictions", [])
                    if datetime.strptime(p["t"], "%Y-%m-%d %H:%M") > now), None)
        if nxt:
            t = datetime.strptime(nxt["t"], "%Y-%m-%d %H:%M")
            tide = {
                "type":   "High Tide" if nxt["type"] == "H" else "Low Tide",
                "time":   t.strftime("%a %b %d  %I:%M %p"),
                "height": f"{float(nxt['v']):.2f}",
            }
    except Exception:
        pass

    # Wind-sport recommendation (same thresholds/keys as the GUI settings)
    sports = []
    if wind_speed_val is not None:
        if settings.get("windsurfer_min", 16) <= wind_speed_val <= settings.get("windsurfer_max", 27):
            sports.append("Windsurf")
        if settings.get("wingfoiler_min", 11) <= wind_speed_val <= settings.get("wingfoiler_max", 18):
            sports.append("Wingfoil")

    return {
        "station":   STATION_NAME,
        "timestamp": now.strftime("%b %d  %-I:%M %p"),
        "conditions": cond,
        "tide": tide,
        "graph": _fetch_graph(now),
        "sport": " + ".join(sports) if sports else None,
        "sunset": _sunset.current_sun_string(now),
    }


if __name__ == "__main__":
    import json
    p = fetch_payload()
    slim = {k: v for k, v in p.items() if k != "graph"}
    slim["graph_points"] = {
        "obs": len(p["graph"]["obs"][0]),
        "pred": len(p["graph"]["pred"][0]),
        "hilo": len(p["graph"]["hilo"][0]),
    }
    print(json.dumps(slim, indent=2, default=str))
