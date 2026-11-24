#!/usr/bin/env bash
# Sandbox-verified setup for Gemini Web Persistent VM (/home/spark).
# - Does NOT modify ~/.bashrc, ~/.profile, or ~/.ssh.
# - Uses uv venv (since python3-venv/ensurepip is absent on the VM) and honors VM TLS proxy CA certs.
set -euo pipefail

BIN_DIR="${HOME}/.local/bin"
SHARE_DIR="${HOME}/.local/share"
CFG_DIR="${HOME}/.config/wb"
WB_DIR="${HOME}/wb"
WB_VENV="${SHARE_DIR}/wb-venv"

export PATH="${BIN_DIR}:${PATH}"
export PLAYWRIGHT_BROWSERS_PATH="${SHARE_DIR}/ms-playwright"
if [ -f /etc/ssl/certs/ca-certificates.crt ]; then
  export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
  export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
  export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
fi

mkdir -p \
  "${BIN_DIR}" \
  "${SHARE_DIR}" \
  "${PLAYWRIGHT_BROWSERS_PATH}" \
  "${CFG_DIR}" \
  "${HOME}/data/datasets" \
  "${HOME}/runs"

if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --user --break-system-packages uv 2>/dev/null \
    || python3 -m pip install --user uv
fi

if [ ! -x "${WB_VENV}/bin/python" ]; then
  uv venv "${WB_VENV}"
fi

uv pip install --python "${WB_VENV}/bin/python" \
  uv \
  duckdb \
  polars \
  pyarrow \
  pydantic \
  httpx \
  curl_cffi \
  trafilatura \
  selectolax \
  beautifulsoup4 \
  lxml \
  yt-dlp \
  playwright \
  matplotlib \
  seaborn \
  jinja2 \
  tenacity \
  zstandard

if [ -f "${WB_DIR}/config/config.example.toml" ] && [ ! -f "${CFG_DIR}/config.toml" ]; then
  cp "${WB_DIR}/config/config.example.toml" "${CFG_DIR}/config.toml"
fi

"${WB_VENV}/bin/playwright" install chromium
python3 "${WB_DIR}/bin/wb" status
