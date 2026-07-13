"""Repository-aware Git actions for Jarvis."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path.home() / "Documents" / "GitHub"


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


def commit_and_push(repository: str, message: str, confirmed: bool) -> dict:
    if not confirmed:
        return {
            "ok": False,
            "confirmation_required": True,
            "error": "The user must explicitly request both commit and push.",
        }
    repo = _resolve_repository(repository)
    if not message.strip():
        return {"ok": False, "error": "A non-empty commit message is required."}
    before = _git(repo, "status", "--porcelain=v1")
    committed = False
    if before:
        _git(repo, "add", "--all")
        _git(repo, "commit", "-m", message.strip(), timeout=60)
        committed = True
    commit = _git(repo, "rev-parse", "--short", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    if not branch:
        return {"ok": False, "error": "The repository is not currently on a named branch."}
    remote = _optional_git(repo, "remote", "get-url", "origin")
    if not remote:
        return {"ok": False, "error": "This repository has no origin remote configured."}
    upstream = _optional_git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    try:
        if upstream:
            _git(repo, "push", timeout=120)
        else:
            _git(repo, "push", "--set-upstream", "origin", branch, timeout=120)
    except RuntimeError as exc:
        return {
            "ok": False,
            "repository": repo.name,
            "branch": branch,
            "commit": commit,
            "committed": committed,
            "error": str(exc),
            "recovery": "Resolve GitHub authentication or remote access, then retry push; do not recommit.",
        }
    ahead = int(_git(repo, "rev-list", "--count", "@{u}..HEAD") or "0")
    return {
        "ok": True,
        "repository": repo.name,
        "branch": branch,
        "commit": commit,
        "message": message.strip(),
        "committed": committed,
        "pushed": True,
        "verified_up_to_date": ahead == 0,
    }
