#!/usr/bin/env bash
# dcc-mcp-unreal — Linux/macOS uninstaller

set -euo pipefail

PROJECT_ROOT="$(pwd)"
ENGINE_ROOT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --engine)  ENGINE_ROOT="$2"; shift 2 ;;
        --project) PROJECT_ROOT="$2"; shift 2 ;;
        *)         shift ;;
    esac
done

if [[ -n "$ENGINE_ROOT" ]]; then
    DEST="$ENGINE_ROOT/Engine/Plugins/DccMcpUnreal"
else
    DEST="$PROJECT_ROOT/Plugins/DccMcpUnreal"
fi

if [[ ! -d "$DEST" ]]; then
    echo "[dcc-mcp-unreal] Plugin not found at $DEST"
    exit 0
fi

echo "Removing $DEST ..."
rm -rf "$DEST"
echo "[dcc-mcp-unreal] Uninstalled successfully."
