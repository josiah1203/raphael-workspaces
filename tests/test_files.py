"""Module file tree/blob API tests."""

import base64
import uuid

from fastapi.testclient import TestClient

from raphael_workspaces.app import app

client = TestClient(app)
WS = "default"
BASE = f"/v1/workspaces/{WS}/modules"


def _module_base(module_id: str) -> str:
    return f"{BASE}/{module_id}"


def _create_module() -> str:
    module_id = f"files-{uuid.uuid4().hex[:8]}"
    res = client.post(f"{BASE}", json={"id": module_id, "name": f"Files {module_id}"})
    assert res.status_code == 200
    return module_id


def test_file_tree_empty() -> None:
    module_id = _create_module()
    res = client.get(f"{_module_base(module_id)}/files/tree", params={"branch": "main", "path": ""})
    assert res.status_code == 200
    body = res.json()
    assert body["branch"] == "main"
    assert body["path"] == ""
    assert body["entries"] == []


def test_file_tree_lists_entries() -> None:
    module_id = _create_module()
    client.put(
        f"{_module_base(module_id)}/files/blob",
        json={"branch": "main", "path": "README.md", "content": "# Hello\n", "message": "add readme"},
    )
    client.put(
        f"{_module_base(module_id)}/files/blob",
        json={"branch": "main", "path": "src/main.py", "content": "print('hi')\n"},
    )
    res = client.get(f"{_module_base(module_id)}/files/tree", params={"branch": "main", "path": ""})
    assert res.status_code == 200
    names = {e["name"] for e in res.json()["entries"]}
    kinds = {e["kind"] for e in res.json()["entries"]}
    assert "README.md" in names
    assert "src" in names
    assert kinds <= {"file", "directory"}


def test_file_tree_subdirectory() -> None:
    module_id = _create_module()
    client.put(
        f"{_module_base(module_id)}/files/blob",
        json={"branch": "main", "path": "src/main.py", "content": "x = 1\n"},
    )
    res = client.get(
        f"{_module_base(module_id)}/files/tree",
        params={"branch": "main", "path": "src"},
    )
    assert res.status_code == 200
    entries = res.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["name"] == "main.py"
    assert entries[0]["kind"] == "file"


def test_get_blob_text() -> None:
    module_id = _create_module()
    content = "line one\nline two\n"
    client.put(
        f"{_module_base(module_id)}/files/blob",
        json={"branch": "main", "path": "notes.txt", "content": content},
    )
    res = client.get(
        f"{_module_base(module_id)}/files/blob",
        params={"branch": "main", "path": "notes.txt"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["content"] == content
    assert body["is_binary"] is False
    assert body["size"] == len(content.encode("utf-8"))


def test_get_blob_binary() -> None:
    module_id = _create_module()
    raw = b"\x89PNG\r\n\x1a\n"
    encoded = base64.b64encode(raw).decode("ascii")
    client.put(
        f"{_module_base(module_id)}/files/blob",
        json={
            "branch": "main",
            "path": "assets/logo.png",
            "content_base64": encoded,
            "content_type": "image/png",
        },
    )
    res = client.get(
        f"{_module_base(module_id)}/files/blob",
        params={"branch": "main", "path": "assets/logo.png"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["is_binary"] is True
    assert body["content_type"] == "image/png"
    assert base64.b64decode(body["content_base64"]) == raw


def test_put_blob_updates_content() -> None:
    module_id = _create_module()
    path = "config.json"
    client.put(
        f"{_module_base(module_id)}/files/blob",
        json={"branch": "main", "path": path, "content": '{"a": 1}'},
    )
    res = client.put(
        f"{_module_base(module_id)}/files/blob",
        json={"branch": "main", "path": path, "content": '{"a": 2}', "message": "bump"},
    )
    assert res.status_code == 200
    got = client.get(
        f"{_module_base(module_id)}/files/blob",
        params={"branch": "main", "path": path},
    ).json()
    assert got["content"] == '{"a": 2}'


def test_blob_not_found() -> None:
    module_id = _create_module()
    res = client.get(
        f"{_module_base(module_id)}/files/blob",
        params={"branch": "main", "path": "missing.txt"},
    )
    assert res.status_code == 404


def test_files_module_not_found() -> None:
    res = client.get(f"{BASE}/no-such-module/files/tree", params={"branch": "main"})
    assert res.status_code == 404


def test_seeded_module_file_tree() -> None:
    res = client.get(f"{_module_base('power-board-v2')}/files/tree", params={"branch": "main"})
    assert res.status_code == 200
    assert "entries" in res.json()


def test_put_blob_requires_content() -> None:
    module_id = _create_module()
    res = client.put(
        f"{_module_base(module_id)}/files/blob",
        json={"branch": "main", "path": "empty.txt"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "content_required"


def test_put_blob_requires_path() -> None:
    module_id = _create_module()
    res = client.put(
        f"{_module_base(module_id)}/files/blob",
        json={"branch": "main", "content": "x"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "path_required"


def test_file_edit_creates_commit_when_message_provided() -> None:
    module_id = _create_module()
    client.put(
        f"{_module_base(module_id)}/files/blob",
        json={
            "branch": "main",
            "path": "tracked.txt",
            "content": "v1\n",
            "message": "add tracked file",
        },
    )
    log = client.get(f"{_module_base(module_id)}/log", params={"branch": "main"}).json()
    messages = [c.get("message") for c in log.get("commits", [])]
    assert "add tracked file" in messages
