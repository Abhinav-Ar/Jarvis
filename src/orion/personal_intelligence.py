"""Private, local-first personal timeline and relationship recall for ORION."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any


RUNTIME = Path(os.getenv("ORION_RUNTIME_DIR") or os.getenv("JARVIS_RUNTIME_DIR") or Path.cwd() / ".runtime")
DATABASE = RUNTIME / "agent.db"
MESSAGES_DATABASE = Path.home() / "Library/Messages/chat.db"
APPLE_EPOCH = 978307200
STOPWORDS = {
    "about", "after", "again", "alex", "before", "could", "going", "have", "just",
    "message", "said", "saying", "she", "should", "tell", "text", "that", "the", "they",
    "this", "what", "when", "where", "with", "would", "you", "your", "was", "were", "will",
}


def _apple_timestamp(value: Any) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if abs(number) > 10_000_000_000:
        number /= 1_000_000_000
    return number + APPLE_EPOCH if number < APPLE_EPOCH else number


def _plain_attributed_body(value: Any) -> str:
    if not value:
        return ""
    data = bytes(value) if not isinstance(value, bytes) else value
    candidates = re.findall(rb"[\x20-\x7e]{4,}", data)
    ignored = (b"NSString", b"NSDictionary", b"NSAttributed", b"__kIM", b"streamtyped")
    strings = [item.decode("utf-8", "ignore").strip() for item in candidates if not any(token in item for token in ignored)]
    strings = [item for item in strings if re.search(r"[A-Za-z0-9]", item)]
    return max(strings, key=len, default="")[:12000]


def _normalize_identity(value: str) -> str:
    value = value.strip().lower()
    if "@" in value:
        return value
    digits = re.sub(r"\D", "", value)
    return digits[-10:] if len(digits) >= 10 else digits or value


class PersonalIntelligence:
    """Normalized personal events with source-aware, time-aware local retrieval."""

    def __init__(self, database: Path | None = None, messages_database: Path | None = None) -> None:
        self.database = database or DATABASE
        self.messages_database = messages_database or MESSAGES_DATABASE
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS people (
                    id INTEGER PRIMARY KEY, display_name TEXT NOT NULL,
                    relationship TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
                    updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS person_aliases (
                    alias TEXT PRIMARY KEY COLLATE NOCASE, person_id INTEGER NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user', updated REAL NOT NULL,
                    FOREIGN KEY(person_id) REFERENCES people(id)
                );
                CREATE TABLE IF NOT EXISTS person_identities (
                    identity TEXT PRIMARY KEY, person_id INTEGER NOT NULL,
                    kind TEXT NOT NULL, source TEXT NOT NULL, updated REAL NOT NULL,
                    FOREIGN KEY(person_id) REFERENCES people(id)
                );
                CREATE TABLE IF NOT EXISTS personal_events (
                    id INTEGER PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL,
                    occurred REAL NOT NULL, direction TEXT NOT NULL DEFAULT '',
                    sender TEXT NOT NULL DEFAULT '', participants TEXT NOT NULL DEFAULT '[]',
                    channel TEXT NOT NULL DEFAULT '', content TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}', indexed REAL NOT NULL,
                    UNIQUE(source, external_id)
                );
                CREATE TABLE IF NOT EXISTS connector_state (
                    source TEXT PRIMARY KEY, status TEXT NOT NULL, detail TEXT NOT NULL,
                    last_sync REAL, item_count INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_personal_events_occurred ON personal_events(occurred DESC);
                CREATE INDEX IF NOT EXISTS idx_personal_events_source ON personal_events(source,occurred DESC);
                CREATE INDEX IF NOT EXISTS idx_person_alias_person ON person_aliases(person_id);
                CREATE INDEX IF NOT EXISTS idx_person_identity_person ON person_identities(person_id);
            """)

    def _set_connector(self, source: str, status: str, detail: str, *, count: int = 0, synced: bool = False) -> None:
        now = time.time()
        with self._connect() as db:
            db.execute(
                "INSERT INTO connector_state(source,status,detail,last_sync,item_count,updated) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(source) DO UPDATE SET status=excluded.status,detail=excluded.detail,"
                "last_sync=COALESCE(excluded.last_sync,connector_state.last_sync),"
                "item_count=CASE WHEN excluded.item_count>0 THEN excluded.item_count ELSE connector_state.item_count END,"
                "updated=excluded.updated",
                (source, status, detail, now if synced else None, count, now),
            )

    def remember_person(self, name: str, *, aliases: list[str] | None = None,
                        identities: list[tuple[str, str]] | None = None,
                        relationship: str = "", source: str = "user") -> dict:
        name = name.strip()
        if not name:
            return {"ok": False, "error": "A person needs a name."}
        now = time.time()
        with self._connect() as db:
            existing = db.execute(
                "SELECT p.id FROM people p LEFT JOIN person_aliases a ON a.person_id=p.id "
                "WHERE lower(p.display_name)=lower(?) OR lower(a.alias)=lower(?) LIMIT 1", (name, name),
            ).fetchone()
            if existing:
                person_id = int(existing["id"])
                db.execute(
                    "UPDATE people SET relationship=CASE WHEN ?<>'' THEN ? ELSE relationship END,updated=? WHERE id=?",
                    (relationship, relationship, now, person_id),
                )
            else:
                person_id = int(db.execute(
                    "INSERT INTO people(display_name,relationship,updated) VALUES(?,?,?)",
                    (name, relationship, now),
                ).lastrowid)
            for alias in [name, *(aliases or [])]:
                if alias.strip():
                    db.execute(
                        "INSERT INTO person_aliases(alias,person_id,source,updated) VALUES(?,?,?,?) "
                        "ON CONFLICT(alias) DO UPDATE SET person_id=excluded.person_id,source=excluded.source,updated=excluded.updated",
                        (alias.strip(), person_id, source, now),
                    )
            for kind, identity in identities or []:
                normalized = _normalize_identity(identity)
                if normalized:
                    db.execute(
                        "INSERT INTO person_identities(identity,person_id,kind,source,updated) VALUES(?,?,?,?,?) "
                        "ON CONFLICT(identity) DO UPDATE SET person_id=excluded.person_id,kind=excluded.kind,source=excluded.source,updated=excluded.updated",
                        (normalized, person_id, kind, source, now),
                    )
        return {"ok": True, "person_id": person_id, "name": name}

    def sync_contact(self, name: str) -> dict:
        """Resolve a named Apple Contact to message identities without opening Contacts."""
        script = r'''on run argv
tell application "Contacts"
  set matches to every person whose name contains item 1 of argv
  set output to ""
  repeat with p in matches
    set output to output & name of p & "\t"
    repeat with e in emails of p
      set output to output & "email:" & value of e & "\t"
    end repeat
    repeat with ph in phones of p
      set output to output & "phone:" & value of ph & "\t"
    end repeat
    set output to output & linefeed
  end repeat
  return output
end tell
end run'''
        try:
            result = subprocess.run(
                ["/usr/bin/osascript", "-e", script, name], capture_output=True, text=True, timeout=12,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": str(exc)}
        if result.returncode:
            return {"ok": False, "error": result.stderr.strip() or "Contacts access is unavailable."}
        matched = []
        for line in result.stdout.splitlines():
            fields = [field.strip() for field in line.split("\t") if field.strip()]
            if not fields:
                continue
            identities = []
            for field in fields[1:]:
                kind, _, value = field.partition(":")
                if value:
                    identities.append((kind, value))
            matched.append(self.remember_person(fields[0], aliases=[name], identities=identities, source="apple_contacts"))
        return {"ok": True, "matches": matched}

    def index_messages(self, *, limit: int = 10000, since_days: int = 730) -> dict:
        if not self.messages_database.exists():
            detail = "Messages database was not found on this Mac."
            self._set_connector("messages", "unavailable", detail)
            return {"ok": False, "source": "messages", "error": detail, "permission_required": False}
        try:
            source = sqlite3.connect(f"file:{self.messages_database}?mode=ro", uri=True, timeout=8)
            source.row_factory = sqlite3.Row
            threshold = (time.time() - APPLE_EPOCH - since_days * 86400) * 1_000_000_000
            rows = source.execute(
                "SELECT m.ROWID AS row_id,m.guid,m.text,m.attributedBody,m.date,m.is_from_me,"
                "h.id AS sender,c.chat_identifier,c.display_name "
                "FROM message m LEFT JOIN handle h ON h.ROWID=m.handle_id "
                "LEFT JOIN chat_message_join j ON j.message_id=m.ROWID "
                "LEFT JOIN chat c ON c.ROWID=j.chat_id WHERE m.date>=? "
                "ORDER BY m.date DESC LIMIT ?", (threshold, max(1, min(limit, 100000))),
            ).fetchall()
            source.close()
        except sqlite3.Error as exc:
            detail = "Messages needs Full Disk Access for ORION/Jarvis Menu before its local history can be searched."
            self._set_connector("messages", "permission_required", detail)
            return {"ok": False, "source": "messages", "error": detail, "detail": str(exc), "permission_required": True}
        now = time.time()
        indexed = 0
        seen: set[str] = set()
        with self._connect() as db:
            for row in rows:
                external_id = str(row["guid"] or row["row_id"])
                if external_id in seen:
                    continue
                seen.add(external_id)
                content = str(row["text"] or "").strip() or _plain_attributed_body(row["attributedBody"])
                if not content:
                    continue
                sender = "me" if row["is_from_me"] else str(row["sender"] or row["display_name"] or row["chat_identifier"] or "unknown")
                participants = [value for value in (row["sender"], row["display_name"], row["chat_identifier"]) if value]
                db.execute(
                    "INSERT INTO personal_events(source,external_id,occurred,direction,sender,participants,channel,content,metadata,indexed) "
                    "VALUES('messages',?,?,?,?,?,?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET "
                    "occurred=excluded.occurred,direction=excluded.direction,sender=excluded.sender,participants=excluded.participants,"
                    "channel=excluded.channel,content=excluded.content,metadata=excluded.metadata,indexed=excluded.indexed",
                    (external_id, _apple_timestamp(row["date"]), "outgoing" if row["is_from_me"] else "incoming",
                     sender, json.dumps(participants), str(row["display_name"] or row["chat_identifier"] or "Messages"),
                     content[:12000], json.dumps({"row_id": row["row_id"]}), now),
                )
                indexed += 1
        self._set_connector("messages", "ready", "Local Apple Messages history is searchable.", count=indexed, synced=True)
        return {"ok": True, "source": "messages", "indexed": indexed}

    def index_discord_export(self, folder: str | Path | None = None, *, maximum_files: int = 200) -> dict:
        root_value = folder or os.getenv("ORION_DISCORD_EXPORT_DIR", "")
        root = Path(root_value).expanduser() if root_value else None
        if not root or not root.exists():
            detail = "Authorize a Discord data-export folder to enable private local recall."
            self._set_connector("discord", "authorization_required", detail)
            return {"ok": False, "source": "discord", "error": detail, "authorization_required": True}
        indexed = 0
        now = time.time()
        with self._connect() as db:
            for path in list(root.rglob("*.json"))[:maximum_files]:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                messages = payload.get("messages", []) if isinstance(payload, dict) else payload
                if not isinstance(messages, list):
                    continue
                for position, item in enumerate(messages):
                    if not isinstance(item, dict) or not str(item.get("content", "")).strip():
                        continue
                    stamp = item.get("timestamp") or item.get("Timestamp") or item.get("created_at")
                    try:
                        occurred = datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
                    except (TypeError, ValueError):
                        occurred = path.stat().st_mtime
                    author = item.get("author") or item.get("Author") or item.get("username") or "unknown"
                    if isinstance(author, dict):
                        author = author.get("global_name") or author.get("username") or author.get("name") or "unknown"
                    external_id = str(item.get("id") or item.get("ID") or f"{path}:{position}")
                    db.execute(
                        "INSERT INTO personal_events(source,external_id,occurred,direction,sender,participants,channel,content,metadata,indexed) "
                        "VALUES('discord',?,?,?,?,?,?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET "
                        "occurred=excluded.occurred,sender=excluded.sender,channel=excluded.channel,content=excluded.content,indexed=excluded.indexed",
                        (external_id, occurred, "", str(author), json.dumps([author]), path.parent.name,
                         str(item.get("content"))[:12000], json.dumps({"file": str(path)}), now),
                    )
                    indexed += 1
        self._set_connector("discord", "ready", "Authorized Discord export is searchable locally.", count=indexed, synced=True)
        return {"ok": True, "source": "discord", "indexed": indexed, "folder": str(root)}

    def connector_status(self) -> dict:
        with self._connect() as db:
            rows = {row["source"]: dict(row) for row in db.execute("SELECT * FROM connector_state").fetchall()}
        if "messages" not in rows:
            if not self.messages_database.exists():
                self._set_connector("messages", "unavailable", "Messages database was not found on this Mac.")
            else:
                try:
                    probe = sqlite3.connect(f"file:{self.messages_database}?mode=ro", uri=True, timeout=3)
                    probe.execute("SELECT 1 FROM message LIMIT 1").fetchone()
                    probe.close()
                    self._set_connector("messages", "ready", "Local read-only Apple Messages connector")
                except sqlite3.Error:
                    self._set_connector(
                        "messages", "permission_required",
                        "Enable Full Disk Access for Jarvis Menu.app to search Messages locally.",
                    )
        defaults = {
            "contacts": ("ready", "Apple Contacts identity resolver"),
            "discord": ("authorization_required", "Official bot access or an authorized Discord export is required"),
            "calendar": ("ready", "Apple Calendar actions are available"),
            "mail": ("draft_only", "Apple Mail can prepare drafts; sending always requires confirmation"),
        }
        for source, (status, detail) in defaults.items():
            if source not in rows:
                self._set_connector(source, status, detail)
        with self._connect() as db:
            rows = {row["source"]: dict(row) for row in db.execute("SELECT * FROM connector_state").fetchall()}
        return {"ok": True, "connectors": list(rows.values()), "privacy": "Personal content is indexed locally. Cloud context sharing is off by default."}

    def _identities_for(self, person: str) -> tuple[list[str], str]:
        if not person.strip():
            return [], ""
        with self._connect() as db:
            row = db.execute(
                "SELECT p.id,p.display_name FROM people p LEFT JOIN person_aliases a ON a.person_id=p.id "
                "WHERE lower(p.display_name)=lower(?) OR lower(a.alias)=lower(?) LIMIT 1", (person, person),
            ).fetchone()
            if not row:
                return [], person
            identities = [item[0] for item in db.execute(
                "SELECT identity FROM person_identities WHERE person_id=?", (row["id"],),
            ).fetchall()]
            aliases = [item[0].lower() for item in db.execute(
                "SELECT alias FROM person_aliases WHERE person_id=?", (row["id"],),
            ).fetchall()]
        return [*identities, *aliases], str(row["display_name"])

    def search(self, query: str, *, person: str = "", sources: list[str] | None = None, limit: int = 8) -> dict:
        terms = [word for word in re.findall(r"[a-z0-9']{2,}", query.lower()) if word not in STOPWORDS]
        identities, display_name = self._identities_for(person)
        source_names = [value.lower() for value in (sources or ["messages", "discord"])]
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM personal_events WHERE source IN ({','.join('?' for _ in source_names)}) "
                "ORDER BY occurred DESC LIMIT 2500", source_names,
            ).fetchall()
        ranked = []
        for row in rows:
            item = dict(row)
            haystack = " ".join((item["content"], item["sender"], item["participants"], item["channel"])).lower()
            if identities and not any(identity.lower() in haystack or _normalize_identity(identity) in _normalize_identity(haystack) for identity in identities):
                continue
            score = sum(3 for term in terms if term in item["content"].lower())
            score += sum(1 for term in terms if term in haystack)
            if person and person.lower() in haystack:
                score += 4
            if terms and score == 0:
                continue
            item["score"] = score
            item["person"] = display_name or person
            ranked.append(item)
        ranked.sort(key=lambda item: (item["score"], item["occurred"]), reverse=True)
        matches = []
        for item in ranked[:max(1, min(limit, 25))]:
            matches.append({
                "source": item["source"], "when": datetime.fromtimestamp(item["occurred"]).astimezone().isoformat(timespec="minutes"),
                "sender": item["person"] or item["sender"], "channel": item["channel"],
                "content": item["content"][:800], "direction": item["direction"], "score": item["score"],
            })
        return {"ok": True, "query": query, "person": display_name or person, "matches": matches}

    def recall(self, query: str, *, person: str = "", sources: list[str] | None = None, limit: int = 5) -> dict:
        # Refresh sources locally; failures are returned only if nothing searchable exists.
        message_sync = self.index_messages(limit=15000) if not sources or "messages" in sources else {"ok": True}
        if (not sources or "discord" in sources) and os.getenv("ORION_DISCORD_EXPORT_DIR"):
            self.index_discord_export()
        if person:
            identities, _ = self._identities_for(person)
            if not identities:
                self.sync_contact(person)
        result = self.search(query, person=person, sources=sources, limit=limit)
        if result["matches"]:
            return result
        if not message_sync.get("ok"):
            return {**result, "ok": False, "error": message_sync.get("error"), "permission_required": message_sync.get("permission_required", False)}
        return result


