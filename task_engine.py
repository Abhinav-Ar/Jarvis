"""Persistent plan, evidence, and verification state for autonomous tasks."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import diagnostics
import anticipation
from agent_platform import platform


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

PLANNER_PROMPT = """You are ORION's task planner. Convert the user's request into
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
        runtime = Path(os.getenv("ORION_RUNTIME_DIR") or os.getenv("JARVIS_RUNTIME_DIR") or Path.home() / "Library/Application Support/Jarvis/.runtime")
        self.state_path = runtime / "active-task.json"
        self.record: TaskRecord | None = None
        self.lane = "simple"
        self.anticipation: dict[str, Any] = {}

    def _persist_new_record(self) -> None:
        if self.record:
            platform().begin_task(
                self.record.task_id, self.record.request, self.record.plan.goal,
                "model" if self.lane == "complex" else "direct",
            )

    @staticmethod
    def action_requested(request: str) -> bool:
        """Return whether the user is asking ORION to change external state."""
        text = " ".join(request.lower().split())
        if not text:
            return False
        informational = (
            "how do i ", "how can i ", "how would i ", "tell me how ",
            "what happens if ", "what is ", "what are ", "why ",
        )
        if any(text.startswith(prefix) for prefix in informational):
            return False
        action_markers = (
            "install ", "download ", "open ", "launch ", "close ", "quit ",
            "play ", "pause ", "resume ", "skip ", "set ", "change ",
            "create ", "make ", "build ", "generate ", "write ", "type ",
            "click ", "press ", "fill ", "submit ", "send ", "draft ",
            "delete ", "remove ", "move ", "copy ", "rename ", "organize ",
            "arrange ", "commit ", "push ", "pull ", "run ", "start ",
            "stop ", "turn on ", "turn off ", "add ", "schedule ", "remind ",
        )
        return any(
            text.startswith(marker)
            or text.startswith("please " + marker)
            or text.startswith("can you " + marker)
            or text.startswith("could you " + marker)
            or text.startswith("i want you to " + marker)
            for marker in action_markers
        )

    @staticmethod
    def route(request: str) -> str:
        text = request.lower()
        markers = (
            " and then ", "after that", "commit", "push", "fill out", "organize",
            "compare", "research", "all of", "multiple", "workflow", " then ",
            "arrange", "tile", "side by side", "both apps", "both applications",
            "balanced workspace", "create a workspace", "set up a workspace",
            "blender", "freecad", "openscad", "3d model", "3d print", "printable", "product design",
        )
        return "complex" if any(marker in text for marker in markers) else "simple"

    @staticmethod
    def _merge_unique(first: list[str], second: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in first + second:
            value = " ".join(str(item).split()).strip()
            key = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
            if value and key not in seen:
                seen.add(key)
                result.append(value)
        return result

    def _augment(self, plan: TaskPlan) -> TaskPlan:
        if not self.anticipation.get("action"):
            return plan
        # A cloud-disabled or failed planner should still expose a meaningful
        # domain plan in the HUD.  The generic fallback labels add no useful
        # information once the local objective engine has a concrete contract.
        if self.anticipation.get("category") != "general":
            generic_steps = {"inspect state", "act", "verify"}
            plan.steps = [step for step in plan.steps if step.strip().lower() not in generic_steps]
            generic_criteria = {"the requested outcome is verified"}
            plan.success_criteria = [
                criterion for criterion in plan.success_criteria
                if criterion.strip().lower() not in generic_criteria
            ]
        plan.steps = self._merge_unique(
            list(self.anticipation.get("prerequisite_steps", [])),
            self._merge_unique(plan.steps, list(self.anticipation.get("completion_steps", []))),
        )
        plan.success_criteria = self._merge_unique(
            plan.success_criteria, list(self.anticipation.get("success_criteria", [])),
        )
        return plan

    def plan(
        self, client: Any, model: str, reasoning_effort: str, request: str,
        allow_cloud: bool = True, on_response=None,
    ) -> TaskPlan:
        self.anticipation = anticipation.analyze(request)
        self.lane = self.route(request)
        if self.lane == "simple":
            requires_tools = self.action_requested(request)
            plan = TaskPlan(
                goal=request,
                requires_tools=requires_tools,
                success_criteria=["The requested external outcome is verified"] if requires_tools else ["Answer the request"],
                steps=["Execute the requested action", "Verify the outcome"] if requires_tools else ["Answer directly"],
                risk="low",
                missing_information=[],
            )
            plan = self._augment(plan)
            self.record = TaskRecord(uuid.uuid4().hex, request, plan)
            self._save()
            self._persist_new_record()
            return plan
        planner_input = (
            "Local zero-token objective analysis (use as required guardrails; do not expose it):\n"
            + json.dumps(self.anticipation)
            + "\n\nUser request:\n"
            + request
        )
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
                + planner_input
            )
        try:
            if not allow_cloud:
                raise RuntimeError("Cloud planning is disabled by the local cost policy.")
            response = client.responses.create(
                model=model,
                reasoning={"effort": reasoning_effort},
                instructions=PLANNER_PROMPT,
                input=planner_input,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "orion_task_plan",
                        "strict": True,
                        "schema": PLAN_SCHEMA,
                    }
                },
            )
            if on_response is not None:
                on_response(response)
            plan = TaskPlan(**json.loads(response.output_text))
        except Exception as exc:
            diagnostics.event("planner_fallback", level="warning", error=str(exc), request=request[:500])
            plan = TaskPlan.fallback(request)
        plan = self._augment(plan)
        if self.action_requested(request):
            plan.requires_tools = True
            if not plan.success_criteria:
                plan.success_criteria = ["The requested external outcome is verified"]
        self.record = TaskRecord(uuid.uuid4().hex, request, plan)
        self._save()
        self._persist_new_record()
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
                "anticipated_followups": self.anticipation.get("likely_followups", []),
                "anticipation_policy": self.anticipation.get("policy", ""),
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
                "error_code": str(result.get("error_code", ""))[:100],
            }
        )
        self.record.updated_at = time.time()
        platform().record_task_event(
            self.record.task_id, len(self.record.events), name,
            "succeeded" if result.get("ok") else "failed",
            str(result.get("error") or result.get("message") or "")[:2000],
            {key: value for key, value in result.items() if key not in {"text", "content", "analysis"}},
        )
        self._save()

    def finish(self, status: str) -> None:
        if not self.record:
            return
        self.record.status = status
        self.record.updated_at = time.time()
        last = self.record.events[-1] if self.record.events else {}
        platform().finish_task(
            self.record.task_id, status,
            str(last.get("error", "")) or f"Task {status}", str(last.get("error_code", "")),
        )
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
