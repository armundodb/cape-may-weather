#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate the e-ink (Inky panel) line-art icons for paddleboarding and Hobie-cat
sailing: paddle_icon.png and hobie_icon.png.

The panel renderer (inky_render._prep_icon) turns any opaque pixels black, so
these are drawn as BLACK OUTLINES on a TRANSPARENT background — outline-only so
the result is clean line art rather than solid black blobs. Each icon keeps a
continuous vertical element (paddle shaft / mast) so _prep_icon's band-splitting
treats it as a single artwork.

Run once (from the repo, in the pimoroni venv) to (re)create the PNGs:
    python make_sport_icons.py
"""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.patches import Circle, Polygon

K = "#000000"   # everything renders black for e-ink
LW = 11.0       # bold stroke width in the 500px canvas (matches wind/wing icons)


def _new_ax():
    fig = Figure(figsize=(5, 5), dpi=100)
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 10); ax.set_ylim(0, 10)
    ax.set_aspect("equal"); ax.axis("off")
    ax.patch.set_alpha(0.0)
    return fig, ax


def _outline(ax, pts, lw=LW):
    xs = [p[0] for p in pts] + [pts[0][0]]
    ys = [p[1] for p in pts] + [pts[0][1]]
    ax.plot(xs, ys, color=K, lw=lw, solid_capstyle="round", solid_joinstyle="round")


def _waves(ax, base):
    import numpy as np
    wx = np.linspace(0.6, 9.4, 200)
    for dy in (0, 0.7):
        ax.plot(wx, base + dy + 0.22*np.sin((wx + dy*1.5)*2.3),
                color=K, lw=LW*0.7, solid_capstyle="round")


def paddleboard(ax):
    _waves(ax, 1.15)
    # SUP board — bold solid lens (like the windsurfer's filled board)
    ax.add_patch(Polygon([(1.2,2.0),(8.0,2.0),(8.8,2.3),(8.0,2.6),(1.2,2.6),(0.4,2.3)],
                          fc=K, ec=K))
    # paddle: bold shaft, T-grip, solid blade (continuous vertical element)
    ax.plot([6.3, 5.2], [8.9, 2.8], color=K, lw=LW, solid_capstyle="round")
    ax.plot([5.6, 7.0], [8.9, 8.55], color=K, lw=LW, solid_capstyle="round")
    ax.add_patch(Polygon([(4.85,2.85),(5.55,2.85),(5.4,1.65),(5.0,1.65)], fc=K, ec=K))
    # bold stick figure standing on the board (solid head, thick limbs)
    ax.add_patch(Circle((4.25, 7.6), 0.62, fc=K, ec=K))
    ax.plot([4.25, 4.25], [6.98, 4.2], color=K, lw=LW*1.25, solid_capstyle="round")
    ax.plot([4.25, 6.3], [6.15, 8.1], color=K, lw=LW*1.1, solid_capstyle="round")
    ax.plot([4.25, 5.7], [5.4, 3.85], color=K, lw=LW*1.1, solid_capstyle="round")
    ax.plot([4.25, 3.5], [4.2, 2.7], color=K, lw=LW*1.25, solid_capstyle="round")
    ax.plot([4.25, 5.0], [4.2, 2.7], color=K, lw=LW*1.25, solid_capstyle="round")


def hobiecat(ax):
    _waves(ax, 1.05)
    # twin hulls — near hull solid, far hull bold outline behind it → clear "cat"
    ax.add_patch(Polygon([(1.0,2.35),(7.7,2.35),(8.5,2.68),(7.7,3.0),(1.0,3.0),(0.3,2.68)],
                          fc=K, ec=K))
    _outline(ax, [(1.6,1.95),(8.2,1.95),(8.9,2.22),(8.2,2.5),(1.6,2.5),(0.9,2.22)], lw=LW*1.0)
    # mast (continuous vertical element) + boom
    ax.plot([4.7, 4.7], [3.0, 9.4], color=K, lw=LW*1.25, solid_capstyle="round")
    ax.plot([1.7, 4.7], [3.35, 3.35], color=K, lw=LW, solid_capstyle="round")
    # mainsail — bold triangle outline with battens (echoes the windsurf sail)
    _outline(ax, [(4.7,3.15),(4.7,9.3),(1.5,3.35)], lw=LW*1.15)
    for yb, xr in ((4.7, 3.35), (6.0, 2.75), (7.3, 2.15)):
        ax.plot([4.7, xr], [yb, yb], color=K, lw=LW*0.8, solid_capstyle="round")
    # jib (small foresail outline)
    _outline(ax, [(4.7,8.2),(4.7,3.95),(7.6,3.55)], lw=LW*1.1)


def _save(draw, path):
    fig, ax = _new_ax()
    draw(ax)
    FigureCanvasAgg(fig).draw()
    fig.savefig(path, transparent=True, dpi=100)
    print("wrote", path)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    _save(paddleboard, os.path.join(here, "paddle_icon.png"))
    _save(hobiecat,    os.path.join(here, "hobie_icon.png"))
