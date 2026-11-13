#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
command -v uv >/dev/null 2>&1 || { echo 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' >&2; exit 1; }
cd "$repo"
uv sync --extra analysis
printf '%s\n' 'Install Obscura manually for your platform, then set INSTAGRAM_OBSCURA_BINARY.'
printf '%s\n' 'Optional multilingual model: uv run instagram-mcp-setup --model (requires aria2c)'
printf '%s\n' 'Run: uv run instagram-mcp-doctor'
