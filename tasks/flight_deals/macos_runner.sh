#!/usr/bin/env bash
# Generic local runner for unattended daily execution on macOS (launchd / cron / Antigravity /schedule)
# or Linux, using an isolated WB_HOME so the host's $HOME is never polluted.
# Contains zero hardcoded personal paths or credentials.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export WB_HOME="${WB_HOME:-${HOME}/.local/share/gemini-workbench-local}"
PYTHON_BIN="${WB_PYTHON:-${WB_HOME}/.local/share/wb-venv/bin/python}"

mkdir -p "${WB_HOME}/runs" "${WB_HOME}/reports"

if [ ! -x "${PYTHON_BIN}" ]; then
  echo "[macos_runner] Initializing isolated local workbench venv at ${WB_HOME}..."
  if command -v uv >/dev/null 2>&1; then
    uv venv "${WB_HOME}/.local/share/wb-venv"
    uv pip install --python "${PYTHON_BIN}" \
      duckdb polars pyarrow pydantic httpx selectolax beautifulsoup4 playwright tenacity
    "${WB_HOME}/.local/share/wb-venv/bin/playwright" install chromium
  else
    echo "[macos_runner] Error: uv not found and WB_PYTHON not set." >&2
    exit 1
  fi
fi

TS="$(TZ=Asia/Tokyo date +%Y%m%d-%H%M%S)"
RUN_DIR="${WB_HOME}/runs/${TS}-flight-deals"
REPORT_FILE="${WB_HOME}/reports/${TS}-flight-deals.md"
LATEST_LINK="${WB_HOME}/reports/latest.md"
mkdir -p "${RUN_DIR}/out"

"${PYTHON_BIN}" "${REPO_DIR}/tasks/flight_deals/run.py" \
  --run-dir "${RUN_DIR}" \
  --out "${REPORT_FILE}" \
  --save-parquet

ln -sf "${REPORT_FILE}" "${LATEST_LINK}"
echo "[macos_runner] Completed: ${REPORT_FILE}"
