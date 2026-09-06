#!/bin/sh
set -eu

cd "$(dirname "$0")"

if [ -f .venv/bin/activate ]; then
  . .venv/bin/activate
fi

while true; do
  date
  python amazon_browser_pull.py || true
  sleep 7200
done
