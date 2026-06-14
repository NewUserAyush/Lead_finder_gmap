#!/usr/bin/env bash
set -e

# Install the Chromium binary into a folder under this script's directory so it
# persists into the runtime container. find_lead_map.py resolves the same path.
export PLAYWRIGHT_BROWSERS_PATH="$(cd "$(dirname "$0")" && pwd)/.playwright-browsers"
pip3 install -r requirements.txt
playwright install chromium
