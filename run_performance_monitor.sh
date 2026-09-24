#!/usr/bin/env bash
# Launch the Cortex Performance Monitor Streamlit page (standalone).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
exec streamlit run pages/4_Performance_Monitor.py --server.headless true
