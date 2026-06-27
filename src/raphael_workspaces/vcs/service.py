import hashlib
import json
from typing import Any

from raphael_workspaces.delta.engine import DeltaEngine
from raphael_workspaces.vcs.storage import VCSStorage


def _op_key(op: dict[str, Any]) -> str:
    return str(op.get("id") or op.get("name") or op.get("type") or "")


class VCService:
    def __init__(self, storage: VCSStorage, delta_engine: DeltaEngine):
        self.storage = storage
        self.delta_engine = delta_engine

    def init_repo(self, repo_id: str, name: str, workspace_id: str = "default") -> None:
        self.storage.create_repo(repo_id, name, workspace_id)
        self.storage.update_ref("main", repo_id, workspace_id, None)

    def create_commit(
        self,
        repo_id: str,
        workspace_id: str,
        branch: str,
        message: str,
        author: str,
        events: list[dict[str, Any]],
        wal_start: int,
        wal_end: int,
        intent_summary: str | None = None,
    ) -> str:
        parent_hash = self.storage.get_ref(branch, repo_id, workspace_id)
        ops = self.delta_engine.squash_events(events)
        ops_json = json.dumps(ops)
        content = f"{parent_hash or ''}{repo_id}{workspace_id}{branch}{author}{message}{ops_json}{wal_start}{wal_end}"
        commit_hash = hashlib.sha256(content.encode()).hexdigest()
        self.storage.add_commit(
            commit_hash, repo_id, workspace_id, parent_hash, author, message, ops_json, wal_start, wal_end, intent_summary
        )
        self.storage.update_ref(branch, repo_id, workspace_id, commit_hash)
        return commit_hash

    def _commit_map(self, repo_id: str, workspace_id: str) -> dict[str, dict[str, Any]]:
        return {c["hash"]: c for c in self.storage.get_commits(repo_id, workspace_id)}

    def _ancestors(self, commit_hash: str | None, repo_id: str, workspace_id: str) -> set[str]:
        commits = self._commit_map(repo_id, workspace_id)
        seen: set[str] = set()
        cur = commit_hash
        while cur and cur not in seen:
            seen.add(cur)
            cur = commits.get(cur, {}).get("parent_hash")
        return seen

    def _common_ancestor(self, a: str | None, b: str | None, repo_id: str, workspace_id: str) -> str | None:
        if not a or not b:
            return None
        if a == b:
            return a
        ancestors_b = self._ancestors(b, repo_id, workspace_id)
        cur = a
        commits = self._commit_map(repo_id, workspace_id)
        while cur:
            if cur in ancestors_b:
                return cur
            cur = commits.get(cur, {}).get("parent_hash")
        return None

    def get_log(self, repo_id: str, workspace_id: str = "default", branch: str | None = None) -> list[dict[str, Any]]:
        commits = self._commit_map(repo_id, workspace_id)
        if not branch:
            return list(commits.values())
        tip = self.storage.get_ref(branch, repo_id, workspace_id)
        if not tip:
            return []
        log: list[dict[str, Any]] = []
        cur = tip
        seen: set[str] = set()
        while cur and cur not in seen:
            seen.add(cur)
            if cur in commits:
                log.append(commits[cur])
            cur = commits[cur].get("parent_hash") if cur in commits else None
        return log

    def create_branch(self, repo_id: str, workspace_id: str, new_branch: str, from_branch: str) -> None:
        if not self.storage.ref_exists(from_branch, repo_id, workspace_id):
            raise ValueError(f"Source branch {from_branch} not found")
        commit_hash = self.storage.get_ref(from_branch, repo_id, workspace_id)
        self.storage.update_ref(new_branch, repo_id, workspace_id, commit_hash)

    def create_tag(self, repo_id: str, workspace_id: str, tag_name: str, branch: str) -> None:
        if not self.storage.ref_exists(branch, repo_id, workspace_id):
            raise ValueError(f"Branch {branch} not found")
        commit_hash = self.storage.get_ref(branch, repo_id, workspace_id)
        if not commit_hash:
            raise ValueError(f"Cannot tag empty branch {branch}")
        self.storage.add_tag(tag_name, repo_id, workspace_id, commit_hash)

    def merge(self, repo_id: str, workspace_id: str, source_branch: str, target_branch: str, author: str) -> dict[str, Any]:
        if not self.storage.ref_exists(source_branch, repo_id, workspace_id) or not self.storage.ref_exists(
            target_branch, repo_id, workspace_id
        ):
            raise ValueError("Both source and target branches must exist")

        source_hash = self.storage.get_ref(source_branch, repo_id, workspace_id)
        target_hash = self.storage.get_ref(target_branch, repo_id, workspace_id)

        if source_hash == target_hash:
            return {"status": "up-to-date", "hash": target_hash}
        if not source_hash:
            return {"status": "up-to-date", "hash": target_hash}
        if not target_hash:
            self.storage.update_ref(target_branch, repo_id, workspace_id, source_hash)
            return {"status": "merged", "hash": source_hash}

        base = self._common_ancestor(source_hash, target_hash, repo_id, workspace_id)
        commits = self._commit_map(repo_id, workspace_id)

        def ops_since(base_hash: str | None, tip: str) -> list[dict[str, Any]]:
            ops: list[dict[str, Any]] = []
            cur = tip
            while cur and cur != base_hash:
                c = commits.get(cur)
                if not c:
                    break
                ops = json.loads(c["ops"]) + ops
                cur = c.get("parent_hash")
            return ops

        source_ops = ops_since(base, source_hash)
        target_ops = ops_since(base, target_hash)

        conflicts = []
        target_by_key = {_op_key(op): op for op in target_ops if _op_key(op)}
        for sop in source_ops:
            key = _op_key(sop)
            if not key:
                continue
            top = target_by_key.get(key)
            if top and top != sop:
                conflicts.append({"id": key, "source": sop, "target": top})

        if conflicts:
            return {"status": "conflict", "conflicts": conflicts}

        merged_ops = target_ops + [op for op in source_ops if _op_key(op) not in target_by_key]
        ops_json = json.dumps(merged_ops)
        content = f"{target_hash}{source_hash}{repo_id}{workspace_id}merge{author}{ops_json}"
        merge_hash = hashlib.sha256(content.encode()).hexdigest()
        self.storage.add_commit(
            merge_hash,
            repo_id,
            workspace_id,
            target_hash,
            author,
            f"Merge branch {source_branch}",
            ops_json,
            0,
            0,
        )
        self.storage.update_ref(target_branch, repo_id, workspace_id, merge_hash)
        return {"status": "merged", "hash": merge_hash}

    def fork_repo(self, repo_id: str, workspace_id: str, new_id: str, name: str) -> dict[str, Any]:
        self.storage.copy_repo(repo_id, new_id, workspace_id, name, parent_module_id=repo_id)
        return self.storage.get_repo(new_id, workspace_id) or {"id": new_id, "name": name}

    def slice_repo(
        self,
        repo_id: str,
        workspace_id: str,
        new_id: str,
        name: str,
        scope: str | None = None,
    ) -> dict[str, Any]:
        attribution = json.dumps({"scope": scope or "full", "source": repo_id})
        self.storage.copy_repo(repo_id, new_id, workspace_id, name, parent_module_id=repo_id, slice_attribution=attribution)
        return self.storage.get_repo(new_id, workspace_id) or {"id": new_id, "name": name}
