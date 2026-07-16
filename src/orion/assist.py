"""OpenAI Responses API conversation and speech services."""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from openai import OpenAI
import sounddevice as sd

import tools
import activity
import diagnostics
import execution_supervisor
from agent_platform import platform
from task_engine import TaskEngine


def _setting(name: str, default: str = "") -> str:
    return os.getenv(f"ORION_{name}", os.getenv(f"JARVIS_{name}", default))


SYSTEM_PROMPT = """You are ORION (One Really Intelligent Operating Network), a concise, warm, capable voice assistant.
Address the user naturally. Because answers are spoken aloud, default to at most
45 words and three compact points unless detail is explicitly requested. Do not
include raw URLs in prose; citations may remain attached to displayed text.
Speak like a capable human assistant, not an audit log. Never say "audit result,"
"evidenced," "success criteria," "unmet," or expose process exit codes in the
final reply. Naturally summarize what worked, what remains, why, and what you can
do next. Never dump internal plans or diagnostic bookkeeping.
Use tools when the user asks for current research, weather, searches, Mac actions,
Apple apps, Spotify, Todoist, or Home Assistant. Only perform actions that the
user explicitly requested; never infer a side effect from casual conversation.
An explicit request to install an application authorizes install_application with
confirmed true. Use the trusted installer instead of merely opening a download page.
Questions asking whether an application is installed must use installation_status
and must never call install_application or start a second job.
Never promise a future action unless a tool result proves that a background job
actually started. Never report an action complete without successful tool evidence.
Treat the user's request as an objective, not a request to choose or describe
workers. Automatically compose the smallest temporary team from ORION's capability
families. Do not ask the user to name internal workers, adapters, formulas, sheets,
or implementation steps. Ask only for a missing credential, consequential approval,
or personal value that cannot be safely inferred. For cross-family objectives,
compile the objective, use every available family needed, and return the finished
artifact or one precise prerequisite—not a menu of possible approaches.
Use the supplied anticipation packet as local evidence. Expand the literal command
into the user's likely intended outcome by completing obvious safe prerequisites,
recovering from expected intermediate states, and verifying the result in the way a
competent human assistant would. Consult relevant prior successes and explicit
corrections before choosing an approach. Resolve references from the active project,
frontmost application, recent conversation, and observed state instead of asking the
user to repeat information ORION already has. When several interpretations remain,
choose the lowest-risk interpretation consistent with those preferences and state;
ask only when the choice would materially change or endanger the result. A predicted
next intent may be prepared or suggested, but never executed if it is consequential,
unrelated, or outside the authorized objective. Do not turn anticipation into chatter:
mention a next step only when it is specific, useful, and grounded in repeated behavior.
Treat a multi-part request as one persistent goal: make a short internal plan,
execute every authorized step in order, inspect tool results, diagnose blockers,
and continue until the requested outcome is complete or genuinely impossible.
Do not ask the user to open an app when open_application can do it. Do not defer
an already-authorized later step by saying you can do it next.
When the user explicitly asks to close or quit an application, use
quit_application and verify it exited. Never substitute hiding a window, closing
one window, or clicking coordinates. Do not force-quit or discard unsaved work.
Spotify existing-playlist playback and new-playlist creation are distinct: never
create a playlist unless the requested action verb is explicitly create, make,
build, or generate. The words "new", "discovery", and "recommendation" describe
a playlist but do not authorize creation when the requested verb is play, open,
start, resume, or listen. A request to play "one of my playlists" must only
play an existing playlist owned by the user or marked collaborative; followed
playlists owned by other people do not count as "my playlists."
Email tooling creates visible drafts only and never sends them.
Desktop inspection is read-only. Before desktop actions, inspect the screen, then
use only bounded actions explicitly requested by the user. Desktop control must
be enabled in the visible menu bar. Never inspect or type passwords, private keys,
authentication codes, or payment data. Always ask for confirmation immediately
before sending messages, submitting forms, purchases, deletions, or account changes.
Complete explicit low-risk requests through every necessary step and recover from
partial failures instead of stopping after the first tool call. Prefer semantic
tools such as browser navigation, Spotify, and Apple app tools over coordinates.
For Git work, use repository-aware Git tools instead of operating GitHub Desktop
with screen coordinates. First inspect repositories and status, infer a concise
commit message from the diff summary, then commit and push when explicitly asked.
When the user names GitHub Desktop, open it and keep it visible, while performing
the repository operation through background Git so no Terminal window is opened;
GitHub Desktop will reflect the same repository state. Explain this naturally only
if asked. If a commit succeeded but push failed, retry the push without recommitting.
An explicit request containing both "commit" and "push" is confirmation for that
operation; do not ask again. Opening GitHub Desktop may be an additional first
step when requested, but it is not a substitute for completing the Git operation.
For a commit-only request, use git_commit and never call git_commit_and_push.
When the user explicitly asks ORION to build, implement, refactor, fix, or generate
code in a named repository, codex_generate may delegate the work to the local Codex
worker. It edits only that repository in workspace-write mode, runs asynchronously,
and never authorizes a commit or push. Report the job identifier and let ORION monitor
it instead of pretending the requested artifact is already complete.
Google Workspace is an artifact adapter, not a separate assistant. A request to
create a finance or budgeting spreadsheet should use the budget template and create
the complete Drive artifact in one operation; the user does not need to specify
tabs, formulas, validation, formatting, or charts. Never claim creation when Google
authorization is unavailable, and never replace the requested Drive artifact with
a local file unless the user agrees.
Native creative and engineering requests must use their dedicated workers. For any
detailed product, 3D scene, CAD part, assembly, or printable object, behave like a
design engineer before behaving like a modeler: use web research to study at least
two relevant real precedents; extract transferable principles without copying a
single design; write explicit functional requirements, constraints, target scale,
material and process; compare three genuinely different concepts; score their
function, manufacturability, usability, visual coherence, and originality; then call
design_project_plan. Its brief_id is mandatory for the modeling call that follows.
The brief is only a prerequisite and never proves the requested artifact is complete.
Use blender_create_advanced_project for researched product concepts, vehicles,
architecture, machinery, environments, and detailed visual models. Use
blender_create_project only when the user explicitly wants a quick simple blockout.
Use blender_resume_advanced_project first when the user asks to continue, retry, or
finish an advanced Blender project ORION previously attempted. When it returns a
revision context, use blender_revise_advanced_project to patch that saved scene in
place. Preserve its design_brief_id and every unaffected component. Never call
design_project_plan again for an existing ORION project unless the user explicitly
asks to discard or replace the original design direction.
Recipe revision is not the same as editing an existing Blender document. When the
user asks to edit, apply, enact, attach, mate, reposition, or modify objects already
inside an open or saved .blend, first call blender_inspect_existing_document. Use
its exact object names, transforms, world bounds, collections, and parents to plan
the smallest change, then call blender_edit_existing_document. That tool edits the
same .blend, creates a backup, verifies declared geometry and assembly relationships,
and reloads the edited file. Classify the edit scope by the user's requested outcome,
not by the easiest available operation. Reshape, remodel, add-detail, repair-visible-
geometry, and make-more-realistic requests require geometry_revision with authored
geometry additions, named replacements, or applied booleans. Structural repair must
include a physical connector or authored geometry. Parenting, transforms, anchor
mates, and modifiers alone cannot satisfy either scope. Never answer with another plan after the user has asked
to enact it. Its timestamped backup is built into the edit operation; never claim a
separate backup or write tool is missing when blender_edit_existing_document is
available. Never claim an existing document changed from inspection or recipe data.
Use FreeCAD or OpenSCAD—not Blender alone—for dimensional functional parts and 3D
prints. FreeCAD supports profiles, revolves, placements, fillets, and constructive
booleans; OpenSCAD supports code-driven parametric solids. A printable design must
define nozzle, layer height, minimum wall, clearance, overhang limit, material, and
load case, and must pass the generated solid/mesh checks. If a mating dimension or
load is safety-critical and cannot be inferred, ask one precise question instead of
inventing it. Use resolve_create_project for Resolve projects, media pools, and
timelines. Do not claim completion from opening or clicking an application, and do
not overwrite an existing Resolve project or import media outside the user's home.
For advanced Blender work, decompose every named subject into a multi-part assembly
with primary forms, structural components, and visible secondary detail. Use profile
extrusion, revolved profiles, curves, custom vertex/face meshes, booleans, arrays,
and modifier stacks as appropriate. One primitive per requested noun is only a
blockout and does not satisfy a request for a finished or detailed model.
Every modeled component must state the requirement or principle it satisfies. Build
primary, secondary, and tertiary form hierarchy; resolve seams, thickness, edge
treatment, access, assembly logic, and repeated systems. Read the generated design
review after modeling. For a detailed Blender deliverable, visually inspect the
opened Blender result against the brief: judge silhouette, proportion, hierarchy,
plausibility, obvious intersections, camera framing, material separation, and the
specific requested character. If it still reads like generic primitives or a rough
blockout, revise the specification and run the worker again rather than defending a
weak first result. Be candid that automated
geometry and mesh checks do not replace human visual critique, structural analysis,
or slicer validation for a fabricated part.
Native Blender workers build in the background and open the exact finished project
themselves. Do not arrange, open, or inspect Blender before that worker completes;
doing so wastes time and can target a stale window. A successful advanced worker
result whose design review passed, exact file was verified, and project was loaded
is terminal evidence. Do not request another screen audit after that contract passes.
Treat colored neon/RGB/accent lighting as a physical fixture or emissive strip by
default, with neutral general illumination. Never represent a requested light as
an arbitrary floating sphere or color-wash every material. For a follow-up change
to the active Blender project, use blender_refine_project rather than desktop clicks,
Home Assistant, or rebuilding the project from scratch.
When the user asks to open, show, or load a native project, use native_project_open.
Opening the application, finding the file on disk, or seeing an untitled window is
not proof that the requested project is loaded. Completion requires the exact
editable artifact to be opened and verified in the native application's window.
When a native worker returns `resumable`, its draft path and design brief are the
authoritative continuation state. Revise that draft's complete validation list in
one pass and retry; never ask the user to locate a project ORION created or attempted.
Do not call the resume tool immediately after a worker has just rejected that same
specification—the rejection already contains the authoritative issue list, and an
unchanged rebuild cannot improve it.
Use screen inspection and desktop actions only as a fallback when no semantic tool
can do the job. Text the user explicitly asked you to type is confirmed, but typing
does not authorize submitting it. If an app fails to become frontmost, retry using
the relevant semantic tool or inspect and recover before replying.
Prefer labelled Accessibility inspection and actions over screenshots and coordinates.
They run locally, cost no model tokens, and must be verified after use. Use visual
inspection only when the relevant control is not exposed through Accessibility.
If Accessibility labels are unavailable, use on-device OCR before paid cloud vision.
For visible work spanning one or two applications, use desktop_window_arrange at
the beginning. It normalizes native fullscreen state and verifies the resulting
window frames under the click-through HUD. Restore them when the user asks or when
the session ends.
Interpret window requests as workspace goals, not merely geometry commands. Preserve
visibility, give cooperating apps balanced usable space, prefer the largest connected
display for a two-app stage, and account for each application's minimum size. If a
balanced horizontal split is physically impossible, use an even vertical stage and
briefly explain the constraint instead of claiming that a severely lopsided layout is
side by side. Keep the primary work application visible throughout the task.
Use the live execution feed for operational detail; spoken progress should mention
only meaningful milestones, blockers, and final verification, not every click.
When asked what failed or what happened previously, search durable task history;
never infer an earlier failure from the current screen.
For coordinate work in a named application, call desktop_inspect with that exact
application name before every coordinate sequence. This activates the application,
locks inspection to its physical display, and prevents clicks on another monitor.
Never claim a tool succeeded unless its result says it did. The current local time
is provided with each request when relevant. Do not expose internal tool syntax.
Every tool result is supervised locally. Treat `_supervision.verified` and its
checks as the completion evidence for that action. Never repeat a verified action.
If `duplicate_prevented` is present, continue from the already verified state rather
than attempting the action again. If a tool circuit is open, choose a genuinely
different adapter or report the specific blocker; never hammer the same route.
When a result contains `_rollback`, account for the restored state before choosing
the next route. A cancellation ends the remaining plan but preserves completed work.
The structured task plan supplied with the request is authoritative. Satisfy its
success criteria, not merely its first step. Automatically perform safe reversible
prerequisites within the user's goal. After failures, identify the unmet precondition,
observe again, revise the route, and retry with a bounded alternative. Stop only for
genuinely missing information, unavailable permission, or a consequential action
the user did not authorize.
"""


