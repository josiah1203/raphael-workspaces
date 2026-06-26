from typing import Any, Dict, List

def map_wire_event_to_common_ops(event_type: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Maps a tool-specific wire event to a list of Calliope common operations.
    """
    ops = []
    
    # FormFlow (Fusion / SolidWorks)
    if event_type == "geometry.feature_created":
        ops.append({
            "type": "parameter.update",
            "name": f"feature.{payload.get('feature_name', payload.get('name', 'unknown'))}.status",
            "value": "created"
        })
    elif event_type == "geometry.feature_modified":
        # Example: map feature movement to component.move if it's a component
        if payload.get("is_component") or "transform" in payload:
            transform = payload.get("transform", {})
            ops.append({
                "type": "component.move",
                "id": payload.get("feature_id", payload.get("id")),
                "x": transform.get("x", 0),
                "y": transform.get("y", 0),
                "z": transform.get("z", 0),
                "rotation": transform.get("rotation", 0)
            })

    # BoardFlow (KiCad / Altium)
    elif event_type in ("electrical.footprint_added", "electrical.footprint_modified"):
        # Map footprint changes to component.move if location is available
        if "position" in payload:
            pos = payload.get("position", {})
            ops.append({
                "type": "component.move",
                "id": payload.get("footprint_ref", payload.get("component_id", "unknown")),
                "x": pos.get("x", 0),
                "y": pos.get("y", 0),
                "z": pos.get("z", 0),
                "rotation": payload.get("rotation", 0)
            })
        else:
            ops.append({
                "type": "parameter.update",
                "name": f"footprint.{payload.get('footprint_ref', payload.get('component_id', 'unknown'))}.status",
                "value": "modified" if event_type == "electrical.footprint_modified" else "added"
            })
    elif event_type == "electrical.net_changed":
        net_name = payload.get("net_name")
        change = payload.get("change")
        ops.append({
            "type": "parameter.update",
            "name": f"net.{net_name}.status",
            "value": change
        })
    elif event_type == "pcb.net_renamed":
        ops.append({
            "type": "net.rename",
            "old_name": payload.get("old_name"),
            "new_name": payload.get("new_name")
        })
    elif event_type == "pcb.via_added":
        ops.append({
            "type": "via.create",
            "at": payload.get("position", [0, 0]),
            "layers": payload.get("layers", []),
            "drill_size": payload.get("drill_size", 0.3)
        })
        
    # Metadata (GitHub / Jira)
    elif event_type == "vcs.push":
        ops.append({
            "type": "parameter.update",
            "name": "vcs.last_push_ref",
            "value": payload.get("ref")
        })
    elif event_type == "issue.updated":
        ops.append({
            "type": "parameter.update",
            "name": f"issue.{payload.get('id')}.status",
            "value": payload.get("status")
        })
    elif event_type == "simulation.setup_captured":
        ops.append({
            "type": "parameter.update",
            "name": f"simulation.{payload.get('document_id', 'unknown')}.setup_status",
            "value": "captured"
        })
    elif event_type == "simulation.result_captured":
        ops.append({
            "type": "parameter.update",
            "name": f"simulation.{payload.get('document_id', 'unknown')}.result_status",
            "value": payload.get("status", "completed")
        })

    return ops
