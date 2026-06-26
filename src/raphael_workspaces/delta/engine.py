from typing import Any, Dict, List
from raphael_workspaces.delta.mapper import map_wire_event_to_common_ops

class DeltaEngine:
    """
    Engine for squashing raw micro-events into logical commits.
    """
    
    def squash_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Groups micro-events and maps them to common operations,
        applying clustering rules to reduce noise.
        """
        all_ops = []
        for event in events:
            event_type = event.get("event_type")
            payload = event.get("payload", {})
            ops = map_wire_event_to_common_ops(event_type, payload)
            all_ops.extend(ops)
            
        return self._apply_clustering_rules(all_ops)
    
    def _apply_clustering_rules(self, ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Applies domain-specific rules to squash redundant operations.
        """
        if not ops:
            return []
            
        squashed = []
        
        # Rule: component.move - only keep the last position for each component id
        last_moves = {}
        # Rule: parameter.update - only keep the last value for each parameter name
        last_params = {}
        
        others = []
        
        for op in ops:
            op_type = op.get("type")
            if op_type == "component.move":
                last_moves[op.get("id")] = op
            elif op_type == "parameter.update":
                last_params[op.get("name")] = op
            else:
                others.append(op)
        
        squashed.extend(last_moves.values())
        squashed.extend(last_params.values())
        squashed.extend(others)
        
        return squashed