class OrionAssistant:
    def __init__(self) -> None:
        self.client = OpenAI()
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
        self.reasoning_effort = os.getenv(
            "OPENAI_REASONING_EFFORT",
            "low" if self.model.startswith("gpt-5.4") else "minimal",
        )
        self.voice = os.getenv("OPENAI_VOICE", "echo")
        self.tts_model = os.getenv("OPENAI_TTS_MODEL", "tts-1")
        self.previous_response_id: str | None = None
        self.last_selected_tools: list[dict] = []
        self.local_session_turns: list[dict[str, str]] = []
        self.active_native_project: dict[str, str] = self._load_recent_native_project()
        self.task_engine = TaskEngine()
        self.platform = platform()

    def _cloud_response(self, purpose: str, **kwargs):
        allowed, reason = self.platform.cloud_allowed(purpose)
        if not allowed:
            raise RuntimeError(reason)
        response = self.client.responses.create(**kwargs)
        self.platform.record_cloud(purpose, str(kwargs.get("model", self.model)), response)
        return response

    def _cloud_response_cancellable(self, purpose: str, request_id: str, **kwargs):
        """Let STOP return control immediately while a network response winds down."""
        if not request_id:
            return self._cloud_response(purpose, **kwargs)
        completed: queue.Queue = queue.Queue(maxsize=1)

        def request() -> None:
            try:
                completed.put((True, self._cloud_response(purpose, **kwargs)))
            except Exception as exc:
                completed.put((False, exc))

        worker = threading.Thread(target=request, name=f"orion-{purpose}-request", daemon=True)
        worker.start()
        while worker.is_alive():
            if request_id and execution_supervisor.cancellation_requested(request_id):
                diagnostics.event("cloud_wait_cancelled", request_id=request_id, purpose=purpose)
                return None
            worker.join(timeout=0.1)
        ok, value = completed.get()
        if ok:
            return value
        raise value

    def _finish_cancelled(self, request_id: str) -> str:
        answer = "Stopped. I preserved completed work and cancelled the remaining task."
        self.task_engine.finish("cancelled")
        execution_supervisor.clear_cancel()
        activity.update("session", "Stopped", "The active task was cancelled; completed work was preserved")
        diagnostics.event("execution_cancelled_safely", request_id=request_id)
        return answer

    def reset_session(self) -> None:
        """Start the next wake session as a fresh ChatGPT-style conversation."""
        self.previous_response_id = None
        self.last_selected_tools = []
        self.local_session_turns = []
        self.active_native_project = self._load_recent_native_project()
        self.task_engine.reset()
        try:
            import execution_engine
            execution_engine.clear_pending_intent()
        except Exception:
            pass

    @staticmethod
    def _load_recent_native_project() -> dict[str, str]:
        path = activity.RUNTIME / "recent-native-project.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return {str(key): str(item) for key, item in value.items()} if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _remember_native_project(self, value: dict[str, str]) -> None:
        self.active_native_project = value
        try:
            activity.RUNTIME.mkdir(parents=True, exist_ok=True)
            temporary = (activity.RUNTIME / "recent-native-project.json").with_suffix(".tmp")
            temporary.write_text(json.dumps(value), encoding="utf-8")
            temporary.replace(activity.RUNTIME / "recent-native-project.json")
        except OSError:
            pass

    def _clear_native_project_context(self, request_text: str) -> None:
        previous = dict(self.active_native_project)
        self.active_native_project = {}
        self.previous_response_id = None
        self.last_selected_tools = []
        self.local_session_turns = []
        try:
            activity.RUNTIME.mkdir(parents=True, exist_ok=True)
            temporary = (activity.RUNTIME / "recent-native-project.json").with_suffix(".tmp")
            temporary.write_text("{}", encoding="utf-8")
            temporary.replace(activity.RUNTIME / "recent-native-project.json")
        except OSError:
            pass
        diagnostics.event(
            "native_project_context_switched", previous_project=previous.get("project", ""),
            request=request_text[:500],
        )

    @staticmethod
    def _references_active_project(request_text: str, project: dict[str, str]) -> bool:
        text = request_text.casefold()
        project_words = {
            word for word in re.findall(r"[a-z0-9]+", str(project.get("project", "")).casefold())
            if len(word) >= 4 and word not in {"project", "design", "model"}
        }
        if project_words.intersection(re.findall(r"[a-z0-9]+", text)):
            return True
        return any(marker in text for marker in (
            "existing project", "current project", "same project", "this project",
            "existing file", "current file", "same file", "this file", "continue the",
            "the project", "the file", "the scene",
        ))

    @classmethod
    def _starts_new_engineering_project(cls, request_text: str, active_project: dict[str, str]) -> bool:
        if not active_project:
            return False
        text = " ".join(request_text.casefold().replace("’", "'").split())
        if re.search(r"\b(?:new|blank|separate)\s+(?:blender\s+)?(?:file|project|scene|design|model)\b", text):
            return True
        if cls._references_active_project(text, active_project):
            return False
        creation = re.search(r"\b(?:design|create|build|model|develop|generate)\b", text)
        engineering_subject = re.search(
            r"\b(?:clamp|mount|bracket|fixture|enclosure|assembly|mechanism|vehicle|robot|rover|"
            r"part|product|structure|cad|blender|freecad|openscad|3d|printable|manufactur)\w*\b",
            text,
        )
        return bool(creation and engineering_subject)

    @staticmethod
    def _is_direct_native_open_request(request_text: str) -> bool:
        text = " ".join(request_text.casefold().replace("’", "'").split())
        if re.search(r"\b(?:new|blank|create|design|build|model|generate|edit|modify|change|repair|fix|improve|make)\b", text):
            return False
        prefix = (
            r"^(?:(?:okay|ok|please|yes)[, ]+)?(?:can you |could you |would you |"
            r"i(?:'m| am) telling you to )?(?:open|load|display|show|bring)\b"
        )
        return bool(re.search(prefix, text))

    @staticmethod
    def _implies_active_project_refinement(request_text: str, active_project: dict[str, str]) -> bool:
        if not active_project:
            return False
        text = " ".join(request_text.casefold().replace("’", "'").split())
        return any(marker in text for marker in (
            "good start", "take this further", "take it further", "next pass", "next level",
            "not finished", "not ready", "still basic", "too basic", "needs work", "needs more",
            "could be better", "more detail", "more realistic", "more polished", "more robust",
            "more complete", "production ready", "sharper", "stronger", "safer",
        ))

    def record_turn(self, user: str, assistant: str, *, local: bool = False) -> None:
        """Retain locally answered turns that are absent from the cloud thread."""
        if not local:
            return
        user_limit = int(os.getenv("ORION_SESSION_USER_CHARS", "1800"))
        assistant_limit = int(os.getenv("ORION_SESSION_ASSISTANT_CHARS", "2600"))
        turn_limit = max(6, min(int(os.getenv("ORION_SESSION_CONTEXT_TURNS", "12")), 24))
        self.local_session_turns.append({"user": user[:user_limit], "assistant": assistant[:assistant_limit]})
        self.local_session_turns = self.local_session_turns[-turn_limit:]

    def ask(self, question: str, request_id: str = "") -> str:
        activity.update("planning", "Planning…")
        planning_started = time.perf_counter()
        request_text = question.rsplit("\nUser:", 1)[-1].strip()
        project_switched = self._starts_new_engineering_project(request_text, self.active_native_project)
        if project_switched:
            self._clear_native_project_context(request_text)
        implicit_project_refinement = self._implies_active_project_refinement(
            request_text, self.active_native_project,
        )
        mutation_requested = bool(
            self.task_engine.action_requested(request_text) or implicit_project_refinement
        )
        prior_task = self.task_engine.record
        resuming_pending_action = bool(
            prior_task and prior_task.plan.requires_tools
            and prior_task.status in {"planned", "executing", "awaiting_input"}
        )
        cloud_allowed, _ = self.platform.cloud_allowed("planning")
        plan = self.task_engine.plan(
            self.client, self.model, self.reasoning_effort, request_text, allow_cloud=cloud_allowed,
            on_response=lambda response: self.platform.record_cloud("planning", self.model, response),
        )
        # The full planner outcome can reveal a requested mutation after a
        # diagnostic prerequisite. Tool authorization must follow that complete
        # intent, not only the first verb in the user's sentence.
        mutation_requested = bool(
            mutation_requested
            or self.task_engine.mutation_requested
            or self.task_engine.plan_requests_mutation(request_text, plan)
        )
        self.task_engine.mutation_requested = mutation_requested
        if mutation_requested:
            plan.requires_tools = True
            if plan.risk == "read_only":
                plan.risk = "consequential"
        try:
            from orion_kernel import kernel
            kernel().adopt_plan(plan.goal, plan.steps, plan.success_criteria, plan.risk)
        except Exception as exc:
            diagnostics.event("kernel_plan_sync_failed", level="warning", request_id=request_id, error=str(exc))
        diagnostics.event(
            "plan_created", request_id=request_id,
            duration_ms=round((time.perf_counter() - planning_started) * 1000),
            lane=self.task_engine.lane, goal=plan.goal, steps=plan.steps,
            success_criteria=plan.success_criteria, risk=plan.risk,
        )
        local_context = (
            {"memories": [], "documents": [], "tasks": []}
            if project_switched else self.platform.context_for(request_text)
        )
        normalized_followup = " ".join(re.sub(r"[^a-z0-9 ]", " ", request_text.lower()).split())
        continuation = normalized_followup in {
            "yes", "yes please", "continue", "go ahead", "do it", "try again", "keep going", "please do",
            "yeah", "yeah do it", "yes do it", "check it", "check again",
        } or normalized_followup.startswith((
            "sure do ", "yes do ", "yeah do ", "okay do ", "ok do ",
            "do all of that", "do everything", "implement that", "carry that out",
        ))
        referential = continuation or implicit_project_refinement or any(marker in normalized_followup for marker in (
            "did you check", "didnt work", "didn t work", "wasnt", "wasn t", "still pending", "changes pending", "literally see",
            "that ", " it ", "instead", "retry", "try again", "add ", "change ", "modify ",
            "update ", "remove ", "make the", "make it", "the desk", "the project", "the file", "before",
            "take this", "take it", "next pass", "next level", "production ready", "more polished",
            "more realistic", "more robust", "more complete", "sharpen", "polish", "refine", "improve",
        ))
        if referential and prior_task and prior_task.plan.requires_tools and prior_task.plan.risk != "read_only":
            mutation_requested = True
            self.task_engine.mutation_requested = True
            plan.requires_tools = True
            if plan.risk == "read_only":
                plan.risk = prior_task.plan.risk
        # Tool routing must follow the current request, not action verbs copied
        # from previous-turn context. The full context is still supplied to the
        # model below for reference resolution.
        selection_request = request_text
        # The planner is the semantic intent compiler for vague requests. Feed
        # its current-turn outcome into capability routing so users do not need
        # to memorize tool-trigger verbs such as "create" or "edit".
        selection_request += (
            "\nCurrent planned goal: " + plan.goal
            + "\nCurrent planned steps: " + " | ".join(plan.steps[:10])
            + "\nCurrent success criteria: " + " | ".join(plan.success_criteria[:10])
        )
        if referential and self.active_native_project and not any(
            name in request_text.lower() for name in ("blender", "freecad", "openscad", "resolve")
        ):
            selection_request += "\nActive application: " + str(self.active_native_project.get("application", ""))
            if mutation_requested and str(self.active_native_project.get("application", "")).casefold() == "blender":
                selection_request += "\nRequested operation: edit existing Blender document"
        explicit_interrupted_resume = any(
            phrase in normalized_followup
            for phrase in ("previous task", "last task", "previous workflow", "last workflow")
        )
        interrupted_context = (
            local_context.get("tasks", [])
            if explicit_interrupted_resume and isinstance(local_context, dict) else []
        )
        if referential and interrupted_context:
            selection_request += "\nInterrupted or recent task to resume: " + json.dumps(interrupted_context[:1])
        selected_tools = tools.select_definitions(selection_request, allow_mutation=mutation_requested)
        if not selected_tools and continuation and self.last_selected_tools:
            selected_tools = self.last_selected_tools
        elif selected_tools:
            self.last_selected_tools = selected_tools
        if continuation and selected_tools and resuming_pending_action:
            plan.requires_tools = True
        if referential and interrupted_context and selected_tools:
            plan.requires_tools = True
        if plan.requires_tools and not selected_tools:
            answer = "I can’t perform that action yet because I don’t have an executable capability for it. I didn’t make any changes."
            self.task_engine.finish("blocked")
            diagnostics.event(
                "capability_gap_blocked", level="warning", request_id=request_id,
                request=request_text[:500], answer_chars=len(answer),
            )
            return answer
        complex_task = self.task_engine.lane == "complex"
        simple_default = "none" if self.model.startswith("gpt-5.4") else "minimal"
        turn_effort = self.reasoning_effort if complex_task else os.getenv("OPENAI_SIMPLE_REASONING_EFFORT", simple_default)
        context_suffix = ""
        if any(local_context.values()):
            context_suffix = "\n\nRelevant user-authorized local context:\n" + json.dumps(local_context)
        if self.local_session_turns:
            turn_limit = max(4, min(int(os.getenv("ORION_SESSION_CONTEXT_TURNS", "12")), 24))
            context_suffix += (
                "\n\nRecent turns completed locally in this same active conversation "
                "(resolve references and follow-ups against these):\n"
                + json.dumps(self.local_session_turns[-turn_limit:])
            )
        if self.active_native_project:
            context_suffix += "\n\nActive native project in this session:\n" + json.dumps(self.active_native_project)
        planned_input = (question + context_suffix) if not complex_task else (
            f"User request:\n{question}\n\nStructured task plan:\n{self.task_engine.context()}\n"
            + (
                "Execute the entire plan now. Do not merely describe it."
                if mutation_requested
                else "Inspect only the evidence needed to answer. Do not modify external state."
            ) + context_suffix
        )
        diagnostics.event(
            "tool_lane_selected", request_id=request_id, lane=self.task_engine.lane,
            tools=[definition.get("name", definition.get("type", "tool")) for definition in selected_tools], reasoning=turn_effort,
            mutation_requested=mutation_requested,
        )
        direct_native_open = bool(
            mutation_requested and self.active_native_project
            and self._is_direct_native_open_request(request_text)
            and self._references_active_project(request_text, self.active_native_project)
            and re.search(r"\b(?:file|project|scene|rover|blender)\b", request_text, re.IGNORECASE)
        )
        if direct_native_open:
            arguments = {
                "application": str(self.active_native_project.get("application", "Blender")),
                "project_name": str(self.active_native_project.get("project", "")),
            }
            action_id, _ = activity.begin_action("native_project_open", arguments)
            result = tools.execute(
                "native_project_open", arguments,
                context={"request_id": request_id, "task_id": self.task_engine.record.task_id if self.task_engine.record else ""},
            )
            activity.finish_action(action_id, result)
            self.task_engine.record_tool("native_project_open", result)
            if result.get("ok"):
                self.task_engine.finish("finished")
                answer = tools.result_summary("native_project_open", arguments, result)
                diagnostics.event("direct_native_open_completed", request_id=request_id, loaded=bool(result.get("loaded")))
                return answer
        model_started = time.perf_counter()
        response = self._cloud_response_cancellable("assistant", request_id,
            model=self.model,
            reasoning={"effort": turn_effort},
            instructions=SYSTEM_PROMPT,
            input=planned_input,
            tools=selected_tools,
            previous_response_id=self.previous_response_id,
        )
        if response is None:
            return self._finish_cancelled(request_id)
        diagnostics.event(
            "model_response_received", request_id=request_id, round=0,
            duration_ms=round((time.perf_counter() - model_started) * 1000),
            function_calls=len([item for item in response.output if item.type == "function_call"]),
        )

        # Continue through action, recovery, and evidence-based final verification.
        tools_since_audit = False
        action_effect_evidence = False
        audit_performed = False
        recovery_signatures: dict[str, int] = {}
        for _ in range(8):
            if request_id and execution_supervisor.cancellation_requested(request_id):
                return self._finish_cancelled(request_id)
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                if mutation_requested and plan.requires_tools and (tools_since_audit or not audit_performed):
                    activity.update("verifying", "Checking…")
                    diagnostics.event("completion_audit_started", request_id=request_id)
                    audit_started = time.perf_counter()
                    response = self._cloud_response_cancellable("verification", request_id,
                        model=self.model,
                        reasoning={"effort": turn_effort},
                        instructions=SYSTEM_PROMPT,
                        input=(
                            "Audit the active task against every success criterion. "
                            "Use tool-result evidence, not assumptions. If anything is unmet, "
                            "diagnose prerequisites and continue executing now. If all criteria "
                            "are evidenced, give the concise final answer. Do not repeat actions "
                            "whose successful results are already recorded."
                        ),
                        tools=selected_tools,
                        previous_response_id=response.id,
                    )
                    if response is None:
                        return self._finish_cancelled(request_id)
                    tools_since_audit = False
                    audit_performed = True
                    diagnostics.event(
                        "completion_audit_received", request_id=request_id,
                        duration_ms=round((time.perf_counter() - audit_started) * 1000),
                        function_calls=len([item for item in response.output if item.type == "function_call"]),
                    )
                    continue
                self.previous_response_id = response.id
                answer = response.output_text.strip() or "I don't have a response for that."
                if mutation_requested and plan.requires_tools and not action_effect_evidence:
                    if answer.rstrip().endswith("?"):
                        self.task_engine.finish("awaiting_input")
                        diagnostics.event("action_waiting_for_input", request_id=request_id, answer_chars=len(answer))
                        return answer
                    answer = "I couldn’t execute that request because no action ran. I didn’t make any changes."
                    self.task_engine.finish("blocked")
                    diagnostics.event(
                        "unevidenced_action_blocked", level="warning", request_id=request_id,
                        model_answer=response.output_text[:500],
                    )
                    return answer
                if not mutation_requested:
                    status = "answered"
                elif answer.rstrip().endswith("?"):
                    status = "awaiting_input"
                else:
                    status = "finished"
                self.task_engine.finish(status)
                diagnostics.event("assistant_finalized", request_id=request_id, status=status, answer_chars=len(answer))
                return answer

            tools_since_audit = True
            completed_calls: list[tuple[str, dict, dict]] = []

            def run_call(call):
                action_id = ""
                try:
                    arguments = json.loads(call.arguments or "{}")
                    action_id, detail = activity.begin_action(call.name, arguments)
                    activity.update("working", "Working…", detail)
                    tool_label, tool_target = activity.describe_tool(call.name, arguments)
                    diagnostics.event(
                        "tool_started", request_id=request_id, tool=call.name,
                        label=tool_label, target=tool_target,
                    )
                    tool_started = time.perf_counter()
                    result = tools.execute(
                        call.name, arguments,
                        context={
                            "request_id": request_id,
                            "task_id": self.task_engine.record.task_id if self.task_engine.record else "",
                        },
                    )
                except Exception as exc:  # Tool failures should not stop conversation.
                    result = {"ok": False, "error": str(exc)}
                    tool_started = locals().get("tool_started", time.perf_counter())
                if action_id:
                    activity.finish_action(action_id, result)
                diagnostics.event(
                    "tool_finished", request_id=request_id, tool=call.name,
                    duration_ms=round((time.perf_counter() - tool_started) * 1000),
                    ok=bool(result.get("ok")), error=str(result.get("error", ""))[:500],
                )
                self.task_engine.record_tool(call.name, result)
                completed_calls.append((call.name, arguments if 'arguments' in locals() else {}, result))
                if (result.get("ok") or result.get("resumable")) and call.name in {
                    "blender_create_project", "blender_refine_project", "freecad_create_project",
                    "blender_create_advanced_project", "blender_inspect_existing_document", "blender_edit_existing_document", "blender_resume_advanced_project", "blender_revise_advanced_project", "openscad_create_project", "resolve_create_project", "native_project_open",
                }:
                    self._remember_native_project({
                        "application": str(result.get("application") or arguments.get("application") or ""),
                        "project": str(result.get("project") or arguments.get("project_name") or ""),
                        "folder": str(result.get("folder") or ""),
                        "draft_path": str(result.get("draft_path") or ""),
                        "design_brief_id": str(result.get("design_brief_id") or arguments.get("design_brief_id") or ""),
                        "status": "resumable" if result.get("resumable") else "verified",
                    })
                return {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result),
                }

            safe_parallel = {
                "get_weather", "open_search", "system_status", "find_contact", "find_files",
                "git_repositories", "git_status", "desktop_inspect",
            }
            if len(calls) > 1 and all(call.name in safe_parallel for call in calls):
                with ThreadPoolExecutor(max_workers=min(4, len(calls))) as executor:
                    outputs = list(executor.map(run_call, calls))
            else:
                outputs = [run_call(call) for call in calls]

            stalled_recovery = None
            for _, _, result in completed_calls:
                if result.get("ok") or not result.get("resumable"):
                    continue
                records = list(result.get("validation_issue_records") or [])
                codes = sorted(str(item.get("code", "")) for item in records)
                fingerprint = "|".join((
                    str(result.get("specification_hash") or (result.get("revision_context") or {}).get("specification_hash", "")),
                    *codes,
                ))
                if not fingerprint.strip("|"):
                    fingerprint = str(result.get("error_code", "")) + "|" + str(result.get("error", ""))[:300]
                recovery_signatures[fingerprint] = recovery_signatures.get(fingerprint, 0) + 1
                if recovery_signatures[fingerprint] >= 2:
                    stalled_recovery = result
                    diagnostics.event(
                        "native_recovery_no_progress", level="warning", request_id=request_id,
                        project=result.get("project", ""), specification_hash=fingerprint.split("|", 1)[0],
                        issue_codes=codes,
                    )
                    break
            if stalled_recovery:
                self.task_engine.finish("resumable")
                answer = self.task_engine.recovery_summary()
                self.record_turn(request_text, answer, local=True)
                return answer
            if any(tools.is_action_evidence(name, arguments, result) for name, arguments, result in completed_calls):
                action_effect_evidence = True

            cancelled = next((result for _, _, result in completed_calls if result.get("cancelled")), None)
            if cancelled:
                return self._finish_cancelled(request_id)

            installation = next(
                ((name, arguments, result) for name, arguments, result in completed_calls
                 if name == "install_application" and result.get("ok") and result.get("status") == "running"),
                None,
            )
            if installation:
                answer = tools.result_summary(*installation)
                self.task_engine.finish("delegated")
                diagnostics.event(
                    "installation_delegated", request_id=request_id,
                    job_id=installation[2].get("job_id", ""), application=installation[2].get("application", ""),
                )
                return answer

            opened_apps = list(dict.fromkeys(
                str(result.get("application") or arguments.get("name") or "").strip()
                for name, arguments, result in completed_calls
                if name == "open_application" and result.get("ok")
            ))
            if len(opened_apps) >= 2:
                # Separate open calls are not a valid multi-app workspace. Stage
                # and verify the pair as one unit before reporting completion.
                import desktop
                arranged = desktop.arrange_windows(opened_apps[:2], confirmed=True)
                self.task_engine.record_tool("desktop_window_arrange", arranged)
                activity.record_step("arrange_opened_workspace", ", ".join(opened_apps[:2]), arranged)
                diagnostics.event(
                    "paired_workspace_verified", request_id=request_id,
                    applications=opened_apps[:2], ok=bool(arranged.get("ok")),
                    layout=arranged.get("layout", ""),
                )
                if not arranged.get("ok"):
                    completed_calls.append(("desktop_window_arrange", {"applications": opened_apps[:2]}, arranged))

            locally_final_tools = {
                "quit_application", "browser_navigate", "set_system_volume", "show_notification",
                "spotify_control", "spotify_play_playlist", "create_reminder", "create_note",
                "install_application", "installation_status",
                "blender_create_project", "freecad_create_project", "openscad_create_project",
                "blender_refine_project", "blender_create_advanced_project", "blender_edit_existing_document", "blender_resume_advanced_project", "blender_revise_advanced_project", "resolve_create_project", "native_project_open",
            }
            if re.match(r"^\s*(?:open|launch|start)\b", request_text, re.IGNORECASE):
                locally_final_tools.add("open_application")
            verified_native_delivery = bool(completed_calls) and all(
                name in locally_final_tools and result.get("ok")
                for name, _, result in completed_calls
            ) and any(
                name in {"blender_create_advanced_project", "blender_edit_existing_document", "blender_resume_advanced_project", "blender_revise_advanced_project"}
                and result.get("verified")
                and (
                    result.get("loaded")
                    or (
                        name == "blender_edit_existing_document"
                        and bool(result.get("disk_verification"))
                    )
                )
                and (
                    bool((result.get("design_review") or {}).get("passed"))
                    or bool((result.get("audit") or {}).get("passed"))
                )
                for name, _, result in completed_calls
            )
            if (
                (not complex_task or verified_native_delivery) and completed_calls
                and all(result.get("ok") for _, _, result in completed_calls)
                and all(name in locally_final_tools for name, _, _ in completed_calls)
            ):
                summaries = [tools.result_summary(name, arguments, result) for name, arguments, result in completed_calls]
                if all(summaries):
                    answer = " ".join(dict.fromkeys(summaries))
                    self.record_turn(request_text, answer, local=True)
                    self.task_engine.finish("finished")
                    diagnostics.event(
                        "local_tool_confirmation", request_id=request_id,
                        tools=[name for name, _, _ in completed_calls], answer_chars=len(answer),
                        verified_native_delivery=verified_native_delivery,
                    )
                    return answer

            generated = next(
                ((name, arguments, result) for name, arguments, result in completed_calls
                 if name == "codex_generate" and result.get("ok")),
                None,
            )
            if generated:
                answer = tools.result_summary(*generated)
                self.task_engine.finish("delegated")
                diagnostics.event(
                    "generation_delegated", request_id=request_id,
                    job_id=generated[2].get("job_id", ""), repository=generated[2].get("repository", ""),
                )
                return answer

            # A structured, known blocker does not benefit from another model
            # round-trip. Preserve the evidence and ask only for the missing
            # permission, identity, or confirmation in plain language.
            blockers = [result for _, _, result in completed_calls if not result.get("ok") and result.get("requires_user")]
            if blockers:
                answer = tools.failure_summary(blockers[-1])
                self.task_engine.finish("awaiting_input")
                diagnostics.event(
                    "known_blocker_returned_locally", request_id=request_id,
                    error_code=blockers[-1].get("error_code", ""), answer_chars=len(answer),
                )
                return answer

            completed_names = [name for name, _, _ in completed_calls]
            if "design_project_plan" in completed_names:
                activity.update(
                    "planning", "Engineering the selected concept…",
                    "Translating the approved design brief into named Blender assemblies, materials, and physical connections",
                )
            elif any(not result.get("ok") for _, _, result in completed_calls):
                activity.update("planning", "Revising the approach…", "Using the failed quality evidence to prepare a corrected execution route")
            else:
                activity.update("verifying", "Evaluating completed work…", "Checking results against the remaining plan before the next action")

            response = self._cloud_response_cancellable("tool_followup", request_id,
                model=self.model,
                reasoning={"effort": turn_effort},
                instructions=SYSTEM_PROMPT,
                input=outputs,
                tools=selected_tools,
                previous_response_id=response.id,
            )
            if response is None:
                return self._finish_cancelled(request_id)
            diagnostics.event(
                "model_response_received", request_id=request_id,
                duration_ms=round((time.perf_counter() - model_started) * 1000),
                function_calls=len([item for item in response.output if item.type == "function_call"]),
            )

        self.task_engine.finish("resumable" if self.task_engine.record and self.task_engine.record.recovery else "blocked")
        diagnostics.event("execution_limit_reached", level="error", request_id=request_id, rounds=8)
        if self.task_engine.record and self.task_engine.record.recovery:
            answer = self.task_engine.recovery_summary()
            self.record_turn(request_text, answer, local=True)
            return answer
        raise RuntimeError("ORION could not verify completion within the bounded execution limit.")

    def transcribe(self, audio_path: Path) -> str:
        model = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
        language = _setting("LANGUAGE", "en")
        use_stream = _setting("STREAM_TRANSCRIPTION", "1") == "1"
        if _setting("LOCAL_TRANSCRIPTION", "1") == "1":
            try:
                import mlx_whisper
                local_model = _setting("LOCAL_TRANSCRIBE_MODEL", "mlx-community/whisper-tiny")
                # Passing the recorder's PCM samples directly avoids mlx-whisper's
                # optional ffmpeg file-decoding dependency. Jarvis records exactly
                # this mono, 16 kHz, signed 16-bit WAV format.
                with wave.open(str(audio_path), "rb") as wav:
                    if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16000:
                        raise ValueError("Local transcription requires mono 16 kHz 16-bit PCM audio.")
                    waveform = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
                    waveform = waveform.astype(np.float32) / 32768.0
                result = mlx_whisper.transcribe(
                    waveform, path_or_hf_repo=local_model, language=language,
                    condition_on_previous_text=False, verbose=False,
                )
                text = str(result.get("text", "")).strip()
                if text:
                    text = self.sanitize_transcript(text)
                if text:
                    diagnostics.event("local_transcription_completed", model=local_model, characters=len(text))
                    return text
            except Exception as exc:
                diagnostics.event("local_transcription_failed", level="warning", error=str(exc))
                if _setting("ALLOW_TRANSCRIPTION_FALLBACK", "1") != "1":
                    raise RuntimeError("Local transcription failed and cloud fallback is disabled.") from exc
        allowed, reason = self.platform.cloud_allowed("transcription")
        if not allowed:
            raise RuntimeError(reason)
        try:
            with audio_path.open("rb") as audio:
                result = self.client.audio.transcriptions.create(
                    model=model, file=audio, language=language, stream=use_stream,
                )
                if hasattr(result, "text"):
                    text = self.sanitize_transcript(result.text.strip())
                    self.platform.record_cloud_event("transcription", model)
                    return text
                final_text = ""
                partial = ""
                for event in result:
                    if getattr(event, "type", "") == "transcript.text.delta":
                        partial += getattr(event, "delta", "")
                        if partial.strip():
                            activity.update("transcribing", "Hearing…", partial.strip()[-120:])
                    elif getattr(event, "type", "") == "transcript.text.done":
                        final_text = getattr(event, "text", "")
                text = self.sanitize_transcript((final_text or partial).strip())
                self.platform.record_cloud_event("transcription", model)
                return text
        except Exception as exc:
            if not use_stream:
                raise
            diagnostics.event("streaming_transcription_failed", level="warning", error=str(exc))
            with audio_path.open("rb") as audio:
                result = self.client.audio.transcriptions.create(
                    model=model, file=audio, language=language, stream=False,
                )
            text = self.sanitize_transcript(result.text.strip())
            self.platform.record_cloud_event("transcription", model)
            return text

    @staticmethod
    def sanitize_transcript(text: str) -> str:
        """Reject obvious decoder loops instead of treating them as commands."""
        text = " ".join(text.split()).strip()
        words = re.findall(r"[a-z0-9']+", text.lower())
        if not words:
            return ""
        longest_run = 1
        run = 1
        for previous, current in zip(words, words[1:]):
            run = run + 1 if current == previous else 1
            longest_run = max(longest_run, run)
        unique_ratio = len(set(words)) / len(words)
        corrupted = (
            longest_run >= 8
            or (len(words) >= 30 and unique_ratio < 0.18)
            or (len(text) > 1200 and unique_ratio < 0.35)
        )
        if corrupted:
            diagnostics.event(
                "transcription_rejected", level="warning", reason="decoder_repetition",
                characters=len(text), words=len(words), unique_ratio=round(unique_ratio, 3),
                longest_run=longest_run,
            )
            activity.update("session", "Please repeat that", "The last audio could not be transcribed reliably")
            return ""
        return text

    @staticmethod
    def speech_text(text: str) -> str:
        """Turn display-oriented Markdown into concise, speakable text."""
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"[*_`#]", "", text)
        text = re.sub(r"\n\s*[-•]\s*", ". ", text)
        text = re.sub(r"\s+", " ", text).strip()
        limit = int(_setting("MAX_SPOKEN_CHARS", "500"))
        if len(text) > limit:
            boundary = text.rfind(". ", 0, limit)
            text = text[: boundary + 1 if boundary > limit // 2 else limit].rstrip()
            text += " I’ve shown the remaining details on screen."
        return text

    def speak(self, text: str, allow_barge_in: bool = False) -> tuple[float, bool, Path | None]:
        if not text or _setting("MUTE", "0") == "1":
            return 0.0, False, None
        activity.stop_announcements()
        text = self.speech_text(text)
        if _setting("LOCAL_SPEECH", "1") == "1":
            return self._speak_local(text, allow_barge_in)
        request_started = time.perf_counter()
        allowed, reason = self.platform.cloud_allowed("speech")
        if not allowed:
            raise RuntimeError(reason)
        first_audio_delay = 0.0
        interrupted = False
        interruption_audio = None
        monitor_context = None
        if allow_barge_in:
            from audio import BargeInMonitor, PushToTalkMonitor, push_to_talk_enabled

            try:
                monitor_context = PushToTalkMonitor() if push_to_talk_enabled() else BargeInMonitor()
                monitor = monitor_context.__enter__()
            except Exception as exc:
                monitor_context = None
                monitor = None
                diagnostics.event("barge_in_unavailable", level="warning", error=str(exc))
        else:
            monitor = None
        try:
            try:
                with self.client.audio.speech.with_streaming_response.create(
                    model=self.tts_model,
                    voice=self.voice,
                    input=text,
                    response_format="pcm",
                ) as response:
                    pending = b""
                    started_output = False
                    underflows = 0
                    output_device = _setting("OUTPUT_DEVICE") or None
                    if output_device and output_device.isdigit():
                        output_device = int(output_device)
                    with sd.RawOutputStream(
                        samplerate=24000, channels=1, dtype="int16",
                        device=output_device, latency="low",
                    ) as output:
                        for chunk in response.iter_bytes(chunk_size=4096):
                            if monitor is not None and monitor.triggered.is_set():
                                interrupted = True
                                break
                            pending += chunk
                            # A small prebuffer prevents network jitter from producing
                            # gaps while preserving a quick spoken response.
                            if not started_output and len(pending) < 8192:
                                continue
                            complete = len(pending) - (len(pending) % 2)
                            if complete:
                                if not first_audio_delay:
                                    first_audio_delay = time.perf_counter() - request_started
                                    if monitor is not None:
                                        monitor.begin_playback()
                                underflows += int(bool(output.write(pending[:complete])))
                                pending = pending[complete:]
                                started_output = True
                        if pending and not interrupted:
                            complete = len(pending) - (len(pending) % 2)
                            if complete:
                                if not first_audio_delay:
                                    first_audio_delay = time.perf_counter() - request_started
                                underflows += int(bool(output.write(pending[:complete])))
                    diagnostics.event("speech_stream_health", underflows=underflows, output_device=str(output_device or "default"))
                    self.platform.record_cloud_event("speech", self.tts_model)
            except Exception as exc:
                diagnostics.event("speech_stream_failed", level="warning", error=str(exc))
                # macOS's built-in voice is a reliable last resort when the selected
                # audio device disappears or the network TTS stream fails.
                fallback_started = time.perf_counter()
                subprocess.run(["/usr/bin/say", text], check=True, timeout=120)
                if not first_audio_delay:
                    first_audio_delay = max(0.01, time.perf_counter() - fallback_started)
            if interrupted and monitor is not None:
                interruption_audio = monitor.capture_phrase()
        finally:
            if monitor_context is not None:
                monitor_context.__exit__(None, None, None)
        diagnostics.event(
            "speech_playback_finished", duration_ms=round((time.perf_counter() - request_started) * 1000),
            first_audio_ms=round(first_audio_delay * 1000), interrupted=interrupted, characters=len(text),
        )
        return first_audio_delay, interrupted, interruption_audio

    def _speak_local(self, text: str, allow_barge_in: bool) -> tuple[float, bool, Path | None]:
        """Free on-device speech with interruption support."""
        request_started = time.perf_counter()
        monitor_context = None
        monitor = None
        if allow_barge_in:
            try:
                from audio import BargeInMonitor, PushToTalkMonitor, push_to_talk_enabled
                monitor_context = PushToTalkMonitor() if push_to_talk_enabled() else BargeInMonitor()
                monitor = monitor_context.__enter__()
            except Exception as exc:
                diagnostics.event("barge_in_unavailable", level="warning", error=str(exc))
        command = ["/usr/bin/say"]
        voice = _setting("MACOS_VOICE").strip()
        if voice:
            command += ["-v", voice]
        command.append(text)
        if monitor is not None:
            monitor.begin_playback()
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        interrupted = False
        interruption_audio = None
        try:
            while process.poll() is None:
                if monitor is not None and monitor.triggered.is_set():
                    interrupted = True
                    process.terminate()
                    break
                time.sleep(0.04)
            process.wait(timeout=5)
            if interrupted and monitor is not None:
                interruption_audio = monitor.capture_phrase()
        finally:
            if process.poll() is None:
                process.terminate()
            if monitor_context is not None:
                monitor_context.__exit__(None, None, None)
        duration = time.perf_counter() - request_started
        diagnostics.event(
            "local_speech_finished", duration_ms=round(duration * 1000),
            interrupted=interrupted, characters=len(text),
        )
        return min(0.08, duration), interrupted, interruption_audio


JarvisAssistant = OrionAssistant


_default: OrionAssistant | None = None


def _assistant() -> OrionAssistant:
    global _default
    if _default is None:
        _default = OrionAssistant()
    return _default


def ask_question_memory(question: str) -> str:
    """Compatibility wrapper for older callers."""
    return _assistant().ask(question)


def TTS(text: str) -> str:
    """Compatibility wrapper for older callers."""
    _assistant().speak(text)
    return "done"
