"""Workspaces event publish tests."""

import tempfile
import uuid
from pathlib import Path

from raphael_workspaces.store import WorkspacesStore


def test_merge_publishes_event(monkeypatch) -> None:
    published: list[tuple] = []

    def fake_publish(event_type, data, **meta):
        published.append((event_type, data))

    monkeypatch.setattr(
        "raphael_contracts.kafka.publish_event",
        fake_publish,
    )
    db_path = Path(tempfile.mkdtemp()) / "merge-event.db"
    monkeypatch.setenv("RAPHAEL_WORKSPACES_DB", str(db_path))
    store = WorkspacesStore()
    module_id = f"merge-src-{uuid.uuid4().hex[:8]}"
    store.create_module("default", module_id, "Merge Source")
    store.create_branch("default", module_id, "feature", "main")
    store.create_commit("default", module_id, "feature commit", branch="feature")
    result = store.merge_branches("default", module_id, "feature", "main")
    assert result.get("status") == "merged", f"expected merged, got {result}"
    assert any(p[0] == "raphael.workspaces.merge" for p in published)
