#!/usr/bin/env bash
# Launch the Cape May Weather dashboard.
#
# Uses the "pimoroni" virtualenv, which has BOTH the app's dependencies
# (matplotlib, requests, numpy, pillow) and the Inky driver — so the
# "Sync Inky" button can push straight to the panel.
set -e
export DISPLAY="${DISPLAY:-:0}"
cd "$(dirname "$0")"
exec /home/armundo/.virtualenvs/pimoroni/bin/python cape_may_weather.py "$@"
