"""Persistent plan, evidence, and verification state for autonomous tasks."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "requires_tools": {"type": "boolean"},
        "success_criteria": {"type": "array", "items": {"type": "string"}},
        "steps": {"type": "array", "items": {"type": "string"}},
        "risk": {"type": "string", "enum": ["read_only", "low", "consequential"]},
        "missing_information": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["goal", "requires_tools", "success_criteria", "steps", "risk", "missing_information"],
    "additionalProperties": False,
}

PLANNER_PROMPT = """You are Jarvis's task planner. Convert the user's request into
a complete execution plan before any actions occur. Work backward from observable
success. Insert necessary prerequisites the user did not spell out when they are
safe, reversible, and logically required. Examples include opening an application,
inspecting current state, selecting an unambiguous target, creating required text,
activating a playback device, or verifying a result. Do not add unrelated goals.
Mark externally consequential operations as consequential. Missing information
should include only facts that cannot safely be discovered with available tools.
For ordinary conversation or questions that need no tools, use requires_tools false.
Keep steps short and ordered."""


@dataclass
class TaskPlan:
    goal: str
    requires_tools: bool
    success_criteria: list[str]
    steps: list[str]
    risk: str
    missing_information: list[str]

    @classmethod
    def fallback(cls, request: str) -> "TaskPlan":
        return cls(request, True, ["The requested outcome is verified"], ["Inspect state", "Act", "Verify"], "low", [])


@dataclass
class TaskRecord:
    task_id: str
    request: str
    plan: TaskPlan
    status: str = "planned"
    events: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class TaskEngine:
    def __init__(self) -> None:
        runtime = Path(os.getenv("JARVIS_RUNTIME_DIR", Path.home() / "Library/Application Support/Jarvis/.runtime"))
        self.state_path = runtime / "active-task.json"
        self.record: TaskRecord | None = None
        self.lane = "simple"

    @staticmethod
    def route(request: str) -> str:
        text = request.lower()
        markers = (
            " and then ", "after that", "commit", "push", "fill out", "organize",
            "compare", "research", "all of", "multiple", "workflow",
        )
        return "complex" if any(marker in text for marker in markers) else "simple"

    def plan(self, client: Any, model: str, reasoning_effort: str, request: str) -> TaskPlan:
        self.lane = self.route(request)
        if self.lane == "simple":
            plan = TaskPlan(
                goal=request,
                requires_tools=False,
                success_criteria=["Answer or perform the single requested action"],
                steps=["Handle the request directly"],
                risk="low",
                missing_information=[],
            )
            self.record = TaskRecord(uuid.uuid4().hex, request, plan)
            self._save()
            return plan
        planner_input = request
        if self.record and time.time() - self.record.updated_at < 600:
            planner_input = (
                "Recent task context (use only if the new request is a continuation):\n"
                + json.dumps(
                    {
                        "request": self.record.request,
                        "goal": self.record.plan.goal,
                        "steps": self.record.plan.steps,
                        "status": self.record.status,
                        "tool_evidence": self.record.events,
                    }
                )
                + "\n\nNew user request:\n"
                + request
            )
        try:
            response = client.responses.create(
                model=model,
                reasoning={"effort": reasoning_effort},
                instructions=PLANNER_PROMPT,
                input=planner_input,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "jarvis_task_plan",
                        "strict": True,
                        "schema": PLAN_SCHEMA,
                    }
                },
            )
            plan = TaskPlan(**json.loads(response.output_text))
        except Exception:
            plan = TaskPlan.fallback(request)
        self.record = TaskRecord(uuid.uuid4().hex, request, plan)
        self._save()
        return plan

    def context(self) -> str:
        if not self.record:
            return ""
        plan = self.record.plan
        return json.dumps(
            {
                "goal": plan.goal,
                "success_criteria": plan.success_criteria,
                "ordered_steps": plan.steps,
                "risk": plan.risk,
                "missing_information": plan.missing_information,
            }
        )

    def record_tool(self, name: str, result: dict) -> None:
        if not self.record:
            return
        self.record.status = "executing"
        self.record.events.append(
            {
                "time": time.time(),
                "tool": name,
                "ok": bool(result.get("ok")),
                "error": str(result.get("error", ""))[:300],
            }
        )
        self.record.updated_at = time.time()
        self._save()

    def finish(self, status: str) -> None:
        if not self.record:
            return
        self.record.status = status
        self.record.updated_at = time.time()
        self._save()

    def reset(self) -> None:
        if self.record:
            self.finish("satisfied")
        self.record = None

    def _save(self) -> None:
        if not self.record:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(asdict(self.record), indent=2), encoding="utf-8")
            temporary.replace(self.state_path)
        except OSError:
            pass
