"""High-level local workflows with prerequisites, recovery, and verification."""

from __future__ import annotations

import re
import time
import uuid

import activity
import desktop
import diagnostics
import git_tools
import mac_tools
from agent_platform import platform


def _explicit_ui(request: str) -> bool:
    text = request.lower()
    return any(marker in text for marker in ("use the ui", "from the ui", "ui itself", "click specifically", "click the button"))


def _git_intent(request: str) -> tuple[bool, bool] | None:
    text = request.lower()
    if text.lstrip().startswith(("what ", "why ", "how ", "explain ", "describe ", "tell me ")) or any(
        marker in text for marker in ("problem i", "problem that", "what happened", "why did", "trying to commit")
    ):
        return None
    commit = bool(re.search(r"\bcommit(?:ted)?\b", text))
    push = bool(re.search(r"\bpush(?:ed)?\b|\bpublish\b", text))
    return (commit, push) if commit or push else None


def _infer_repository(request: str) -> dict:
    repositories = git_tools.repositories()
    if not repositories.get("ok"):
        return repositories
    items = repositories.get("repositories", [])
    lowered = request.lower()
    explicit = [item for item in items if item["name"].lower() in lowered]
    if len(explicit) == 1:
        return {"ok": True, "repository": explicit[0]["name"], "source": "request"}
    active = platform().active_project_session().get("session")
    if active:
        return {"ok": True, "repository": active["repository"], "source": "active_project"}
    if "github desktop" in lowered:
        ocr = desktop.local_ocr("GitHub Desktop")
        if ocr.get("ok"):
            visible_text = " ".join(str(item.get("text", "")) for item in ocr.get("text", [])).lower()
            current_matches = [
                item for item in items
                if re.search(rf"current repository\s+{re.escape(item['name'].lower())}\b", visible_text)
            ]
            if len(current_matches) == 1:
                return {"ok": True, "repository": current_matches[0]["name"], "source": "local_ocr"}
        snapshot = desktop.accessibility_snapshot("GitHub Desktop")
        if snapshot.get("ok"):
            visible = " ".join(
                str(element.get(key, ""))
                for element in snapshot.get("elements", [])
                for key in ("title", "description", "value", "identifier")
            ).lower()
            matches = [item for item in items if re.search(rf"\b{re.escape(item['name'].lower())}\b", visible)]
            if len(matches) == 1:
                return {"ok": True, "repository": matches[0]["name"], "source": "github_desktop"}
    changed = [item for item in items if item.get("changed_files")]
    if len(changed) == 1:
        return {"ok": True, "repository": changed[0]["name"], "source": "only_changed_repository"}
    return {
        "ok": False, "error_code": "repository_ambiguous", "requires_user": True,
        "error": "More than one repository could match.",
        "candidates": [item["name"] for item in changed or items],
    }


class WorkflowRun:
    def __init__(self, request: str, workflow: str, goal: str, steps: list[str] | None = None) -> None:
        self.task_id = uuid.uuid4().hex
        self.step = 0
        self.workflow = workflow
        platform().begin_task(self.task_id, request, goal, workflow)
        activity.set_execution_path(goal, steps or ["Inspect current state", "Perform the requested action", "Verify the outcome"])

    def event(self, action: str, result: dict, detail: str = "") -> dict:
        self.step += 1
        platform().record_task_event(
            self.task_id, self.step, action,
            "succeeded" if result.get("ok") else "failed",
            detail or str(result.get("error") or result.get("message") or ""), result,
        )
        diagnostics.event(
            "workflow_step", task_id=self.task_id, workflow=self.workflow,
            step=self.step, action=action, ok=bool(result.get("ok")),
            error_code=result.get("error_code", ""),
        )
        activity.record_step(action, detail or str(result.get("error") or result.get("message") or "Verified"), result)
        return result

    def finish(self, result: dict, summary: str) -> dict:
        status = "completed" if result.get("ok") else ("needs_input" if result.get("requires_user") else "failed")
        platform().finish_task(self.task_id, status, summary, result.get("error_code", ""))
        return {**result, "task_id": self.task_id, "summary": summary}


def _wait_for_clean(repository: str, timeout: float = 8.0) -> dict:
    deadline = time.monotonic() + timeout
    state = git_tools.status(repository)
    while state.get("has_changes") and time.monotonic() < deadline:
        time.sleep(0.35)
        state = git_tools.status(repository)
    return state


