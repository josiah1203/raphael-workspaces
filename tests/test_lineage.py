"""Graph lineage integration test for fork/slice routes."""

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from raphael_workspaces.app import app

client = TestClient(app)
BASE = "/v1/workspaces/default/modules/power-board-v2"


@patch("raphael_workspaces.routes.httpx.Client")
def test_fork_records_graph_lineage(mock_client_cls) -> None:
    mock_client = mock_client_cls.return_value.__enter__.return_value
    mock_client.post.return_value.status_code = 201
    fork_id = f"fork-{uuid.uuid4().hex[:8]}"
    res = client.post(f"{BASE}/fork", json={"id": fork_id, "name": "Lineage Fork"})
    assert res.status_code == 200
    mock_client.post.assert_called()
    call = mock_client.post.call_args
    assert "/v1/graph/edges" in call.args[0]
    payload = call.kwargs["json"]
    assert payload["edge_type"] == "forked_from"
    assert payload["from_id"] == fork_id
    assert payload["to_id"] == "power-board-v2"
