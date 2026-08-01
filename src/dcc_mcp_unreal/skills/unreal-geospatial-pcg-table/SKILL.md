---
name: unreal-geospatial-pcg-table
description: >-
  Domain skill - import attributed GeoJSON city data into Unreal Engine PCG
  Data Tables with georeferenced roads, pedestrian ways, buildings, railways, water, and
  land-use points for UE 5.8's native Load Data Table node. Use after a geospatial provider such as
  openstreetmap-city-data. Not for downloading source data.
license: MIT
compatibility: Unreal Engine 5.8+, Python 3.9+
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: scene
    search-hint: "unreal geojson openstreetmap OSM city roads pedestrian footway buildings railway water landuse PCG data asset Cesium georeference import"
    tags: "unreal, geospatial, geojson, openstreetmap, pcg, cesium, city"
    tools: tools.yaml
---

# Unreal Geospatial PCG

Consumes an existing attributed GeoJSON file and creates a native `DataTable`
whose row type is UE 5.8's built-in `PCGPoint`. Import one semantic layer per
table, then load it with the native PCG `Load Data Table` node.

Import `pedestrian` separately from `roads`; flat `steps` features are skipped
because they need elevation-aware geometry rather than a scaled plane mesh.

Prefer a live `CesiumGeoreference` actor so imported points align with Cesium
tiles. When Cesium is unavailable, provide an explicit longitude/latitude
origin for the local East-South-Up fallback projection.

The source provider owns downloading and licensing. Preserve its attribution in
the `attribution` argument and in any showcase or publish manifest.
