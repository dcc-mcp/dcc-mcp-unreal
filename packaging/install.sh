#!/usr/bin/env bash
# ============================================================
#  dcc-mcp-unreal — Linux/macOS installer
#
#  Installs the plugin into the current Unreal Engine project
#  or as an Engine plugin (if --engine is passed).
#
#  Usage:
#    ./install.sh                          (install into project in CWD)
#    ./install.sh --engine /opt/UE_5.4    (install into engine)
#    ./install.sh --project /path/to/game (specify project root)
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$SCRIPT_DIR/../unreal/plugin"
INSTALL_MODE="project"
ENGINE_ROOT=""
PROJECT_ROOT="$(pwd)"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --engine)
            INSTALL_MODE="engine"
            ENGINE_ROOT="$2"
            shift 2
            ;;
        --project)
            PROJECT_ROOT="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# Read version from .uplugin
UPLUGIN="$(find "$PLUGIN_DIR" -maxdepth 1 -name '*.uplugin' | head -n 1)"
VERSION=$(python3 -c "import json; d=json.load(open('$UPLUGIN')); print(d.get('VersionName','0.1.0'))" 2>/dev/null || echo "0.1.0")
echo "[dcc-mcp-unreal] Installing version $VERSION"

# Determine destination
if [[ "$INSTALL_MODE" == "engine" ]]; then
    if [[ -z "$ENGINE_ROOT" ]]; then
        echo "ERROR: --engine requires a path, e.g. --engine /opt/UE_5.4"
        exit 1
    fi
    DEST="$ENGINE_ROOT/Engine/Plugins/DccMcpUnreal"
    echo "Installing as Engine plugin to: $DEST"
else
    # Check for .uproject
    if ! ls "$PROJECT_ROOT"/*.uproject &>/dev/null; then
        echo "WARNING: No .uproject found in $PROJECT_ROOT"
        echo "         Specify the project root with --project /path/to/game"
    fi
    DEST="$PROJECT_ROOT/Plugins/DccMcpUnreal"
    echo "Installing as Project plugin to: $DEST"
fi

# Remove previous installation and copy plugin files
if [[ -d "$DEST" ]]; then
    echo "Removing existing installation at $DEST"
    rm -rf "$DEST"
fi
mkdir -p "$DEST"
cp -R "$PLUGIN_DIR/." "$DEST/"
echo "Plugin files copied."

# Install Python package into plugin's python/ directory
echo "Installing dcc-mcp-unreal Python package..."
if python3 -m pip install dcc-mcp-unreal --target "$DEST/python" --quiet; then
    echo "Python package installed."
else
    echo "WARNING: pip install failed. Install manually:"
    echo "  pip install dcc-mcp-unreal --target '$DEST/python'"
fi

# Run post-install verification
echo ""
echo "Running post-install verification..."
python3 "$SCRIPT_DIR/post_install.py" --plugin-root "$DEST" || {
    echo "WARNING: Post-install verification reported issues."
}

echo ""
echo "============================================================"
echo " Installation complete!"
echo ""
echo " To enable in Unreal Engine:"
echo " 1. Open your project in Unreal Editor"
echo " 2. Edit > Plugins > search 'DCC MCP Unreal'"
echo " 3. Enable the plugin and restart the editor"
echo " 4. The MCP server starts automatically at port 8765"
echo ""
echo " To configure port:   export DCC_MCP_UNREAL_PORT=9000"
echo " To configure name:   export DCC_MCP_UNREAL_SERVER_NAME=my-unreal"
echo "============================================================"
