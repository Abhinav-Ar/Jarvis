"""Repository-aware Git actions for Jarvis."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path.home() / "Documents" / "GitHub"


def classify_error(detail: str) -> tuple[str, bool, bool, str]:
    text = detail.lower()
    if "permission" in text and ("403" in text or "denied" in text):
        return "remote_permission_denied", False, True, "Use an authenticated GitHub session or restore remote write access."
    if "authentication failed" in text or "could not read username" in text:
        return "authentication_required", False, True, "Sign in to GitHub, then retry the push without recommitting."
    if "could not resolve host" in text or "failed to connect" in text:
        return "network_unavailable", True, False, "Keep the local commit and retry the push when the network returns."
    if "non-fast-forward" in text or "fetch first" in text:
        return "remote_changes_ahead", False, True, "Fetch and reconcile remote changes before pushing."
    if "conflict" in text or "unmerged" in text:
        return "merge_conflict", False, True, "Resolve the listed conflicts before continuing."
    if "no upstream" in text:
        return "no_upstream", True, False, "Set the current branch upstream to origin and retry."
    return "git_command_failed", False, False, "Inspect the Git error and choose a bounded recovery."


def failure(detail: str, **context) -> dict:
    code, retryable, requires_user, recovery = classify_error(detail)
    return {
        "ok": False, "error": detail, "error_code": code,
        "retryable": retryable, "requires_user": requires_user,
        "recovery": recovery, **context,
    }


def _git(repository: Path, *arguments: str, timeout: int = 30) -> str:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(repository), *arguments], capture_output=True,
        text=True, timeout=timeout,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"Git {arguments[0]} failed.")
    return result.stdout.strip()


def _optional_git(repository: Path, *arguments: str) -> str:
    try:
        return _git(repository, *arguments)
    except RuntimeError:
        return ""


def _resolve_repository(repository: str) -> Path:
    requested = Path(repository).expanduser()
    candidate = requested if requested.is_absolute() else REPOSITORY_ROOT / requested
    candidate = candidate.resolve()
    root = REPOSITORY_ROOT.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Repository must be inside {REPOSITORY_ROOT}.")
    if not (candidate / ".git").exists():
        raise ValueError(f"Git repository not found: {candidate}")
    return candidate


def repositories() -> dict:
    if not REPOSITORY_ROOT.exists():
        return {"ok": False, "error": f"Repository folder not found: {REPOSITORY_ROOT}"}
    items = []
    for dot_git in sorted(REPOSITORY_ROOT.glob("*/.git")):
        repo = dot_git.parent
        status = _git(repo, "status", "--porcelain=v1")
        items.append({"name": repo.name, "path": str(repo), "changed_files": len(status.splitlines())})
    return {"ok": True, "repositories": items}


def status(repository: str) -> dict:
    repo = _resolve_repository(repository)
    porcelain = _git(repo, "status", "--porcelain=v1")
    branch = _git(repo, "branch", "--show-current")
    summary = _git(repo, "diff", "--stat", "HEAD")
    return {
        "ok": True,
        "repository": repo.name,
        "path": str(repo),
        "branch": branch,
        "changed_files": porcelain.splitlines(),
        "diff_summary": summary,
        "has_changes": bool(porcelain),
    }


def generate_commit_message(repository: str, porcelain: str = "") -> str:
    """Create a useful local message without sending a diff to a model."""
    repo = _resolve_repository(repository)
    changes = porcelain or _git(repo, "status", "--porcelain=v1")
    paths = []
    for line in changes.splitlines():
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if path:
            paths.append(path)
    if not paths:
        return "Sync local changes"
    lowered = [path.lower() for path in paths]
    labels = []
    if any("test" in path for path in lowered): labels.append("tests")
    if any(path.endswith((".swift", ".storyboard", ".xib")) or "hud" in path or "ui" in path for path in lowered): labels.append("interface")
    if any(path.endswith((".md", ".rst")) or "readme" in path for path in lowered): labels.append("documentation")
    if any(path.endswith(("requirements.txt", ".toml", ".lock")) for path in lowered): labels.append("dependencies")
    if any(path.endswith((".plist", ".env.example", ".yml", ".yaml")) for path in lowered): labels.append("configuration")
    code = [path for path in paths if Path(path).suffix.lower() in {".py", ".swift", ".js", ".ts", ".tsx"}]
    if code and "interface" not in labels: labels.insert(0, "assistant logic")
    if labels:
        description = ", ".join(labels[:2])
        if len(labels) > 2:
            description += f", and {labels[2]}"
        return f"Update {description}"[:72]
    if len(paths) == 1:
        stem = re.sub(r"[_-]+", " ", Path(paths[0]).stem).strip()
        return f"Update {stem or 'project file'}"[:72]
    return f"Update {len(paths)} project files"


def sync_status(repository: str) -> dict:
    repo = _resolve_repository(repository)
    branch = _git(repo, "branch", "--show-current")
    remote = _optional_git(repo, "remote", "get-url", "origin")
    upstream = _optional_git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    ahead = int(_optional_git(repo, "rev-list", "--count", "@{u}..HEAD") or "0") if upstream else None
    behind = int(_optional_git(repo, "rev-list", "--count", "HEAD..@{u}") or "0") if upstream else None
    return {
        "ok": True, "repository": repo.name, "branch": branch, "remote": remote,
        "upstream": upstream, "ahead": ahead, "behind": behind,
        "working_tree_clean": not bool(_git(repo, "status", "--porcelain=v1")),
    }


def commit(repository: str, message: str, confirmed: bool) -> dict:
    if not confirmed:
        return {"ok": False, "confirmation_required": True, "error": "The user must explicitly request a commit."}
    repo = _resolve_repository(repository)
    changes = _git(repo, "status", "--porcelain=v1")
    if not changes:
        return {"ok": True, "repository": repo.name, "already_clean": True, "message": "There were no uncommitted changes."}
    message = message.strip() or generate_commit_message(repository, changes)
    _git(repo, "add", "--all")
    _git(repo, "commit", "-m", message, timeout=60)
    commit_id = _git(repo, "rev-parse", "--short", "HEAD")
    remaining = _git(repo, "status", "--porcelain=v1")
    return {
        "ok": not bool(remaining),
        "repository": repo.name,
        "commit": commit_id,
        "message": message,
        "working_tree_clean": not bool(remaining),
    }


def commit_and_push(repository: str, message: str, confirmed: bool) -> dict:
    if not confirmed:
        return {
            "ok": False,
            "confirmation_required": True,
            "error": "The user must explicitly request both commit and push.",
        }
    repo = _resolve_repository(repository)
    before = _git(repo, "status", "--porcelain=v1")
    message = message.strip() or generate_commit_message(repository, before)
    committed = False
    if before:
        _git(repo, "add", "--all")
        _git(repo, "commit", "-m", message, timeout=60)
        committed = True
    commit = _git(repo, "rev-parse", "--short", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    if not branch:
        return {"ok": False, "error": "The repository is not currently on a named branch.", "error_code": "detached_head", "requires_user": True}
    remote = _optional_git(repo, "remote", "get-url", "origin")
    if not remote:
        return {"ok": False, "error": "This repository has no origin remote configured.", "error_code": "missing_origin", "requires_user": True}
    upstream = _optional_git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    try:
        if upstream:
            _git(repo, "push", timeout=120)
        else:
            _git(repo, "push", "--set-upstream", "origin", branch, timeout=120)
    except RuntimeError as exc:
        return failure(str(exc), repository=repo.name, branch=branch, commit=commit, committed=committed)
    ahead = int(_git(repo, "rev-list", "--count", "@{u}..HEAD") or "0")
    return {
        "ok": True,
        "repository": repo.name,
        "branch": branch,
        "commit": commit,
        "message": message,
        "committed": committed,
        "pushed": True,
        "verified_up_to_date": ahead == 0,
    }


def push(repository: str, confirmed: bool) -> dict:
    """Push an existing commit without ever creating another one."""
    if not confirmed:
        return {"ok": False, "confirmation_required": True, "error_code": "confirmation_required", "error": "The user must explicitly request a push."}
    repo = _resolve_repository(repository)
    branch = _git(repo, "branch", "--show-current")
    if not branch:
        return {"ok": False, "error_code": "detached_head", "requires_user": True, "error": "The repository is not currently on a named branch."}
    remote = _optional_git(repo, "remote", "get-url", "origin")
    if not remote:
        return {"ok": False, "error_code": "missing_origin", "requires_user": True, "error": "This repository has no origin remote configured."}
    upstream = _optional_git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    try:
        _git(repo, "push", timeout=120) if upstream else _git(repo, "push", "--set-upstream", "origin", branch, timeout=120)
    except RuntimeError as exc:
        return failure(str(exc), repository=repo.name, branch=branch, committed=False)
    state = sync_status(repository)
    return {**state, "pushed": True, "verified_up_to_date": state.get("ahead") == 0}
