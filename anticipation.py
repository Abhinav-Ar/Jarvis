"""Zero-token objective expansion and bounded contextual preflight for ORION."""

from __future__ import annotations

import re
from typing import Any


INFORMATION_PREFIXES = ("what ", "why ", "how ", "explain ", "describe ", "tell me about ", "can i ")

RULES: list[dict[str, Any]] = [
    {
        "category": "git_delivery",
        "markers": ("commit", "push", "pull request", "github", "repository", "repo "),
        "prerequisites": ["Identify the intended repository and inspect its current state", "Review the changed files and derive an accurate change summary"],
        "completion": ["Perform the authorized Git operation", "Verify the working tree and remote synchronization state"],
        "criteria": ["The operation applies to the intended repository", "No requested Git operation remains incomplete or unverified"],
        "next": ["Report any remaining uncommitted or unpushed work"],
    },
    {
        "category": "engineering_design",
        "markers": ("blender", "freecad", "openscad", "3d model", "3d print", "printable", "cad ", "product design"),
        "prerequisites": ["Establish intended use, scale, constraints, and manufacturing intent", "Research comparable designs and compare viable concepts"],
        "completion": ["Build the selected concept in the appropriate native design tool", "Inspect the result against the design brief and verification gates"],
        "criteria": ["The result is an editable native artifact rather than a blockout", "Functional, visual, and manufacturing constraints are explicitly checked"],
        "next": ["Prepare the most relevant render, CAD export, or printability report"],
    },
    {
        "category": "workspace_layout",
        "markers": ("side by side", "arrange", "workspace", "split screen", "tile ", "move the window", "resize the window"),
        "prerequisites": ["Open the required applications and identify their actual displays", "Normalize fullscreen and minimum-size constraints"],
        "completion": ["Place the windows as a coherent working stage", "Verify visibility, balance, non-overlap, and target-display placement"],
        "criteria": ["Every requested application is usable and visible", "The layout is balanced for the available display instead of merely non-overlapping"],
        "next": ["Keep the primary application foregrounded for the requested work"],
    },
    {
        "category": "software_installation",
        "markers": ("install ", "download ", "set up the app", "get blender", "get freecad", "get openscad"),
        "prerequisites": ["Check whether the requested application is already installed", "Choose the trusted supported installation route"],
        "completion": ["Complete or monitor installation through a terminal state", "Verify the installed application exists and can launch"],
        "criteria": ["Installation is verified rather than merely downloaded or promised", "A failed route is diagnosed and a safe supported fallback is attempted"],
        "next": ["Open the installed application when that is part of the requested setup"],
    },
    {
        "category": "artifact_creation",
        "markers": ("spreadsheet", "google sheet", "google doc", "presentation", "budget", "document", "slides"),
        "prerequisites": ["Infer the artifact structure, audience, and useful defaults from the objective", "Confirm the destination adapter is available"],
        "completion": ["Create the complete requested artifact", "Verify its structure, formulas or content, and saved location"],
        "criteria": ["The artifact is usable without the user designing its internal structure", "The requested cloud or native destination contains the verified result"],
        "next": ["Open or surface the finished artifact for immediate use"],
    },
    {
        "category": "media_playback",
        "markers": ("spotify", "playlist", "play music", "play the song", "play my ", "resume music"),
        "prerequisites": ["Resolve the requested library item and an available playback device"],
        "completion": ["Start the intended item rather than resuming unrelated audio", "Verify the active playback context"],
        "criteria": ["The requested song, album, or owned/collaborative playlist is the active context"],
        "next": ["Preserve the active device for subsequent playback controls"],
    },
    {
        "category": "application_control",
        "markers": ("open ", "launch ", "close ", "quit ", "go to "),
        "prerequisites": ["Resolve the intended application or destination semantically"],
        "completion": ["Perform the requested application action", "Verify the application reached the requested state"],
        "criteria": ["The intended application is visibly in the requested open, foreground, or closed state"],
        "next": ["Preserve unsaved work and the user’s existing workspace"],
    },
    {
        "category": "task_management",
        "markers": ("remind ", "reminder", "calendar", "schedule ", "todoist", "task "),
        "prerequisites": ["Resolve dates, times, destination, and duplicate risk from available context"],
        "completion": ["Create the requested item", "Verify its title, schedule, and destination"],
        "criteria": ["The item exists once with the intended timing and wording"],
        "next": ["Surface only genuinely missing scheduling information"],
    },
]


def classify(request: str) -> str:
    text = " ".join(request.lower().split())
    if any(marker in text for marker in ("install ", "download ", "set up the app", "get blender", "get freecad", "get openscad")):
        return "software_installation"
    for rule in RULES:
        if any(marker in text for marker in rule["markers"]):
            return str(rule["category"])
    return "general"


def action_requested(request: str) -> bool:
    text = " ".join(request.lower().split())
    if text.startswith("please "):
        text = text[len("please "):]
    if text.startswith(INFORMATION_PREFIXES):
        return False
    verbs = (
        "open", "close", "create", "make", "build", "generate", "install", "download",
        "arrange", "move", "resize", "commit", "push", "play", "pause", "write", "fill",
        "send", "schedule", "remind", "add", "change", "set", "run", "start", "stop",
    )
    return any(re.search(rf"\b{verb}\b", text) for verb in verbs)


def analyze(request: str) -> dict[str, Any]:
    category = classify(request)
    action = action_requested(request)
    rule = next((item for item in RULES if item["category"] == category), None)
    if not action or not rule:
        return {
            "category": category, "action": action, "prerequisite_steps": [],
            "completion_steps": [], "success_criteria": [], "likely_followups": [],
            "policy": "Answer directly; do not manufacture an action objective.",
        }
    return {
        "category": category,
        "action": True,
        "prerequisite_steps": list(rule["prerequisites"]),
        "completion_steps": list(rule["completion"]),
        "success_criteria": list(rule["criteria"]),
        "likely_followups": list(rule["next"]),
        "policy": (
            "Complete safe reversible prerequisites and verification inside the requested objective. "
            "Anticipated follow-ups are preparation or suggestions only; do not perform consequential or unrelated actions without authorization."
        ),
    }


def probe_context(request: str, analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    """Collect only cheap, local, read-only context relevant to this objective."""
    analysis = analysis or analyze(request)
    context: dict[str, Any] = {}
    try:
        import mac_tools
        context["frontmost_application"] = mac_tools.frontmost_application()
    except Exception:
        pass
    category = analysis.get("category")
    if category == "git_delivery":
        try:
            import git_tools
            repositories = git_tools.repositories().get("repositories", [])
            context["repositories"] = [
                {
                    "name": item.get("name"), "branch": item.get("branch"),
                    "changed_files": len(item.get("changed_files", [])),
                }
                for item in repositories[:12]
            ]
        except Exception:
            pass
    if category == "engineering_design":
        try:
            import mac_tools
            context["design_applications"] = [
                {"name": item.get("name"), "capabilities": item.get("capabilities", [])}
                for item in mac_tools.workspace_applications()
                if item.get("name") in {"Blender", "FreeCAD", "OpenSCAD"}
            ]
        except Exception:
            pass
    try:
        from agent_platform import platform
        session = platform().active_project_session().get("session")
        if session:
            context["active_project"] = {
                "repository": session.get("repository"), "path": session.get("path"),
                "branch": session.get("branch"),
            }
    except Exception:
        pass
    return context
