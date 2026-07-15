"""OpenAI Responses API conversation and speech services."""

from __future__ import annotations

import json
import os
import re
import subprocess
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
Native creative and engineering requests must use their dedicated worker whenever
the user explicitly asks to create a project or artifact: blender_create_project
for editable scenes and renders, freecad_create_project for editable parametric
parts plus STEP/STL, openscad_create_project for self-contained source plus STL,
and resolve_create_project for Resolve projects, media pools, and timelines. Infer
reasonable project defaults from the objective instead of asking the user to design
the internal scene graph. Do not claim deep project creation from merely opening or
clicking the application. Never overwrite an existing Resolve project or import
media outside the user's home folder.
Treat colored neon/RGB/accent lighting as a physical fixture or emissive strip by
default, with neutral general illumination. Never represent a requested light as
an arbitrary floating sphere or color-wash every material. For a follow-up change
to the active Blender project, use blender_refine_project rather than desktop clicks,
Home Assistant, or rebuilding the project from scratch.
When the user asks to open, show, or load a native project, use native_project_open.
Opening the application, finding the file on disk, or seeing an untitled window is
not proof that the requested project is loaded. Completion requires the exact
editable artifact to be opened and verified in the native application's window.
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
        self.active_native_project: dict[str, str] = {}
        self.task_engine = TaskEngine()
        self.platform = platform()

    def _cloud_response(self, purpose: str, **kwargs):
        allowed, reason = self.platform.cloud_allowed(purpose)
        if not allowed:
            raise RuntimeError(reason)
        response = self.client.responses.create(**kwargs)
        self.platform.record_cloud(purpose, str(kwargs.get("model", self.model)), response)
        return response

    def reset_session(self) -> None:
        """Start the next wake session as a fresh ChatGPT-style conversation."""
        self.previous_response_id = None
        self.last_selected_tools = []
        self.local_session_turns = []
        self.active_native_project = {}
        self.task_engine.reset()
        try:
            import execution_engine
            execution_engine.clear_pending_intent()
        except Exception:
            pass

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
        local_context = self.platform.context_for(request_text)
        normalized_followup = " ".join(re.sub(r"[^a-z0-9 ]", " ", request_text.lower()).split())
        continuation = normalized_followup in {
            "yes", "yes please", "continue", "go ahead", "do it", "try again", "keep going", "please do",
            "yeah", "yeah do it", "yes do it", "check it", "check again",
        }
        referential = continuation or any(marker in normalized_followup for marker in (
            "did you check", "didnt work", "wasnt", "still pending", "changes pending", "literally see",
            "that ", " it ", "instead", "retry", "try again", "add ", "change ", "modify ",
            "update ", "remove ", "make the", "make it", "the desk", "the project",
        ))
        selection_request = request_text
        if referential and self.local_session_turns:
            selection_request += "\nRecent local turns: " + json.dumps(self.local_session_turns[-3:])
        if referential and self.active_native_project:
            selection_request += "\nActive native project: " + json.dumps(self.active_native_project)
        selected_tools = tools.select_definitions(selection_request)
        if not selected_tools and continuation and self.last_selected_tools:
            selected_tools = self.last_selected_tools
        elif selected_tools:
            self.last_selected_tools = selected_tools
        if continuation and selected_tools and resuming_pending_action:
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
            "Execute the entire plan now. Do not merely describe it." + context_suffix
        )
        diagnostics.event(
            "tool_lane_selected", request_id=request_id, lane=self.task_engine.lane,
            tools=[definition.get("name", definition.get("type", "tool")) for definition in selected_tools], reasoning=turn_effort,
        )
        model_started = time.perf_counter()
        response = self._cloud_response("assistant",
            model=self.model,
            reasoning={"effort": turn_effort},
            instructions=SYSTEM_PROMPT,
            input=planned_input,
            tools=selected_tools,
            previous_response_id=self.previous_response_id,
        )
        diagnostics.event(
            "model_response_received", request_id=request_id, round=0,
            duration_ms=round((time.perf_counter() - model_started) * 1000),
            function_calls=len([item for item in response.output if item.type == "function_call"]),
        )

        # Continue through action, recovery, and evidence-based final verification.
        tools_since_audit = False
        action_effect_evidence = False
        audit_performed = False
        for _ in range(8):
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                if plan.requires_tools and (tools_since_audit or not audit_performed):
                    activity.update("verifying", "Checking…")
                    diagnostics.event("completion_audit_started", request_id=request_id)
                    audit_started = time.perf_counter()
                    response = self._cloud_response("verification",
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
                if plan.requires_tools and not action_effect_evidence:
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
                if not plan.requires_tools:
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
                if result.get("ok") and call.name in {
                    "blender_create_project", "blender_refine_project", "freecad_create_project",
                    "openscad_create_project", "resolve_create_project", "native_project_open",
                }:
                    self.active_native_project = {
                        "application": str(result.get("application") or arguments.get("application") or ""),
                        "project": str(result.get("project") or arguments.get("project_name") or ""),
                        "folder": str(result.get("folder") or ""),
                    }
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
            if any(tools.is_action_evidence(name, arguments, result) for name, arguments, result in completed_calls):
                action_effect_evidence = True

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
                "blender_refine_project", "resolve_create_project", "native_project_open",
            }
            if re.match(r"^\s*(?:open|launch|start)\b", request_text, re.IGNORECASE):
                locally_final_tools.add("open_application")
            if (
                not complex_task and completed_calls
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

            response = self._cloud_response("tool_followup",
                model=self.model,
                reasoning={"effort": turn_effort},
                instructions=SYSTEM_PROMPT,
                input=outputs,
                tools=selected_tools,
                previous_response_id=response.id,
            )
            diagnostics.event(
                "model_response_received", request_id=request_id,
                duration_ms=round((time.perf_counter() - model_started) * 1000),
                function_calls=len([item for item in response.output if item.type == "function_call"]),
            )

        self.task_engine.finish("blocked")
        diagnostics.event("execution_limit_reached", level="error", request_id=request_id, rounds=8)
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
