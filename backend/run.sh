#!/usr/bin/env bash

# If invoked via `sh run.sh`, re-exec with bash so bash-specific syntax works.
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

cd "$(dirname "$0")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if .env exists, if not create from template
if [[ ! -f ".env" ]]; then
  if [[ -f ".env.example" ]]; then
    echo -e "${YELLOW}Creating .env from .env.example${NC}"
    cp .env.example .env
    echo -e "${GREEN}✓ Created .env${NC}"
    echo -e "${YELLOW}⚠️  Please update .env with your configuration before running the app${NC}"
  else
    echo -e "${RED}Error: .env.example not found${NC}"
    exit 1
  fi
fi

# Check if conda is available
if ! command -v conda >/dev/null 2>&1; then
  echo -e "${RED}Error: conda not found in PATH${NC}"
  echo "Please activate your conda setup first, then run this script again."
  exit 1
fi

# Configuration from environment or defaults
CONDA_ENV_NAME="${MEETSUM_CONDA_ENV:-meetSum}"
API_HOST="${MEETSUM_API_HOST:-127.0.0.1}"
API_PORT="${MEETSUM_API_PORT:-8001}"
RELOAD="${RELOAD:-true}"

# Check if conda environment exists
if ! conda env list | grep -q "^$CONDA_ENV_NAME "; then
  echo -e "${RED}Error: Conda environment '$CONDA_ENV_NAME' not found${NC}"
  echo "Create it with: conda create -n $CONDA_ENV_NAME python=3.11"
  exit 1
fi

# Display startup information
echo -e "${GREEN}═══════════════════════════════════════${NC}"
echo -e "${GREEN}  Open Meet Sum - Backend Server${NC}"
echo -e "${GREEN}═══════════════════════════════════════${NC}"
echo "Environment: $CONDA_ENV_NAME"
echo "Host: $API_HOST"
echo "Port: $API_PORT"
if [[ "$RELOAD" == "true" ]]; then
  echo "Mode: Development (auto-reload enabled)"
else
  echo "Mode: Production"
fi
echo -e "${GREEN}═══════════════════════════════════════${NC}"
echo ""

# Build uvicorn command as an array to avoid shell parsing issues.
UVICORN_CMD=(uvicorn app:app --host "$API_HOST" --port "$API_PORT")

if [[ "$RELOAD" == "true" ]]; then
  UVICORN_CMD+=(--reload)
fi

# If the target conda env is already active, run directly.
if [[ "${CONDA_DEFAULT_ENV:-}" == "$CONDA_ENV_NAME" ]]; then
  exec "${UVICORN_CMD[@]}"
fi

# Otherwise launch through conda run and stream output in real time.
exec conda run --no-capture-output -n "$CONDA_ENV_NAME" "${UVICORN_CMD[@]}"
