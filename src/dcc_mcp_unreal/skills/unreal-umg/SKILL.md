---
name: unreal-umg
description: >-
  Domain skill — UMG Widget Blueprint authoring for Unreal Engine 5.4+: create
  widget blueprints, manage widget hierarchies, configure slot layouts, bind
  events, and author UMG animations. Complements unreal-blueprints (general BP
  editing) with UMG-specialized widget, slot, animation, and event-binding
  operations. Not for general Blueprint node editing — use unreal-blueprints
  for that.
license: MIT
compatibility: "Unreal Engine 5.4+; Python 3.9+; dcc-mcp-core 0.17+"
allowed-tools: Bash Read Write Edit
metadata:
  dcc-mcp:
    dcc: unreal
    version: "1.0.0"
    layer: domain
    stage: authoring
    compatibility:
      unreal_min: "5.4"
    search-hint: "UMG widget blueprint, user widget, canvas panel, widget hierarchy, widget animation, event binding, widget properties, anchors, slot layout, UMG keyframe, compile widget"
    tags: "unreal, umg, widget, ui, animation, domain"
    tools: tools.yaml
---

# Unreal UMG Tools

Widget Blueprint authoring tools for Unreal Motion Graphics (UMG) in Unreal Engine 5.4+.

## Tools

### `unreal_umg__create_widget_blueprint`
Create a new UMG Widget Blueprint inheriting from UserWidget. The asset is placed under `/Game/` namespace.

### `unreal_umg__add_widget_to_canvas`
Add a child widget (Button, TextBlock, Image, etc.) to a CanvasPanel or other panel widget.

### `unreal_umg__set_widget_properties`
Set widget display properties: size, anchors, visibility, tooltip, and style.

### `unreal_umg__bind_widget_event`
Bind a widget interaction event (OnClicked, OnHovered, etc.) to a Blueprint-implemented function.

### `unreal_umg__create_umg_animation`
Create a UMG WidgetAnimation track on a widget.

### `unreal_umg__add_animation_keyframe`
Add a keyframe to an existing UMG animation track for position, opacity, color, scale, rotation, visibility, or shear.

### `unreal_umg__compile_widget_blueprint`
Compile a Widget Blueprint asset and return any compilation errors.

### `unreal_umg__list_widget_hierarchy`
Read the full widget tree hierarchy starting from a root widget.

## Prerequisites

- Unreal Engine 5.4 or later with Python scripting plugin enabled
- `unreal` Python module available inside Unreal Editor
- dcc-mcp-unreal adapter running with this skill on its search path

## Widget Type Whitelist

Only these widget types are accepted for creation:

Button, TextBlock, Image, CanvasPanel, VerticalBox, HorizontalBox, Overlay, Border, SizeBox, EditableText, ProgressBar, Slider

## Event Type Whitelist

OnClicked, OnPressed, OnReleased, OnHovered, OnUnhovered, OnDragDetected, OnDragCancelled

## Persistence

Every mutating tool saves the Widget Blueprint through
`EditorAssetLibrary.save_loaded_asset` and fails when Unreal refuses the save,
so a reported success always means the change reached disk.

## Asset Path Constraints

All asset paths are restricted to the `/Game/` content namespace. Absolute filesystem paths are rejected.
