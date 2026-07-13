#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-contained sunset (and sunrise) calculator for Cape May, NJ.

No external dependencies (astral/ephem are not installed in the pimoroni venv),
so this implements the standard NOAA "sunrise equation" directly and converts
the result to the machine's local time.  Used to add today's sunset to the Inky
payload.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

# Cape May, NJ — latitude north (+), longitude east (−, i.e. it is west).
CAPE_MAY_LAT = 38.9351
CAPE_MAY_LON = -74.9060

_RAD = math.pi / 180.0
# 2000-01-01 as a day count reference (date.toordinal() of that day).
_EPOCH_ORDINAL = date(2000, 1, 1).toordinal()


def _solar_event(d: date, lat: float, lon: float, event: str):
    """UTC datetime of 'sunrise' or 'sunset' for date d at lat/lon.

    Returns None on polar day/night (sun never crosses the horizon)."""
    # Days since 2000-01-01 (mean-solar-noon day count, Wikipedia "Sunrise equation").
    n = (d.toordinal() - _EPOCH_ORDINAL) + 0.0008
    j_star = n - lon / 360.0                       # mean solar noon (lon east)
    m = (357.5291 + 0.98560028 * j_star) % 360.0   # solar mean anomaly
    c = (1.9148 * math.sin(m * _RAD)               # equation of the centre
         + 0.0200 * math.sin(2 * m * _RAD)
         + 0.0003 * math.sin(3 * m * _RAD))
    lam = (m + c + 180.0 + 102.9372) % 360.0       # ecliptic longitude
    j_transit = (2451545.0 + j_star
                 + 0.0053 * math.sin(m * _RAD)
                 - 0.0069 * math.sin(2 * lam * _RAD))
    sin_dec = math.sin(lam * _RAD) * math.sin(23.44 * _RAD)
    cos_dec = math.cos(math.asin(sin_dec))
    cos_omega = ((math.sin(-0.833 * _RAD) - math.sin(lat * _RAD) * sin_dec)
                 / (math.cos(lat * _RAD) * cos_dec))
    if not -1.0 <= cos_omega <= 1.0:
        return None                                # no sunrise/sunset that day
    omega = math.acos(cos_omega) / _RAD
    j_event = j_transit + (omega / 360.0 if event == "sunset" else -omega / 360.0)
    unix = (j_event - 2440587.5) * 86400.0         # Julian date → Unix seconds
    return datetime.fromtimestamp(unix, tz=timezone.utc)


def sunset_datetime(day: date | None = None,
                    lat: float = CAPE_MAY_LAT, lon: float = CAPE_MAY_LON):
    """Local (machine-timezone) datetime of sunset, or None."""
    utc = _solar_event(day or datetime.now().date(), lat, lon, "sunset")
    return utc.astimezone() if utc else None


def sunrise_datetime(day: date | None = None,
                     lat: float = CAPE_MAY_LAT, lon: float = CAPE_MAY_LON):
    """Local (machine-timezone) datetime of sunrise, or None."""
    utc = _solar_event(day or datetime.now().date(), lat, lon, "sunrise")
    return utc.astimezone() if utc else None


def sunset_string(day: date | None = None) -> str:
    """Today's sunset as e.g. '8:24 PM', or '' if it can't be computed."""
    try:
        dt = sunset_datetime(day)
        return dt.strftime("%-I:%M %p") if dt else ""
    except Exception:
        return ""


def current_sun_event(now: datetime | None = None):
    """The sun event to display right now, as (kind, datetime):
      - during daylight  → ('sunset',  today's sunset)
      - once the sun has set (or before dawn) → ('sunrise', the next sunrise).
    Returns (kind, None) if the time can't be computed."""
    now = now or datetime.now()
    if now.tzinfo is None:                  # treat naive input as local wall-clock
        now = now.astimezone()
    today = now.date()
    sr = sunrise_datetime(today)
    ss = sunset_datetime(today)
    if sr and now < sr:                     # pre-dawn: still dark → next sunrise (today)
        return ("sunrise", sr)
    if ss and now < ss:                     # daytime → today's sunset
        return ("sunset", ss)
    return ("sunrise", sunrise_datetime(today + timedelta(days=1)))  # after sunset → next sunrise


def current_sun_string(now: datetime | None = None) -> str:
    """Time to show in the sun graphic — today's sunset while the sun is up,
    otherwise the next sunrise. '' if it can't be computed."""
    try:
        _kind, dt = current_sun_event(now)
        return dt.strftime("%-I:%M %p") if dt else ""
    except Exception:
        return ""


if __name__ == "__main__":
    print("sunset:  ", sunset_string())
    print("sunrise: ", sunrise_datetime().strftime("%-I:%M %p") if sunrise_datetime() else "")
    print("current: ", current_sun_event(), "->", current_sun_string())
