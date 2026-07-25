"""Check available BlueprintEditorLibrary APIs in UE 5.3."""
import json
from pathlib import Path

import unreal

results = {}

# Check for critical APIs
bel = unreal.BlueprintEditorLibrary

apis_to_check = [
    "get_blueprint_event_graphs",
    "refresh_open_blueprint_nodes",
    "get_compilation_messages",
    "compile_blueprint",
    "remove_graph_node",
    "add_function_graph",
    "create_matching_function",
    "find_event_graph",
    "get_blueprint_editor",
    "repair_blueprint",
    "find_graph",
    "remove_graph",
    "rename_graph",
]

for api in apis_to_check:
    if hasattr(bel, api):
        results[api] = "AVAILABLE"
    else:
        results[api] = "MISSING"

# Also check what's available
all_attrs = [a for a in dir(bel) if not a.startswith("_")]
results["all_available"] = all_attrs

# Check alternative APIs
results["unreal_EditorAssetLibrary_available"] = hasattr(unreal, "EditorAssetLibrary")

# Check for Graph-related APIs
for cls_name in ["EdGraph", "EdGraphNode", "EdGraphPin", "K2Node", "BlueprintEditorLibrary"]:
    if hasattr(unreal, cls_name):
        results[f"class_{cls_name}"] = "AVAILABLE"
    else:
        results[f"class_{cls_name}"] = "MISSING"

output_path = Path(__file__).with_suffix(".result.json")
output_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
print(f"Results written to: {output_path}")
