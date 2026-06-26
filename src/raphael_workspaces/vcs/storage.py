import sqlite3
from pathlib import Path
from typing import List, Optional, Dict, Any
from raphael_workspaces.paths import raphael_home

class VCSStorage:
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = raphael_home() / "vcs.db"
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS repos (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS commits (
                    hash TEXT PRIMARY KEY,
                    repo_id TEXT NOT NULL,
                    parent_hash TEXT,
                    author TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    message TEXT,
                    ops JSON,
                    wal_range_start INTEGER,
                    wal_range_end INTEGER,
                    FOREIGN KEY(repo_id) REFERENCES repos(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS refs (
                    name TEXT,
                    repo_id TEXT,
                    commit_hash TEXT,
                    PRIMARY KEY(name, repo_id),
                    FOREIGN KEY(repo_id) REFERENCES repos(id),
                    FOREIGN KEY(commit_hash) REFERENCES commits(hash)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    name TEXT,
                    repo_id TEXT,
                    commit_hash TEXT,
                    PRIMARY KEY(name, repo_id),
                    FOREIGN KEY(repo_id) REFERENCES repos(id),
                    FOREIGN KEY(commit_hash) REFERENCES commits(hash)
                )
            """)

    def create_repo(self, repo_id: str, name: str, description: Optional[str] = None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO repos (id, name, description) VALUES (?, ?, ?)",
                         (repo_id, name, description))

    def get_repo(self, repo_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT id, name, description FROM repos WHERE id = ?", (repo_id,)).fetchone()
            if row:
                return {"id": row[0], "name": row[1], "description": row[2]}
        return None

    def add_commit(self, commit_hash: str, repo_id: str, parent_hash: Optional[str], 
                   author: str, message: str, ops: str, wal_start: int, wal_end: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO commits (hash, repo_id, parent_hash, author, message, ops, wal_range_start, wal_range_end)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (commit_hash, repo_id, parent_hash, author, message, ops, wal_start, wal_end))

    def update_ref(self, name: str, repo_id: str, commit_hash: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO refs (name, repo_id, commit_hash) VALUES (?, ?, ?)",
                         (name, repo_id, commit_hash))

    def get_ref(self, name: str, repo_id: str) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT commit_hash FROM refs WHERE name = ? AND repo_id = ?", 
                               (name, repo_id)).fetchone()
            if row:
                return row[0]
        return None

    def ref_exists(self, name: str, repo_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT 1 FROM refs WHERE name = ? AND repo_id = ?", 
                               (name, repo_id)).fetchone()
            return row is not None

    def get_commits(self, repo_id: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT hash, parent_hash, author, timestamp, message, ops, wal_range_start, wal_range_end 
                FROM commits WHERE repo_id = ? ORDER BY rowid DESC
            """, (repo_id,)).fetchall()
            return [
                {
                    "hash": r[0], "parent_hash": r[1], "author": r[2], 
                    "timestamp": r[3], "message": r[4], "ops": r[5],
                    "wal_range_start": r[6], "wal_range_end": r[7]
                } for r in rows
            ]

    def get_last_wal_index(self, repo_id: str, branch: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT wal_range_end FROM commits 
                WHERE repo_id = ? AND hash = (SELECT commit_hash FROM refs WHERE name = ? AND repo_id = ?)
            """, (repo_id, branch, repo_id)).fetchone()
            if row and row[0] is not None:
                return row[0]
        return 0

    def list_all_refs(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT name, repo_id, commit_hash FROM refs").fetchall()
            return [{"name": r[0], "repo_id": r[1], "commit_hash": r[2]} for r in rows]

    def add_tag(self, name: str, repo_id: str, commit_hash: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO tags (name, repo_id, commit_hash) VALUES (?, ?, ?)",
                         (name, repo_id, commit_hash))

    def get_tags(self, repo_id: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT name, commit_hash FROM tags WHERE repo_id = ?", (repo_id,)).fetchall()
            return [{"name": r[0], "commit_hash": r[1]} for r in rows]

    def list_branches(self, repo_id: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT name, commit_hash FROM refs WHERE repo_id = ? ORDER BY name",
                (repo_id,),
            ).fetchall()
            return [{"name": r[0], "commit_hash": r[1]} for r in rows]
