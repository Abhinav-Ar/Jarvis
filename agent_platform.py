"""Local-first persistent agent substrate for ORION."""

from __future__ import annotations

import json
import importlib.util
import os
import sqlite3
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
import diagnostics
import shutil


RUNTIME = Path(os.getenv("ORION_RUNTIME_DIR") or os.getenv("JARVIS_RUNTIME_DIR") or Path.cwd() / ".runtime")
DATABASE = RUNTIME / "agent.db"
STATUS = RUNTIME / "platform-status.json"
_lock = threading.RLock()


class AgentPlatform:
    def __init__(self, database: Path | None = None) -> None:
        self.database = database or DATABASE
        self.status_path = self.database.parent / "platform-status.json"
        self.cloud_limit_disabled_flag = self.database.parent / "cloud-limit-disabled"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with _lock, self._connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY, key TEXT NOT NULL, value TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user', created REAL NOT NULL, updated REAL NOT NULL,
                    UNIQUE(key)
                );
                CREATE TABLE IF NOT EXISTS documents (
                    path TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
                    modified REAL NOT NULL, indexed REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflows (
                    name TEXT PRIMARY KEY, definition TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY, workflow TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL, run_after REAL NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capabilities (
                    name TEXT PRIMARY KEY, category TEXT NOT NULL, available INTEGER NOT NULL,
                    detail TEXT NOT NULL, checked REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cloud_usage (
                    id INTEGER PRIMARY KEY, purpose TEXT NOT NULL, model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_sessions (
                    id INTEGER PRIMARY KEY, repository TEXT NOT NULL, path TEXT NOT NULL,
                    branch TEXT NOT NULL, start_commit TEXT NOT NULL, end_commit TEXT NOT NULL DEFAULT '',
                    start_state TEXT NOT NULL, end_state TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL, started REAL NOT NULL, updated REAL NOT NULL, ended REAL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, request TEXT NOT NULL, goal TEXT NOT NULL,
                    workflow TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
                    result_summary TEXT NOT NULL DEFAULT '', error_code TEXT NOT NULL DEFAULT '',
                    created REAL NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, step INTEGER NOT NULL,
                    action TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
                    evidence TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs(status, run_after);
                CREATE INDEX IF NOT EXISTS idx_cloud_created ON cloud_usage(created);
                CREATE INDEX IF NOT EXISTS idx_project_active ON project_sessions(status, updated);
                CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated DESC);
                CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id);
            """)
        self.write_status()

    def remember(self, key: str, value: str, source: str = "user") -> dict:
        key, value = key.strip(), value.strip()
        if not key or not value:
            return {"ok": False, "error": "Memory needs both a name and a value."}
        now = time.time()
        with _lock, self._connect() as db:
            db.execute(
                "INSERT INTO memories(key,value,source,created,updated) VALUES(?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,source=excluded.source,updated=excluded.updated",
                (key, value, source, now, now),
            )
        self.write_status()
        return {"ok": True, "key": key, "stored": True}

    def forget(self, key: str) -> dict:
        with _lock, self._connect() as db:
            cursor = db.execute("DELETE FROM memories WHERE key = ?", (key.strip(),))
        self.write_status()
        return {"ok": bool(cursor.rowcount), "key": key.strip(), "deleted": bool(cursor.rowcount)}

    def search_memory(self, query: str, limit: int = 8) -> dict:
        pattern = f"%{query.strip()}%"
        with _lock, self._connect() as db:
            rows = db.execute(
                "SELECT key,value,source,updated FROM memories WHERE key LIKE ? OR value LIKE ? "
                "ORDER BY updated DESC LIMIT ?", (pattern, pattern, max(1, min(limit, 20))),
            ).fetchall()
        return {"ok": True, "matches": [dict(row) for row in rows]}

    def index_paths(self, roots: list[Path], maximum_files: int = 500) -> dict:
        allowed = {".txt", ".md", ".py", ".json", ".csv", ".rtf"}
        indexed = 0
        with _lock, self._connect() as db:
            for root in roots:
                root = root.expanduser().resolve()
                if not root.exists():
                    continue
                for path in root.rglob("*"):
                    if indexed >= maximum_files:
                        break
                    if not path.is_file() or path.suffix.lower() not in allowed or path.stat().st_size > 1_000_000:
                        continue
                    try:
                        content = path.read_text(encoding="utf-8", errors="ignore")[:100_000]
                        modified = path.stat().st_mtime
                        db.execute(
                            "INSERT INTO documents(path,title,content,modified,indexed) VALUES(?,?,?,?,?) "
                            "ON CONFLICT(path) DO UPDATE SET title=excluded.title,content=excluded.content,"
                            "modified=excluded.modified,indexed=excluded.indexed",
                            (str(path), path.name, content, modified, time.time()),
                        )
                        indexed += 1
                    except OSError:
                        continue
        self.write_status()
        return {"ok": True, "indexed": indexed, "roots": [str(path) for path in roots]}

    def search_documents(self, query: str, limit: int = 10) -> dict:
        pattern = f"%{query.strip()}%"
        with _lock, self._connect() as db:
            rows = db.execute(
                "SELECT path,title,substr(content,1,500) AS excerpt,modified FROM documents "
                "WHERE title LIKE ? OR content LIKE ? ORDER BY modified DESC LIMIT ?",
                (pattern, pattern, max(1, min(limit, 25))),
            ).fetchall()
        return {"ok": True, "matches": [dict(row) for row in rows]}

    def context_for(self, request: str, limit: int = 5) -> dict:
        """Small local retrieval packet; never sends the entire database."""
        words = list(dict.fromkeys(re.findall(r"[a-z0-9_-]{4,}", request.lower())))[:8]
        if not words:
            return {"memories": [], "documents": [], "tasks": []}
        clauses = " OR ".join(["lower(key) LIKE ? OR lower(value) LIKE ?"] * len(words))
        parameters = [f"%{word}%" for word in words for _ in (0, 1)]
        document_clauses = " OR ".join(["lower(title) LIKE ? OR lower(content) LIKE ?"] * len(words))
        with _lock, self._connect() as db:
            memories = db.execute(
                f"SELECT key,value FROM memories WHERE {clauses} ORDER BY updated DESC LIMIT ?",
                (*parameters, limit),
            ).fetchall()
            documents = db.execute(
                f"SELECT path,title,substr(content,1,240) AS excerpt FROM documents WHERE {document_clauses} "
                "ORDER BY modified DESC LIMIT ?", (*parameters, limit),
            ).fetchall()
            tasks = []
            if any(marker in request.lower() for marker in ("what happened", "problem", "failed", "failure", "last task", "previous task", "logs")):
                task_rows = db.execute(
                    "SELECT id,request,goal,status,result_summary,error_code,updated FROM tasks "
                    "ORDER BY updated DESC LIMIT 3"
                ).fetchall()
                for task in task_rows:
                    item = dict(task)
                    event = db.execute(
                        "SELECT action,status,detail,evidence FROM task_events WHERE task_id=? ORDER BY id DESC LIMIT 1",
                        (item["id"],),
                    ).fetchone()
                    item["last_event"] = dict(event) if event else {}
                    tasks.append(item)
        return {
            "memories": [dict(row) for row in memories],
            "documents": [dict(row) for row in documents],
            "tasks": tasks,
        }

    def save_workflow(self, name: str, steps: list[dict[str, Any]]) -> dict:
        if not name.strip() or not steps:
            return {"ok": False, "error": "A workflow needs a name and at least one step."}
        with _lock, self._connect() as db:
            db.execute(
                "INSERT INTO workflows(name,definition,updated) VALUES(?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET definition=excluded.definition,updated=excluded.updated",
                (name.strip(), json.dumps(steps), time.time()),
            )
        self.write_status()
        return {"ok": True, "name": name.strip(), "steps": len(steps)}

    def queue_job(self, workflow: str, payload: dict[str, Any], run_after: float | None = None) -> dict:
        now = time.time()
        with _lock, self._connect() as db:
            cursor = db.execute(
                "INSERT INTO jobs(workflow,payload,status,run_after,created,updated) VALUES(?,?,?,?,?,?)",
                (workflow, json.dumps(payload), "queued", run_after or now, now, now),
            )
        self.write_status()
        return {"ok": True, "job_id": cursor.lastrowid, "status": "queued"}

    def begin_task(self, task_id: str, request: str, goal: str, workflow: str = "") -> dict:
        now = time.time()
        request = str(diagnostics.redact(request))
        goal = str(diagnostics.redact(goal))
        with _lock, self._connect() as db:
            db.execute(
                "INSERT INTO tasks(id,request,goal,workflow,status,created,updated) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET request=excluded.request,goal=excluded.goal,"
                "workflow=excluded.workflow,status=excluded.status,updated=excluded.updated",
                (task_id, request[:4000], goal[:4000], workflow[:100], "planned", now, now),
            )
        return {"ok": True, "task_id": task_id}

    def record_task_event(
        self, task_id: str, step: int, action: str, status: str,
        detail: str = "", evidence: dict[str, Any] | None = None,
    ) -> dict:
        safe_evidence = json.dumps(diagnostics.redact(evidence or {}), default=str)[:12000]
        detail = str(diagnostics.redact(detail))
        with _lock, self._connect() as db:
            cursor = db.execute(
                "INSERT INTO task_events(task_id,step,action,status,detail,evidence,created) "
                "VALUES(?,?,?,?,?,?,?)",
                (task_id, int(step), action[:100], status[:40], detail[:2000], safe_evidence, time.time()),
            )
            db.execute("UPDATE tasks SET status=?,updated=? WHERE id=?", ("executing", time.time(), task_id))
        return {"ok": True, "event_id": cursor.lastrowid}

    def finish_task(self, task_id: str, status: str, summary: str = "", error_code: str = "") -> dict:
        with _lock, self._connect() as db:
            cursor = db.execute(
                "UPDATE tasks SET status=?,result_summary=?,error_code=?,updated=? WHERE id=?",
                (status[:40], summary[:4000], error_code[:100], time.time(), task_id),
            )
        self.write_status()
        return {"ok": bool(cursor.rowcount), "task_id": task_id, "status": status}

    def recent_tasks(self, limit: int = 5, query: str = "") -> dict:
        limit = max(1, min(int(limit), 20))
        with _lock, self._connect() as db:
            if query.strip():
                pattern = f"%{query.strip()}%"
                rows = db.execute(
                    "SELECT * FROM tasks WHERE request LIKE ? OR goal LIKE ? OR result_summary LIKE ? "
                    "ORDER BY updated DESC LIMIT ?", (pattern, pattern, pattern, limit),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM tasks ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
            tasks = []
            for row in rows:
                item = dict(row)
                events = db.execute(
                    "SELECT step,action,status,detail,evidence,created FROM task_events "
                    "WHERE task_id=? ORDER BY id", (item["id"],),
                ).fetchall()
                item["events"] = [dict(event) for event in events]
                tasks.append(item)
        return {"ok": True, "tasks": tasks}

    def start_project_session(self, repository: str, path: str, branch: str, commit: str, state: dict) -> dict:
        now = time.time()
        with _lock, self._connect() as db:
            db.execute("UPDATE project_sessions SET status='paused',updated=? WHERE status='active'", (now,))
            cursor = db.execute(
                "INSERT INTO project_sessions(repository,path,branch,start_commit,start_state,status,started,updated) "
                "VALUES(?,?,?,?,?,'active',?,?)",
                (repository, path, branch, commit, json.dumps(state), now, now),
            )
        self.write_status()
        return {"ok": True, "session_id": cursor.lastrowid, "repository": repository, "status": "active"}

    def active_project_session(self) -> dict:
        with _lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM project_sessions WHERE status='active' ORDER BY updated DESC LIMIT 1"
            ).fetchone()
        return {"ok": True, "session": dict(row) if row else None}

    def latest_project_session(self, repository: str) -> dict:
        with _lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM project_sessions WHERE lower(repository)=lower(?) ORDER BY updated DESC LIMIT 1",
                (repository,),
            ).fetchone()
        return {"ok": True, "session": dict(row) if row else None}

    def close_project_session(self, session_id: int, commit: str, state: dict, notes: str) -> dict:
        now = time.time()
        with _lock, self._connect() as db:
            cursor = db.execute(
                "UPDATE project_sessions SET end_commit=?,end_state=?,notes=?,status='closed',updated=?,ended=? "
                "WHERE id=? AND status='active'",
                (commit, json.dumps(state), notes[:4000], now, now, int(session_id)),
            )
        self.write_status()
        return {"ok": bool(cursor.rowcount), "session_id": session_id, "status": "closed" if cursor.rowcount else "not_active"}

    def register_capability(self, name: str, category: str, available: bool, detail: str = "") -> None:
        with _lock, self._connect() as db:
            db.execute(
                "INSERT INTO capabilities(name,category,available,detail,checked) VALUES(?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET category=excluded.category,available=excluded.available,"
                "detail=excluded.detail,checked=excluded.checked",
                (name, category, int(available), detail, time.time()),
            )
        self.write_status()

    def cloud_allowed(self, purpose: str = "general") -> tuple[bool, str]:
        if os.getenv("ORION_CLOUD_ENABLED", os.getenv("JARVIS_CLOUD_ENABLED", "1")) != "1":
            return False, "Cloud AI is disabled."
        if self.cloud_limit_disabled_flag.exists():
            return True, "Local cloud-call limit is disabled."
        limit = int(os.getenv("ORION_MAX_CLOUD_CALLS_PER_DAY", os.getenv("JARVIS_MAX_CLOUD_CALLS_PER_DAY", "100")))
        since = time.time() - 86400
        with _lock, self._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM cloud_usage WHERE created >= ?", (since,)).fetchone()[0]
        return (count < limit, "allowed" if count < limit else f"Daily cloud-call limit of {limit} reached.")

    def record_cloud(self, purpose: str, model: str, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        with _lock, self._connect() as db:
            db.execute(
                "INSERT INTO cloud_usage(purpose,model,input_tokens,output_tokens,created) VALUES(?,?,?,?,?)",
                (purpose, model, input_tokens, output_tokens, time.time()),
            )
        self.write_status()

    def record_cloud_event(self, purpose: str, model: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
        with _lock, self._connect() as db:
            db.execute(
                "INSERT INTO cloud_usage(purpose,model,input_tokens,output_tokens,created) VALUES(?,?,?,?,?)",
                (purpose, model, int(input_tokens), int(output_tokens), time.time()),
            )
        self.write_status()

    @staticmethod
    def risk_for(tool: str) -> str:
        if tool in {
            "create_email_draft", "git_commit", "git_commit_and_push", "git_push",
            "desktop_action", "desktop_accessibility_set", "desktop_accessibility_press",
            "install_application",
            "blender_create_project", "freecad_create_project",
            "openscad_create_project", "resolve_create_project",
        }:
            return "consequential"
        if tool in {"desktop_window_arrange", "desktop_window_restore"}:
            return "reversible"
        if tool.startswith(("create_", "todoist_", "home_assistant_", "quit_", "spotify_create_", "google_create_")):
            return "reversible"
        if tool == "orion_teach_workflow":
            return "reversible"
        if tool in {"codex_generate", "generation_cancel"}:
            return "consequential"
        return "read_only"

    def summary(self) -> dict:
        with _lock, self._connect() as db:
            counts = {
                "memories": db.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
                "documents": db.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                "workflows": db.execute("SELECT COUNT(*) FROM workflows WHERE enabled=1").fetchone()[0],
                "queued_jobs": db.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0],
                "task_history": db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
                "capabilities": db.execute("SELECT COUNT(*) FROM capabilities WHERE available=1").fetchone()[0],
                "capability_families_available": db.execute("SELECT COUNT(*) FROM capabilities WHERE name LIKE 'family:%' AND available=1").fetchone()[0],
                "capability_families_total": db.execute("SELECT COUNT(*) FROM capabilities WHERE name LIKE 'family:%'").fetchone()[0],
                "cloud_calls_24h": db.execute(
                    "SELECT COUNT(*) FROM cloud_usage WHERE created >= ?", (time.time() - 86400,)
                ).fetchone()[0],
                "active_project": db.execute(
                    "SELECT repository FROM project_sessions WHERE status='active' ORDER BY updated DESC LIMIT 1"
                ).fetchone(),
            }
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "world_facts" in tables:
                counts.update({
                    "world_facts": db.execute("SELECT COUNT(*) FROM world_facts").fetchone()[0],
                    "active_goals": db.execute("SELECT COUNT(*) FROM goals WHERE status IN ('active','awaiting_input')").fetchone()[0],
                    "layered_memories": db.execute("SELECT COUNT(*) FROM layered_memory").fetchone()[0],
                    "adapters": db.execute("SELECT COUNT(*) FROM adapters WHERE available=1").fetchone()[0],
                    "monitors": db.execute("SELECT COUNT(*) FROM event_rules WHERE enabled=1").fetchone()[0],
                    "replay_turns": db.execute("SELECT COUNT(*) FROM replay_turns").fetchone()[0],
                })
        counts["active_project"] = counts["active_project"][0] if counts["active_project"] else ""
        counts["cloud_base_limit"] = int(os.getenv("ORION_MAX_CLOUD_CALLS_PER_DAY", os.getenv("JARVIS_MAX_CLOUD_CALLS_PER_DAY", "100")))
        counts["cloud_limit_enabled"] = not self.cloud_limit_disabled_flag.exists()
        allowed, reason = self.cloud_allowed()
        return {"ok": True, **counts, "cloud_allowed": allowed, "cloud_policy": reason}

    def write_status(self) -> None:
        try:
            data = self.summary() if self.database.exists() else {"ok": True}
            temporary = self.status_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({**data, "updated": time.time()}), encoding="utf-8")
            temporary.replace(self.status_path)
        except (OSError, sqlite3.Error):
            pass


_platform: AgentPlatform | None = None


def platform() -> AgentPlatform:
    global _platform
    if _platform is None:
        _platform = AgentPlatform()
    return _platform


def initialize_platform() -> AgentPlatform:
    agent = platform()
    local = {
        "mac_control": (True, "Native macOS tools"),
        "persistent_memory": (True, str(agent.database)),
        "workflow_engine": (True, "Local SQLite queue"),
        "world_model": (True, "Observed state with source, confidence, and freshness"),
        "goal_supervisor": (True, "Persistent goals, prerequisites, and outcomes"),
        "layered_memory": (True, "Working, episodic, semantic, and procedural memory"),
        "event_monitor": (True, "Local battery, disk, and scheduled-work monitoring"),
        "replay_diagnostics": (True, "Sanitized request routing and outcome replay"),
        "adapter_registry": (True, "Native, semantic, API, and cloud capability registry"),
        "intelligence_router": (True, "Local-first routing with bounded cloud escalation"),
        "codex_worker": (
            bool(shutil.which("codex") or Path("/Applications/ChatGPT.app/Contents/Resources/codex").exists()),
            "Asynchronous workspace-write code generation",
        ),
        "local_transcription": (
            os.getenv("ORION_LOCAL_TRANSCRIPTION", os.getenv("JARVIS_LOCAL_TRANSCRIPTION", "1")) == "1" and importlib.util.find_spec("mlx_whisper") is not None,
            os.getenv("ORION_LOCAL_TRANSCRIBE_MODEL", os.getenv("JARVIS_LOCAL_TRANSCRIBE_MODEL", "mlx-community/whisper-tiny")),
        ),
        "local_speech": (os.getenv("ORION_LOCAL_SPEECH", os.getenv("JARVIS_LOCAL_SPEECH", "1")) == "1", "Built-in macOS voice"),
        "openai": (bool(os.getenv("OPENAI_API_KEY")), "Cloud escalation"),
        "spotify": (bool(os.getenv("SPOTIPY_CLIENT_ID") and os.getenv("SPOTIPY_CLIENT_SECRET")), "Spotify API"),
        "todoist": (bool(os.getenv("TODOIST_API_TOKEN")), "Todoist API"),
        "home_assistant": (bool(os.getenv("HOME_ASSISTANT_URL") and os.getenv("HOME_ASSISTANT_TOKEN")), "Home Assistant API"),
    }
    for name, (available, detail) in local.items():
        agent.register_capability(name, "integration" if name not in {"persistent_memory", "workflow_engine"} else "agent", available, detail)
    try:
        import capability_families
        for key, family in capability_families.families().items():
            detail = family.description if family.available else family.prerequisite
            agent.register_capability(f"family:{key}", "capability_family", family.available, detail)
    except Exception as exc:
        diagnostics.event("capability_family_registration_failed", level="warning", error=str(exc))
    roots_value = os.getenv("ORION_INDEX_ROOTS", os.getenv("JARVIS_INDEX_ROOTS", ""))
    roots = [Path(value).expanduser() for value in roots_value.split(os.pathsep) if value.strip()]
    if roots:
        agent.index_paths(roots, maximum_files=int(os.getenv("ORION_INDEX_MAX_FILES", os.getenv("JARVIS_INDEX_MAX_FILES", "500"))))
    agent.write_status()
    return agent
