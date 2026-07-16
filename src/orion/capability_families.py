"""Declarative capability families used to assemble temporary worker teams."""

from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Family:
    name: str
    description: str
    capabilities: tuple[str, ...]
    markers: tuple[str, ...]
    available: bool
    mode: str
    prerequisite: str = ""


def _app(name: str) -> bool:
    # Some official macOS downloads include a version in the bundle name
    # (for example OpenSCAD-2021.01.app). Treat those as the same supported app.
    for root in (Path("/Applications"), Path.home() / "Applications"):
        if (
            (root / f"{name}.app").exists()
            or any(root.glob(f"{name}-*.app"))
            or (root / name / f"{name}.app").exists()
        ):
            return True
    return False


def _google_available() -> bool:
    return bool(os.getenv("GOOGLE_ACCESS_TOKEN") or (
        os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET") and os.getenv("GOOGLE_REFRESH_TOKEN")
    ))


def families() -> dict[str, Family]:
    codex = bool(shutil.which("codex") or Path("/Applications/ChatGPT.app/Contents/Resources/codex").exists())
    google = _google_available()
    microsoft = bool(os.getenv("MICROSOFT_ACCESS_TOKEN"))
    creative = any(_app(name) for name in ("Adobe Photoshop 2026", "Adobe Illustrator 2026", "Adobe Premiere Pro 2026", "DaVinci Resolve", "Movavi Video Editor 26", "Blender"))
    cad = any(_app(name) for name in ("Autodesk Fusion", "Fusion 360", "AutoCAD", "FreeCAD", "OpenSCAD", "Rhino 8", "Shapr3D", "Blender"))
    return {
        "google_workspace": Family(
            "Google Workspace", "Drive-native spreadsheets, documents, presentations, and file organization.",
            ("drive.search", "sheets.create", "sheets.design", "docs.create", "slides.create"),
            ("google drive", "google sheet", "spreadsheet", "google doc", "google slides", "drive folder"),
            google, "api", "Google OAuth credentials and Drive/Sheets/Docs/Slides scopes" if not google else "",
        ),
        "microsoft_365": Family(
            "Microsoft 365", "OneDrive, Excel, Word, PowerPoint, and Outlook artifacts.",
            ("onedrive", "excel", "word", "powerpoint", "outlook"),
            ("onedrive", "excel", "word document", "powerpoint", "outlook", "microsoft 365"),
            microsoft or _app("Microsoft Excel"), "graph_api_and_native",
            "Microsoft Graph authorization" if not microsoft else "",
        ),
        "development": Family(
            "Development", "Code generation, repository operations, testing, review, and IDE workspaces.",
            ("codex.generate", "git.inspect", "git.commit", "git.push", "ide.stage"),
            ("code", "repository", "github", "codex", "implement", "debug", "test", "xcode", "visual studio"),
            codex, "worker_and_native", "Codex installation" if not codex else "",
        ),
        "creative": Family(
            "Creative", "Image, design, audio, video, and 3D content production.",
            ("image.generate", "design.edit", "video.edit", "audio.edit", "3d.texture"),
            ("image", "design", "photoshop", "illustrator", "video", "audio", "creative", "render", "texture", "blender", "davinci", "da vinci", "resolve", "movavi"),
            creative, "native_adapter", "Install and authorize a supported creative application" if not creative else "",
        ),
        "engineering": Family(
            "Engineering and CAD", "Precedent research, requirements, concept selection, parametric CAD, printability, rendering, and validation.",
            ("design.research", "design.brief", "concept.compare", "cad.model", "cad.drawing", "manufacturing.validate", "dimensions.verify", "render.preview"),
            ("cad", "model", "part", "assembly", "drawing", "simulation", "engineering", "3d print", "freecad", "free cad", "openscad", "open scad", "blender"),
            cad, "application_api", "Install a supported CAD application with scripting/API access" if not cad else "",
        ),
        "business": Family(
            "Business", "Budgets, reports, invoices, forecasts, dashboards, and operational analysis.",
            ("budget.build", "report.generate", "invoice.track", "forecast", "dashboard"),
            ("budget", "finances", "financial", "invoice", "forecast", "business", "dashboard", "expenses"),
            google or microsoft, "composed", "Authorize Google Workspace or Microsoft 365" if not (google or microsoft) else "",
        ),
        "research": Family(
            "Research", "Current web research, local document retrieval, comparison, synthesis, and citations.",
            ("web.search", "files.search", "documents.retrieve", "compare", "synthesize"),
            ("research", "latest", "compare", "find information", "sources", "news", "analyze"),
            True, "hybrid",
        ),
        "macos": Family(
            "macOS", "Applications, windows, files, Apple apps, Shortcuts, notifications, and system state.",
            ("apps", "windows", "files", "calendar", "reminders", "notes", "mail", "shortcuts", "system"),
            ("open", "close", "window", "file", "calendar", "reminder", "note", "mail", "shortcut", "mac"),
            True, "native",
        ),
    }


def select_families(objective: str) -> list[Family]:
    text = objective.lower()
    selected = [family for family in families().values() if any(marker in text for marker in family.markers)]
    if not selected:
        selected = [families()["macos"]]
    # Business objectives require an artifact surface; prefer whichever office
    # family is available without making the user name that implementation detail.
    names = {family.name for family in selected}
    if "Business" in names and not names.intersection({"Google Workspace", "Microsoft 365"}):
        office = families()["google_workspace"] if families()["google_workspace"].available else families()["microsoft_365"]
        selected.append(office)
    return list(dict.fromkeys(selected))


def compile_objective(objective: str) -> dict:
    team = select_families(objective)
    missing = [family.prerequisite for family in team if not family.available and family.prerequisite]
    return {
        "ok": not missing,
        "objective": objective,
        "team": [asdict(family) for family in team],
        "available_families": [family.name for family in team if family.available],
        "blocked_families": [family.name for family in team if not family.available],
        "missing_prerequisites": missing,
        "execution_policy": "Compose capabilities automatically; ask only for unavailable credentials, consequential approval, or genuinely missing user data.",
    }


def status() -> dict:
    items = list(families().values())
    return {
        "ok": True,
        "families": [asdict(family) for family in items],
        "available": sum(family.available for family in items),
        "total": len(items),
    }
