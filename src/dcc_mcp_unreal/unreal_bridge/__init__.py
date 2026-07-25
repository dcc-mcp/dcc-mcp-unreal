"""unreal_bridge — Host-native bridge modules for DCC-MCP Unreal skills.

Each submodule implements the P0 reflection contract for a domain (blueprint,
actors, assets, etc.) and returns standard result envelopes consumable by
the dcc-mcp skill tool layer.  Bridge functions call Unreal Engine's Python
API (``import unreal``) directly inside the engine process; they are NOT
intended for out-of-process use.

Modules:
    blueprint  — 22 bridge functions for Blueprint graph authoring:
                  graph lifecycle, node CRUD, pin wiring, layout, compile,
                  and diagnostics.
"""
from __future__ import annotations

__all__ = ["blueprint"]
