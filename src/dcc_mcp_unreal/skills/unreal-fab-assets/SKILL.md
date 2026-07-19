---
name: unreal-fab-assets
description: >-
  Acquire free Fab marketplace content through Unreal Engine's official Fab
  integration, then verify the imported Content Browser assets. Use when the
  user asks to find, download, add, or import Fab or Unreal Marketplace assets.
  Not for arbitrary file imports - use unreal-assets instead.
license: MIT
compatibility: Unreal Engine 5.3+, Python 3.9+
allowed-tools: Read Bash
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: interchange
    depends: ["app-ui", "unreal-assets"]
    search-hint: "unreal fab marketplace free asset download add to project license content browser"
    tags: [unreal, fab, marketplace, assets, pipeline]
    tools: tools.yaml
---

# Unreal Fab Assets

Use the official Fab window in Unreal Engine for acquisition. UE-format Fab
content must be added to a project through the Fab integration or Epic Games
Launcher; do not scrape listing downloads or reproduce Fab's authenticated
client.

## Workflow

1. Inventory the live Unreal instance and load `app-ui` plus `unreal-assets`.
2. Start with `app_ui__snapshot` scoped to the exact Unreal process ID or
   window handle. Open **Window > Fab** semantically when possible.
3. Search using the user's art direction. Filter to **Free**, Unreal Engine
   format, and a version compatible with the running engine.
4. Before acquisition, report the listing title, publisher, source URL,
   license, supported engine version, and expected destination. Do not accept
   a new EULA, acquire a listing, or add it to the project without task-scoped
   user approval.
5. Use the Fab integration's **Add to My Library** and **Add to Project** flow.
   Never enter credentials, solve a CAPTCHA, bypass region/account policy, or
   automate paid content. Stop on authentication or confirmation boundaries.
6. Take a fresh snapshot after every UI action. When the download finishes,
   verify the new package with `unreal_assets__list_assets` and
   `unreal_assets__get_asset_info`.
7. Record a compact manifest containing the listing metadata, license, source
   URL, acquisition time, Content Browser paths, and verification result.
8. Always finish with `app_ui__stop_computer_use`, including failure and user
   interruption paths.

Fab content may be incorporated into a packaged project under its listing
license. Do not redistribute downloaded source assets as a standalone bundle.

## Scripts

- `prepare_free_asset_acquisition`
