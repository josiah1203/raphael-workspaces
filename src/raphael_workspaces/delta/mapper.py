from typing import Any, Dict, List


def map_wire_event_to_common_ops(event_type: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Maps a tool-specific wire event to a list of common operations.
    """
    ops = []

    if event_type == "geometry.feature_created":
        ops.append(
            {
                "type": "parameter.update",
                "name": f"feature.{payload.get('feature_name', payload.get('name', 'unknown'))}.status",
                "value": "created",
            }
        )
    elif event_type == "geometry.feature_modified":
        if payload.get("is_component") or "transform" in payload:
            transform = payload.get("transform", {})
            ops.append(
                {
                    "type": "component.move",
                    "id": payload.get("feature_id", payload.get("id")),
                    "x": transform.get("x", 0),
                    "y": transform.get("y", 0),
                    "z": transform.get("z", 0),
                    "rotation": transform.get("rotation", 0),
                }
            )
    elif event_type in ("electrical.footprint_added", "electrical.footprint_modified"):
        if "position" in payload:
            pos = payload.get("position", {})
            ops.append(
                {
                    "type": "component.move",
                    "id": payload.get("footprint_ref", payload.get("component_id", "unknown")),
                    "x": pos.get("x", 0),
                    "y": pos.get("y", 0),
                    "z": pos.get("z", 0),
                    "rotation": payload.get("rotation", 0),
                }
            )
        else:
            ops.append(
                {
                    "type": "parameter.update",
                    "name": f"footprint.{payload.get('footprint_ref', payload.get('component_id', 'unknown'))}.status",
                    "value": "modified" if event_type == "electrical.footprint_modified" else "added",
                }
            )
    elif event_type == "electrical.net_changed":
        ops.append(
            {
                "type": "parameter.update",
                "name": f"net.{payload.get('net_name')}.status",
                "value": payload.get("change"),
            }
        )
    elif event_type == "vcs.push":
        ops.append({"type": "parameter.update", "name": "vcs.last_push_ref", "value": payload.get("ref")})

    return ops