def _wait_for_push(repository: str, timeout: float = 12.0) -> dict:
    deadline = time.monotonic() + timeout
    state = git_tools.sync_status(repository)
    while state.get("ahead") not in {0, None} and time.monotonic() < deadline:
        time.sleep(0.5)
        state = git_tools.sync_status(repository)
    if state.get("ahead") == 0:
        return {**state, "ok": True, "pushed": True, "verified_up_to_date": True}
    return {**state, "ok": False, "error_code": "push_not_verified", "retryable": False, "error": "GitHub still reports a local commit waiting to be pushed."}


def _github_desktop_commit(run: WorkflowRun, repository: str, message: str) -> dict:
    set_result = run.event(
        "fill_required_summary",
        desktop.accessibility_set("GitHub Desktop", "textfield|Summary", message, confirmed=True),
        f"Generated local commit summary: {message}",
    )
    if not set_result.get("ok"):
        # Electron may expose the summary as a text area rather than a text field.
        set_result = run.event(
            "fill_required_summary_fallback",
            desktop.accessibility_set("GitHub Desktop", "Summary", message, confirmed=True),
        )
    if not set_result.get("ok"):
        return set_result
    pressed = run.event(
        "press_commit",
        desktop.accessibility_press("GitHub Desktop", "button|Commit", confirmed=True),
    )
    if not pressed.get("ok"):
        return pressed
    verified = _wait_for_clean(repository)
    if verified.get("has_changes"):
        return {"ok": False, "error_code": "commit_not_verified", "retryable": False, "error": "The commit control was pressed, but the working tree still has changes."}
    return {"ok": True, "repository": repository, "message": message, "working_tree_clean": True}


def _github_desktop_push(run: WorkflowRun, repository: str) -> dict:
    pressed = run.event(
        "press_push_origin",
        desktop.accessibility_press("GitHub Desktop", "button|Push origin", confirmed=True),
    )
    if not pressed.get("ok"):
        pressed = run.event(
            "press_push_menu_fallback",
            desktop.accessibility_press("GitHub Desktop", "menuitem|Push", confirmed=True),
        )
    if not pressed.get("ok"):
        state = git_tools.sync_status(repository)
        if state.get("ahead") == 0:
            return {**state, "ok": True, "pushed": True, "verified_up_to_date": True}
        return pressed
    return _wait_for_push(repository)


def run_git_workflow(request: str) -> dict | None:
    intent = _git_intent(request)
    if not intent:
        return None
    wants_commit, wants_push = intent
    activity.update("working", "Locating repository…", "Reading the active project and GitHub Desktop locally")
    inferred = _infer_repository(request)
    if not inferred.get("ok"):
        candidates = ", ".join(inferred.get("candidates", []))
        return {**inferred, "handled": True, "summary": f"I need the repository name first. Changed repositories: {candidates}."}
    repository = inferred["repository"]
    run = WorkflowRun(
        request, "git_commit_push", f"Commit and/or push {repository} and verify the result",
        ["Identify the repository", "Review changed files", "Create the commit", "Synchronize with GitHub", "Verify the final state"],
    )
    activity.update("working", "Repository identified", f"{repository} • reviewing changed files")
    activity.announce(f"I found {repository}. I’m reviewing the changes now.", key="git_review")
    if "github desktop" in request.lower():
        opened = run.event("open_github_desktop", mac_tools.open_application("GitHub Desktop"))
        if not opened.get("ok"):
            return run.finish(opened, "GitHub Desktop could not be opened.")
        arranged = desktop.arrange_windows(["GitHub Desktop"], confirmed=True)
        run.event("stage_github_desktop", arranged, "Placed GitHub Desktop beside the command deck")
    activity.update("working", "Reviewing changes…", repository)
    state = run.event("inspect_repository", git_tools.status(repository))
    if not state.get("ok"):
        return run.finish(state, state.get("error", "The repository could not be inspected."))
    message = git_tools.generate_commit_message(repository, "\n".join(state.get("changed_files", [])))
    use_ui = _explicit_ui(request)
    activity.update("working", "Applying Git operation…", f"{repository} • commit/push authorization confirmed")
    if wants_commit and use_ui and state.get("has_changes"):
        result = _github_desktop_commit(run, repository, message)
    elif wants_commit and wants_push:
        result = run.event("commit_and_push", git_tools.commit_and_push(repository, message, True))
    elif wants_commit:
        result = run.event("commit", git_tools.commit(repository, message, True))
    else:
        result = run.event("push", git_tools.push(repository, True))

    if wants_push and use_ui and result.get("ok"):
        result = run.event("verify_or_push", _github_desktop_push(run, repository))
    elif wants_push and not result.get("ok") and result.get("error_code") in {"remote_permission_denied", "authentication_required"} and "github desktop" in request.lower():
        activity.update("working", "Trying GitHub Desktop’s signed-in session…", repository)
        result = run.event("authenticated_desktop_push_recovery", _github_desktop_push(run, repository))

    if result.get("ok"):
        activity.update("verifying", "Verifying synchronization…", repository)
        verification = run.event("verify_repository", git_tools.sync_status(repository))
        if wants_push and verification.get("ahead") not in {0, None}:
            result = {"ok": False, "error_code": "push_not_verified", "error": "A local commit is still waiting to be pushed."}
        elif wants_commit and not verification.get("working_tree_clean"):
            result = {"ok": False, "error_code": "commit_not_verified", "error": "Uncommitted changes remain after the commit attempt."}
        else:
            result = {**result, "verification": verification}

    if result.get("ok"):
        action = "committed and pushed" if wants_commit and wants_push else ("committed" if wants_commit else "pushed")
        summary = f"{repository} was {action} successfully and the result was verified."
    elif result.get("error_code") in {"remote_permission_denied", "authentication_required"}:
        result["requires_user"] = True
        summary = f"The commit is safe locally, but GitHub rejected the push. Sign in or restore write access, then ask me to retry the push; I will not recommit."
    else:
        summary = result.get("error", "I stopped because the requested Git operation could not be verified.")
    return {**run.finish(result, summary), "handled": True}


