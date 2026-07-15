"""ORION's local operating kernel: state, goals, memory, events, adapters, and replay."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import diagnostics


RUNTIME = Path(os.getenv("ORION_RUNTIME_DIR") or os.getenv("JARVIS_RUNTIME_DIR") or Path.cwd() / ".runtime")


class IntelligenceRouter:
    """Choose the cheapest capable reasoning lane before any model call."""

    @staticmethod
    def route(request: str) -> dict[str, Any]:
        text = request.lower()
        consequential = any(word in text for word in ("commit", "push", "send", "submit", "purchase", "delete"))
        visual = any(word in text for word in ("screen", "click", "what do you see", "visually"))
        current = any(word in text for word in ("latest", "today", "current news", "right now"))
        known_local = any(word in text for word in (
            "open ", "close ", "volume", "spotify", "project status", "commit", "push",
            "reminder", "calendar", "note", "workspace", "battery", "workflow",
        ))
        if visual:
            lane, reason = "local_semantic_then_vision", "Accessibility and OCR precede cloud vision"
        elif current:
            lane, reason = "cloud_research", "Fresh external information is required"
        elif known_local:
            lane, reason = "local_workflow", "A deterministic adapter or workflow can handle this"
        else:
            lane, reason = "hybrid_reasoning", "Conversation may need bounded cloud reasoning"
        return {"lane": lane, "reason": reason, "consequential": consequential}


class OrionKernel:
    MEMORY_LAYERS = {"working", "episodic", "semantic", "procedural"}

    def __init__(self, database: Path | None = None) -> None:
        self.database = database or RUNTIME / "agent.db"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.replay_path = self.database.parent / "replay.jsonl"
        self._stop = threading.Event()
        self._monitor: threading.Thread | None = None
        self._lock = threading.RLock()
        self._initialize()
        self.register_default_adapters()

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
        with self._lock, self._connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS world_facts (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, source TEXT NOT NULL,
                    confidence REAL NOT NULL, observed REAL NOT NULL, expires REAL
                );
                CREATE TABLE IF NOT EXISTS layered_memory (
                    id INTEGER PRIMARY KEY, layer TEXT NOT NULL, key TEXT NOT NULL,
                    value TEXT NOT NULL, source TEXT NOT NULL, confidence REAL NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL, expires REAL,
                    UNIQUE(layer,key)
                );
                CREATE TABLE IF NOT EXISTS goals (
                    id TEXT PRIMARY KEY, request TEXT NOT NULL, objective TEXT NOT NULL,
                    status TEXT NOT NULL, risk TEXT NOT NULL, context TEXT NOT NULL,
                    success_criteria TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS goal_steps (
                    id INTEGER PRIMARY KEY, goal_id TEXT NOT NULL, position INTEGER NOT NULL,
                    description TEXT NOT NULL, status TEXT NOT NULL, evidence TEXT NOT NULL,
                    updated REAL NOT NULL, UNIQUE(goal_id,position)
                );
                CREATE TABLE IF NOT EXISTS adapters (
                    name TEXT PRIMARY KEY, category TEXT NOT NULL, mode TEXT NOT NULL,
                    available INTEGER NOT NULL, capabilities TEXT NOT NULL, checked REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS event_rules (
                    name TEXT PRIMARY KEY, event_type TEXT NOT NULL, condition TEXT NOT NULL,
                    action TEXT NOT NULL, enabled INTEGER NOT NULL, cooldown REAL NOT NULL,
                    last_fired REAL NOT NULL DEFAULT 0, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS kernel_events (
                    id INTEGER PRIMARY KEY, event_type TEXT NOT NULL, payload TEXT NOT NULL,
                    handled INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS replay_turns (
                    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    request TEXT NOT NULL, response TEXT NOT NULL, route TEXT NOT NULL,
                    goal_id TEXT NOT NULL, outcome TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflows (
                    name TEXT PRIMARY KEY, definition TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY, workflow TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL, run_after REAL NOT NULL, created REAL NOT NULL,
                    updated REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_world_expires ON world_facts(expires);
                CREATE INDEX IF NOT EXISTS idx_memory_layer_updated ON layered_memory(layer,updated DESC);
                CREATE INDEX IF NOT EXISTS idx_goals_status_updated ON goals(status,updated DESC);
                CREATE INDEX IF NOT EXISTS idx_kernel_events_created ON kernel_events(created DESC);
            """)
        self._install_default_rules()

    def observe(self, key: str, value: Any, source: str, confidence: float = 1.0, ttl: float | None = 300) -> dict:
        now = time.time()
        expires = now + ttl if ttl else None
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO world_facts(key,value,source,confidence,observed,expires) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,source=excluded.source,"
                "confidence=excluded.confidence,observed=excluded.observed,expires=excluded.expires",
                (key, json.dumps(value, default=str), source, max(0, min(float(confidence), 1)), now, expires),
            )
        return {"ok": True, "key": key, "observed": now}

    def world_snapshot(self, prefix: str = "", limit: int = 40) -> dict:
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM world_facts WHERE expires IS NOT NULL AND expires < ?", (now,))
            if prefix:
                rows = db.execute(
                    "SELECT * FROM world_facts WHERE key LIKE ? ORDER BY observed DESC LIMIT ?",
                    (f"{prefix}%", limit),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM world_facts ORDER BY observed DESC LIMIT ?", (limit,)).fetchall()
        facts = []
        for row in rows:
            item = dict(row)
            try: item["value"] = json.loads(item["value"])
            except (ValueError, TypeError): pass
            facts.append(item)
        return {"ok": True, "facts": facts, "captured": now}

    def remember(self, layer: str, key: str, value: Any, source: str = "orion", confidence: float = 1.0, ttl: float | None = None) -> dict:
        if layer not in self.MEMORY_LAYERS:
            return {"ok": False, "error": f"Unknown memory layer: {layer}"}
        now = time.time(); expires = now + ttl if ttl else None
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO layered_memory(layer,key,value,source,confidence,created,updated,expires) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(layer,key) DO UPDATE SET value=excluded.value,source=excluded.source,"
                "confidence=excluded.confidence,updated=excluded.updated,expires=excluded.expires",
                (layer, key, json.dumps(value, default=str), source, confidence, now, now, expires),
            )
        return {"ok": True, "layer": layer, "key": key}

    def recall(self, query: str, layers: list[str] | None = None, limit: int = 8) -> dict:
        layers = [layer for layer in (layers or list(self.MEMORY_LAYERS)) if layer in self.MEMORY_LAYERS]
        if not layers: return {"ok": True, "matches": []}
        now = time.time(); pattern = f"%{query.strip().lower()}%"
        placeholders = ",".join("?" for _ in layers)
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM layered_memory WHERE expires IS NOT NULL AND expires < ?", (now,))
            rows = db.execute(
                f"SELECT layer,key,value,source,confidence,updated FROM layered_memory "
                f"WHERE layer IN ({placeholders}) AND (lower(key) LIKE ? OR lower(value) LIKE ?) "
                "ORDER BY confidence DESC,updated DESC LIMIT ?", (*layers, pattern, pattern, limit),
            ).fetchall()
        matches = []
        for row in rows:
            item = dict(row)
            try: item["value"] = json.loads(item["value"])
            except (ValueError, TypeError): pass
            matches.append(item)
        return {"ok": True, "matches": matches}

    def create_goal(self, request: str, objective: str | None = None, risk: str = "low", success_criteria: list[str] | None = None) -> dict:
        goal_id = uuid.uuid4().hex
        now = time.time(); criteria = success_criteria or ["Requested outcome is observed and verified"]
        context = {"references": {}, "authorization": {"request": request}}
        with self._lock, self._connect() as db:
            db.execute("UPDATE goals SET status='paused',updated=? WHERE status IN ('active','awaiting_input')", (now,))
            db.execute(
                "INSERT INTO goals(id,request,objective,status,risk,context,success_criteria,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
                (goal_id, request[:4000], (objective or request)[:4000], "active", risk, json.dumps(context), json.dumps(criteria), now, now),
            )
        return {"ok": True, "goal_id": goal_id, "status": "active", "objective": objective or request}

    def active_goal(self) -> dict:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM goals WHERE status IN ('active','awaiting_input') ORDER BY updated DESC LIMIT 1").fetchone()
            steps = db.execute("SELECT * FROM goal_steps WHERE goal_id=? ORDER BY position", (row["id"],)).fetchall() if row else []
        return {"ok": True, "goal": dict(row) if row else None, "steps": [dict(step) for step in steps]}

    def update_goal(self, goal_id: str, status: str, evidence: dict | None = None) -> dict:
        allowed = {"active", "awaiting_input", "completed", "failed", "paused", "cancelled"}
        if status not in allowed: return {"ok": False, "error": "Invalid goal status"}
        with self._lock, self._connect() as db:
            cursor = db.execute("UPDATE goals SET status=?,updated=? WHERE id=?", (status, time.time(), goal_id))
        if evidence is not None:
            self.remember("episodic", f"goal:{goal_id}:outcome", evidence, source="goal_supervisor", ttl=86400 * 90)
        return {"ok": bool(cursor.rowcount), "goal_id": goal_id, "status": status}

    def set_goal_steps(self, goal_id: str, steps: list[str]) -> dict:
        with self._lock, self._connect() as db:
            for position, description in enumerate(steps):
                db.execute(
                    "INSERT INTO goal_steps(goal_id,position,description,status,evidence,updated) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(goal_id,position) DO UPDATE SET description=excluded.description,updated=excluded.updated",
                    (goal_id, position, description[:1000], "pending", "{}", time.time()),
                )
        return {"ok": True, "goal_id": goal_id, "steps": len(steps)}

    def adopt_plan(self, objective: str, steps: list[str], success_criteria: list[str], risk: str) -> dict:
        active = self.active_goal().get("goal")
        if not active:
            return {"ok": False, "error": "No active goal"}
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE goals SET objective=?,risk=?,success_criteria=?,updated=? WHERE id=?",
                (objective[:4000], risk, json.dumps(success_criteria), time.time(), active["id"]),
            )
        self.set_goal_steps(active["id"], steps)
        return {"ok": True, "goal_id": active["id"], "steps": len(steps)}

    def register_adapter(self, name: str, category: str, mode: str, capabilities: list[str], available: bool = True) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO adapters(name,category,mode,available,capabilities,checked) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET mode=excluded.mode,available=excluded.available,"
                "capabilities=excluded.capabilities,checked=excluded.checked",
                (name, category, mode, int(available), json.dumps(capabilities), time.time()),
            )

    def register_default_adapters(self) -> None:
        definitions = {
            "macOS": ("system", "native", ["applications", "windows", "power", "notifications"]),
            "Accessibility": ("desktop", "semantic", ["inspect", "press", "fill", "window_state"]),
            "Git": ("development", "native", ["status", "commit", "push", "verify"]),
            "Apple Apps": ("productivity", "native", ["calendar", "reminders", "notes", "mail", "contacts"]),
            "Spotify": ("media", "api", ["library", "playback", "playlists"]),
            "Todoist": ("productivity", "api", ["tasks"]),
            "Home Assistant": ("environment", "api", ["devices", "scenes", "climate"]),
            "OpenAI": ("reasoning", "cloud", ["planning", "research", "vision", "fallback_transcription"]),
            "Codex": ("generation", "worker", ["code_generation", "repository_editing", "testing"]),
        }
        for name, (category, mode, capabilities) in definitions.items():
            self.register_adapter(name, category, mode, capabilities)
        try:
            import mac_tools
            categories = {
                "Blender": "creative_engineering",
                "FreeCAD": "engineering",
                "OpenSCAD": "engineering",
                "DaVinci Resolve": "creative",
            }
            for application in mac_tools.workspace_applications():
                self.register_adapter(
                    application["name"], categories.get(application["name"], "application"),
                    "native_workspace", application["capabilities"],
                )
        except Exception as exc:
            diagnostics.event("workspace_application_registration_failed", level="warning", error=str(exc))

    def adapters(self) -> dict:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT * FROM adapters ORDER BY category,name").fetchall()
        return {"ok": True, "adapters": [dict(row) for row in rows]}

    def _install_default_rules(self) -> None:
        rules = [
            ("low_battery", "system.health", {"battery_below": 15, "unplugged": True}, "notify", 900),
            ("low_disk", "system.health", {"disk_free_gb_below": 10}, "notify", 3600),
            ("due_job", "workflow.due", {}, "notify", 300),
        ]
        with self._lock, self._connect() as db:
            for name, event_type, condition, action, cooldown in rules:
                db.execute(
                    "INSERT OR IGNORE INTO event_rules(name,event_type,condition,action,enabled,cooldown,updated) VALUES(?,?,?,?,1,?,?)",
                    (name, event_type, json.dumps(condition), action, cooldown, time.time()),
                )

    def emit(self, event_type: str, payload: dict) -> dict:
        with self._lock, self._connect() as db:
            cursor = db.execute(
                "INSERT INTO kernel_events(event_type,payload,created) VALUES(?,?,?)",
                (event_type, json.dumps(payload, default=str), time.time()),
            )
        diagnostics.event("kernel_event", event_type=event_type, payload=payload)
        return {"ok": True, "event_id": cursor.lastrowid}

    def refresh_world(self) -> None:
        try:
            import psutil
            battery = psutil.sensors_battery()
            disk = psutil.disk_usage("/")
            system = {
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_free_gb": round(disk.free / 1_073_741_824, 1),
                "battery_percent": round(battery.percent, 1) if battery else None,
                "plugged_in": bool(battery.power_plugged) if battery else None,
            }
            self.observe("system.health", system, "psutil", ttl=45)
            if system["battery_percent"] is not None and system["battery_percent"] < 15 and not system["plugged_in"]:
                self._fire_rule("low_battery", system)
            if system["disk_free_gb"] < 10: self._fire_rule("low_disk", system)
        except Exception as exc:
            diagnostics.event("world_refresh_failed", level="warning", error=str(exc))

    def _fire_rule(self, name: str, payload: dict) -> None:
        now = time.time()
        with self._lock, self._connect() as db:
            rule = db.execute("SELECT * FROM event_rules WHERE name=? AND enabled=1", (name,)).fetchone()
            if not rule or now - float(rule["last_fired"]) < float(rule["cooldown"]): return
            db.execute("UPDATE event_rules SET last_fired=?,updated=? WHERE name=?", (now, now, name))
        self.emit("rule.fired", {"rule": name, **payload})
        try:
            import mac_tools
            message = "Battery is below 15 percent." if name == "low_battery" else "Your Mac has less than 10 GB of free disk space."
            mac_tools.notify("ORION", message)
        except Exception:
            pass

    def _monitor_loop(self) -> None:
        while not self._stop.wait(30):
            self.refresh_world()
            self._observe_due_jobs()
            try:
                import generation
                updates = generation.poll_jobs()
                if updates:
                    self.observe("generation.latest", updates[-1], "generation_worker", ttl=86400)
                    self._publish_status()
            except Exception as exc:
                diagnostics.event("generation_monitor_failed", level="warning", error=str(exc))
            try:
                import app_installer
                updates = app_installer.poll_jobs()
                if updates:
                    self.observe("installation.latest", updates[-1], "installation_supervisor", ttl=86400)
                    self._publish_status()
                    diagnostics.event("installation_supervisor_observed", **updates[-1])
            except Exception as exc:
                diagnostics.event("installation_monitor_failed", level="warning", error=str(exc))

    def _observe_due_jobs(self) -> None:
        try:
            with self._lock, self._connect() as db:
                rows = db.execute("SELECT id,workflow,payload FROM jobs WHERE status='queued' AND run_after<=?", (time.time(),)).fetchall()
            for row in rows:
                self.emit("workflow.due", {"job_id": row["id"], "workflow": row["workflow"]})
                with self._lock, self._connect() as db:
                    db.execute("UPDATE jobs SET status='ready',updated=? WHERE id=? AND status='queued'", (time.time(), row["id"]))
                try:
                    import mac_tools
                    mac_tools.notify("ORION", f"Scheduled workflow {row['workflow']} is ready.")
                except Exception:
                    pass
        except sqlite3.Error:
            pass

    def start_monitor(self) -> None:
        if self._monitor and self._monitor.is_alive(): return
        self._stop.clear(); self.refresh_world()
        self._monitor = threading.Thread(target=self._monitor_loop, name="orion-world-monitor", daemon=True)
        self._monitor.start()

    def stop_monitor(self) -> None:
        self._stop.set()

    def before_request(self, request: str, request_id: str, session_id: str) -> dict:
        route = IntelligenceRouter.route(request)
        active = self.active_goal().get("goal")
        referential = len(request.split()) <= 14 and any(word in request.lower() for word in ("it", "that", "continue", "yes", "again", "there"))
        if not active or not referential:
            goal = self.create_goal(request, risk="consequential" if route["consequential"] else "low")
            goal_id = goal["goal_id"]
        else:
            goal_id = active["id"]
            with self._lock, self._connect() as db:
                db.execute("UPDATE goals SET updated=? WHERE id=?", (time.time(), goal_id))
        self.remember("working", f"session:{session_id}:last_request", request, source="voice_session", ttl=3600)
        self.observe("interaction.active_goal", {"goal_id": goal_id, "request": request}, "goal_supervisor", ttl=3600)
        context = self.context_for(request)
        capability_plan = context.get("capability_plan", {})
        if capability_plan:
            team = capability_plan.get("available_families", []) + capability_plan.get("blocked_families", [])
            self.observe("interaction.capability_team", {"goal_id": goal_id, "families": team}, "objective_compiler", ttl=3600)
            self.remember("working", f"goal:{goal_id}:capability_team", capability_plan, source="objective_compiler", ttl=3600)
        return {"goal_id": goal_id, "route": route, "context": context}

    def after_response(self, request: str, response: str, request_id: str, session_id: str, goal_id: str, route: dict, outcome: str = "completed") -> None:
        status = "awaiting_input" if response.rstrip().endswith("?") else outcome
        if status not in {"completed", "awaiting_input", "failed", "paused"}: status = "completed"
        self.update_goal(goal_id, status, {"request": request, "response": response, "request_id": request_id})
        if status == "completed":
            with self._lock, self._connect() as db:
                db.execute(
                    "UPDATE goal_steps SET status='completed',evidence=?,updated=? WHERE goal_id=? AND status='pending'",
                    (json.dumps({"request_id": request_id, "response": response[:500]}), time.time(), goal_id),
                )
        self.remember("episodic", f"turn:{request_id}", {"request": request, "response": response, "outcome": status}, source="conversation", ttl=86400 * 90)
        self.record_replay(session_id, request_id, request, response, route, goal_id, status)
        self._publish_status()

    def context_for(self, request: str) -> dict:
        words = [word for word in re.findall(r"[a-z0-9_-]{4,}", request.lower()) if word not in {"please", "would", "could"}]
        memories = self.recall(" ".join(words[:4]) or request, limit=6)["matches"]
        workflow_matches = []
        request_lower = request.lower()
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT name,definition FROM workflows WHERE enabled=1 ORDER BY updated DESC LIMIT 40").fetchall()
        for row in rows:
            try:
                definition = json.loads(row["definition"])
            except (ValueError, TypeError):
                continue
            trigger = str(definition.get("trigger", "")) if isinstance(definition, dict) else ""
            if trigger and (trigger.lower() in request_lower or request_lower in trigger.lower()):
                workflow_matches.append({"name": row["name"], "definition": definition})
        try:
            import capability_families
            capability_plan = capability_families.compile_objective(request)
        except Exception:
            capability_plan = {}
        return {
            "active_goal": self.active_goal(),
            "world": self.world_snapshot(limit=12)["facts"],
            "memory": memories,
            "routing": IntelligenceRouter.route(request),
            "matched_workflows": workflow_matches[:3],
            "capability_plan": capability_plan,
        }

    def record_replay(self, session_id: str, request_id: str, request: str, response: str, route: dict, goal_id: str, outcome: str) -> None:
        safe_request = str(diagnostics.redact(request))[:4000]
        safe_response = str(diagnostics.redact(response))[:6000]
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO replay_turns(session_id,request_id,request,response,route,goal_id,outcome,created) VALUES(?,?,?,?,?,?,?,?)",
                (session_id, request_id, safe_request, safe_response, json.dumps(route), goal_id, outcome, time.time()),
            )
        try:
            with self.replay_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"session_id": session_id, "request_id": request_id, "request": safe_request, "response": safe_response, "route": route, "goal_id": goal_id, "outcome": outcome, "time": time.time()}) + "\n")
        except OSError:
            pass

    def teach_workflow(self, name: str, trigger: str, steps: list[str]) -> dict:
        if not name.strip() or not steps: return {"ok": False, "error": "A workflow needs a name and at least one step."}
        definition = [{"description": step, "status": "learned"} for step in steps]
        try:
            with self._lock, self._connect() as db:
                db.execute(
                    "INSERT INTO workflows(name,definition,updated) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET definition=excluded.definition,updated=excluded.updated",
                    (name.strip(), json.dumps({"trigger": trigger, "steps": definition}), time.time()),
                )
            self.remember("procedural", f"workflow:{name.strip()}", {"trigger": trigger, "steps": steps}, source="user_taught")
            self._publish_status()
            return {"ok": True, "name": name.strip(), "trigger": trigger, "steps": len(steps)}
        except sqlite3.Error as exc:
            return {"ok": False, "error": str(exc)}

    def workflows(self) -> dict:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT name,definition,enabled,updated FROM workflows ORDER BY updated DESC").fetchall()
        workflows = []
        for row in rows:
            item = dict(row)
            try: item["definition"] = json.loads(item["definition"])
            except (ValueError, TypeError): pass
            workflows.append(item)
        return {"ok": True, "workflows": workflows}

    def status(self) -> dict:
        with self._lock, self._connect() as db:
            counts = {
                "world_facts": db.execute("SELECT COUNT(*) FROM world_facts").fetchone()[0],
                "active_goals": db.execute("SELECT COUNT(*) FROM goals WHERE status IN ('active','awaiting_input')").fetchone()[0],
                "memories": db.execute("SELECT COUNT(*) FROM layered_memory").fetchone()[0],
                "adapters": db.execute("SELECT COUNT(*) FROM adapters WHERE available=1").fetchone()[0],
                "event_rules": db.execute("SELECT COUNT(*) FROM event_rules WHERE enabled=1").fetchone()[0],
                "replay_turns": db.execute("SELECT COUNT(*) FROM replay_turns").fetchone()[0],
            }
        return {"ok": True, "identity": "ORION", "expansion": "One Really Intelligent Operating Network", **counts, "active_goal": self.active_goal()}

    def _publish_status(self) -> None:
        if self.database.resolve() != (RUNTIME / "agent.db").resolve():
            return
        try:
            from agent_platform import platform
            platform().write_status()
        except Exception:
            pass


_kernel: OrionKernel | None = None


def kernel() -> OrionKernel:
    global _kernel
    if _kernel is None: _kernel = OrionKernel()
    return _kernel


def initialize_kernel() -> OrionKernel:
    instance = kernel(); instance.start_monitor()
    instance.observe("agent.identity", {"name": "ORION", "expansion": "One Really Intelligent Operating Network"}, "configuration", ttl=None)
    return instance
