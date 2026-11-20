#!/usr/bin/env bash
# Fetches MCP Toolbox if needed, then serves the BigQuery tools it defines.
#
# The agent talks to this over HTTP at $TOOLBOX_URL/mcp — run this in one
# terminal and the agent (agents-cli playground, or fast_api_app.py) in
# another.
set -euo pipefail
cd "$(dirname "$0")/.."

TOOLBOX_VERSION="1.12.0"
BIN="mcp-toolbox/bin/toolbox"

if [[ ! -x "$BIN" ]]; then
  case "$(uname -s)/$(uname -m)" in
    Linux/x86_64) PLATFORM="linux/amd64" ;;
    Darwin/arm64) PLATFORM="darwin/arm64" ;;
    Darwin/x86_64) PLATFORM="darwin/amd64" ;;
    *)
      echo "No prebuilt MCP Toolbox binary for $(uname -s)/$(uname -m)." >&2
      echo "Run it from a container instead: see mcp-toolbox.dev/how-to/build/." >&2
      exit 1
      ;;
  esac
  echo "Fetching MCP Toolbox v${TOOLBOX_VERSION} (${PLATFORM})..."
  mkdir -p mcp-toolbox/bin
  curl -sSL -o "$BIN" \
    "https://storage.googleapis.com/mcp-toolbox-for-databases/v${TOOLBOX_VERSION}/${PLATFORM}/toolbox"
  chmod +x "$BIN"
fi

set -a
[[ -f .env ]] && source .env
set +a

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT in .env}"
: "${BIGQUERY_LOCATION:=us-central1}"

exec "$BIN" --config mcp-toolbox/tools.yaml --port 5000
