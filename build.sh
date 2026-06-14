#!/usr/bin/env bash
set -e

export PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/src/.playwright-browsers
pip3 install -r requirements.txt
playwright install chromium