_personal: PersonalIntelligence | None = None


def personal() -> PersonalIntelligence:
    global _personal
    if _personal is None:
        _personal = PersonalIntelligence()
    return _personal


def infer_recall_request(text: str) -> dict:
    """Extract a likely person and subject for common conversational recall questions."""
    normalized = " ".join(text.strip().split())
    match = re.search(r"\b(?:when|what|where)\s+did\s+(.+?)\s+(?:say|tell|mention|text)(?:\s+(?:me|us))?\s*(.*)", normalized, re.I)
    if not match:
        return {"person": "", "query": normalized}
    person, subject = match.groups()
    subject = re.sub(r"^(?:that\s+)?(?:he|she|they)\s+", "", subject, flags=re.I)
    subject = re.sub(r"^(?:was|were|is|are)\s+(?:going\s+to\s+)?", "", subject, flags=re.I)
    return {"person": person.strip(" ,.?"), "query": subject.strip(" ,.?") or normalized}


def local_recall_answer(text: str) -> str | None:
    inferred = infer_recall_request(text)
    result = personal().recall(inferred["query"], person=inferred["person"], limit=3)
    if not result.get("ok") and result.get("permission_required"):
        return result.get("error")
    matches = result.get("matches", [])
    if not matches:
        return None
    best = matches[0]
    when = datetime.fromisoformat(best["when"]).astimezone()
    person = best.get("sender") or inferred["person"] or "They"
    return f'{person} said “{best["content"]}” on {when.strftime("%A, %B %-d at %-I:%M %p")}. I found it in {best["source"].title()}.'