def run_form_workflow(request: str) -> dict | None:
    """Fill one explicitly named, non-sensitive field without vision."""
    text = " ".join(request.strip().split())
    patterns = (
        r"(?:type|enter|put) (?P<value>.+?) into (?:the )?(?P<field>.+?) field (?:in|on) (?P<app>.+?)(?: app| application)?[.!?]?$",
        r"(?:in|on) (?P<app>.+?)(?: app| application)?,? (?:fill|set) (?:the )?(?P<field>.+?) field (?:to|with) (?P<value>.+?)[.!?]?$",
    )
    match = next((re.search(pattern, text, re.IGNORECASE) for pattern in patterns if re.search(pattern, text, re.IGNORECASE)), None)
    if not match:
        return None
    application = mac_tools.canonical_application_name(match.group("app").strip())
    field = match.group("field").strip()
    value = match.group("value").strip().strip('"')
    run = WorkflowRun(
        request, "labelled_form_fill", f"Fill the {field} field in {application} and verify it",
        [f"Open {application}", "Stage its window", f"Find the {field} field", "Enter the authorized text", "Verify the value"],
    )
    opened = run.event("open_application", mac_tools.open_application(application))
    if not opened.get("ok"):
        return {**run.finish(opened, opened.get("error", f"{application} could not be opened.")), "handled": True}
    run.event("stage_application", desktop.arrange_windows([application], confirmed=True), f"Placed {application} beside the command deck")
    result = run.event(
        "fill_labelled_field",
        desktop.accessibility_set(application, field, value, confirmed=True),
    )
    if result.get("ok"):
        observed = run.event("verify_field", desktop.accessibility_snapshot(application, field))
        values = [str(element.get("value", "")) for element in observed.get("elements", [])]
        if value not in values:
            result = {"ok": False, "error_code": "field_not_verified", "error": f"The {field} field could not be verified after typing."}
    summary = f"Filled the {field} field in {application} and verified it." if result.get("ok") else result.get("error", "The field could not be filled safely.")
    return {**run.finish(result, summary), "handled": True}


def recent_failure_summary(request: str) -> str | None:
    text = request.lower()
    if not any(marker in text for marker in ("what happened", "what failed", "problem did you", "problem you", "last failure", "previous failure")):
        return None
    history = platform().recent_tasks(limit=10).get("tasks", [])
    failed = next((task for task in history if task.get("status") in {"failed", "needs_input", "awaiting_input", "blocked"} or task.get("error_code")), None)
    if not failed:
        return "I don’t have a recorded failed task yet."
    detail = failed.get("result_summary") or failed.get("goal")
    code = failed.get("error_code")
    return f"The last recorded problem was: {detail}" + (f" The failure code was {code}." if code else "")


def try_execute(request: str) -> str | None:
    history_reply = recent_failure_summary(request)
    if history_reply:
        return history_reply
    result = run_git_workflow(request)
    if result is not None:
        return result.get("summary") or result.get("error")
    result = run_form_workflow(request)
    return (result.get("summary") or result.get("error")) if result is not None else None
