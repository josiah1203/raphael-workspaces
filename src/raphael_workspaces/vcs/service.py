import hashlib
import json
from typing import List, Optional, Dict, Any
from raphael_workspaces.vcs.storage import VCSStorage
from raphael_workspaces.delta.engine import DeltaEngine

class VCService:
    def __init__(self, storage: VCSStorage, delta_engine: DeltaEngine):
        self.storage = storage
        self.delta_engine = delta_engine

    def init_repo(self, repo_id: str, name: str):
        self.storage.create_repo(repo_id, name)
        # Create default branch 'main'
        self.storage.update_ref("main", repo_id, None)

    def create_commit(self, repo_id: str, branch: str, message: str, 
                      author: str, events: List[Dict[str, Any]], 
                      wal_start: int, wal_end: int) -> str:
        
        parent_hash = self.storage.get_ref(branch, repo_id)
        
        # Squash events
        ops = self.delta_engine.squash_events(events)
        ops_json = json.dumps(ops)
        
        # Calculate commit hash
        content = f"{parent_hash or ''}{repo_id}{branch}{author}{message}{ops_json}{wal_start}{wal_end}"
        commit_hash = hashlib.sha256(content.encode()).hexdigest()
        
        self.storage.add_commit(commit_hash, repo_id, parent_hash, author, message, ops_json, wal_start, wal_end)
        self.storage.update_ref(branch, repo_id, commit_hash)
        
        return commit_hash

    def get_log(self, repo_id: str, branch: Optional[str] = None) -> List[Dict[str, Any]]:
        # For now, just return all commits for the repo
        return self.storage.get_commits(repo_id)

    def create_branch(self, repo_id: str, new_branch: str, from_branch: str):
        if not self.storage.ref_exists(from_branch, repo_id):
            raise ValueError(f"Source branch {from_branch} not found")
        commit_hash = self.storage.get_ref(from_branch, repo_id)
        self.storage.update_ref(new_branch, repo_id, commit_hash)

    def create_tag(self, repo_id: str, tag_name: str, branch: str):
        if not self.storage.ref_exists(branch, repo_id):
            raise ValueError(f"Branch {branch} not found")
        commit_hash = self.storage.get_ref(branch, repo_id)
        if not commit_hash:
            raise ValueError(f"Cannot tag empty branch {branch}")
        self.storage.add_tag(tag_name, repo_id, commit_hash)

    def merge(self, repo_id: str, source_branch: str, target_branch: str, author: str) -> Dict[str, Any]:
        if not self.storage.ref_exists(source_branch, repo_id) or not self.storage.ref_exists(target_branch, repo_id):
            raise ValueError("Both source and target branches must exist")
            
        source_hash = self.storage.get_ref(source_branch, repo_id)
        target_hash = self.storage.get_ref(target_branch, repo_id)
        
        if source_hash == target_hash:
            return {"status": "up-to-date", "hash": target_hash}
            
        if not source_hash:
            return {"status": "up-to-date", "hash": target_hash}
            
        if not target_hash:
            # Fast-forward
            self.storage.update_ref(target_branch, repo_id, source_hash)
            return {"status": "merged", "hash": source_hash}
            
        # Get source commits since they diverged (simple version: just get all and compare)
        # For now, let's just take the last commit from source and its ops
        # In a real VCS we'd find the common ancestor.
        
        source_commits = self.storage.get_commits(repo_id)
        target_commits = source_commits # same table
        
        source_commit = next(c for c in source_commits if c["hash"] == source_hash)
        target_commit = next(c for c in target_commits if c["hash"] == target_hash)
        
        source_ops = json.loads(source_commit["ops"])
        target_ops = json.loads(target_commit["ops"])
        
        # Conflict detection: same component moved or same parameter updated
        conflicts = []
        source_ids = {op.get("id") or op.get("name") for op in source_ops if op.get("id") or op.get("name")}
        target_ids = {op.get("id") or op.get("name") for op in target_ops if op.get("id") or op.get("name")}
        
        intersection = source_ids.intersection(target_ids)
        if intersection:
            for item_id in intersection:
                # Check if values are actually different
                s_op = next(op for op in source_ops if (op.get("id") or op.get("name")) == item_id)
                t_op = next(op for op in target_ops if (op.get("id") or op.get("name")) == item_id)
                if s_op != t_op:
                    conflicts.append({"id": item_id, "source": s_op, "target": t_op})
        
        if conflicts:
            return {"status": "conflict", "conflicts": conflicts}
            
        # No conflicts, create merge commit
        merged_ops = target_ops + [op for op in source_ops if (op.get("id") or op.get("name")) not in target_ids]
        
        content = f"{target_hash}{source_hash}{repo_id}merge{author}{json.dumps(merged_ops)}"
        merge_hash = hashlib.sha256(content.encode()).hexdigest()
        
        self.storage.add_commit(merge_hash, repo_id, target_hash, author, 
                               f"Merge branch {source_branch}", json.dumps(merged_ops), 0, 0)
        self.storage.update_ref(target_branch, repo_id, merge_hash)
        
        return {"status": "merged", "hash": merge_hash}
