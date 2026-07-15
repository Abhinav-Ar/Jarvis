"""Engineering design briefs, concept selection, and manufacturability gates.

This module deliberately sits in front of the native modeling workers.  It turns
an aesthetic prompt into a traceable design decision before geometry is built.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

import diagnostics
import project_workspace as workspace


ARTIFACT_TYPES = {"visual_model", "product_concept", "functional_part", "3d_print", "assembly"}
PROCESSES = {"visual_only", "fdm_3d_print", "resin_3d_print", "cnc", "fabrication", "general"}
SCORE_KEYS = ("function", "manufacturability", "usability", "visual_coherence", "originality")
WEIGHTS = {"function": 0.30, "manufacturability": 0.25, "usability": 0.15, "visual_coherence": 0.20, "originality": 0.10}


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _.-]+", "", value).strip(" .")[:80]


def create_brief(
    project_name: str,
    intent: str,
    artifact_type: str,
    intended_use: str,
    target_dimensions: list[float],
    units: str,
    material: str,
    manufacturing_process: str,
    requirements: list[str],
    constraints: list[str],
    precedents: list[dict],
    concepts: list[dict],
    selected_concept: str,
    selection_rationale: str,
    design_principles: list[str],
    print_settings: dict,
    confirmed: bool,
    _request_id: str = "",
) -> dict:
    blocked = workspace.require_confirmation(confirmed, "engineering design brief")
    if blocked:
        return blocked
    error = _validate(
        project_name, intent, artifact_type, intended_use, target_dimensions, units,
        material, manufacturing_process, requirements, constraints, precedents,
        concepts, selected_concept, selection_rationale, design_principles, print_settings,
    )
    if error:
        return {"ok": False, "error_code": "incomplete_design_brief", "error": error}

    safe = _safe_name(project_name)
    folder = workspace.ROOT / safe / "Design"
    folder.mkdir(parents=True, exist_ok=True)
    brief_id = uuid.uuid4().hex[:12]
    scored = []
    for concept in concepts:
        item = dict(concept)
        item["weighted_score"] = round(sum(float(item[key]) * WEIGHTS[key] for key in SCORE_KEYS), 2)
        scored.append(item)
    selected = next(item for item in scored if item["name"].casefold() == selected_concept.strip().casefold())
    gates = _quality_gates(artifact_type, manufacturing_process, print_settings)
    brief = {
        "brief_id": brief_id,
        "project": safe,
        "created_at": time.time(),
        "request_id": _request_id,
        "intent": intent.strip(),
        "artifact_type": artifact_type,
        "intended_use": intended_use.strip(),
        "target_dimensions": [float(value) for value in target_dimensions],
        "units": units,
        "material": material.strip(),
        "manufacturing_process": manufacturing_process,
        "requirements": [item.strip() for item in requirements],
        "constraints": [item.strip() for item in constraints],
        "precedents": precedents,
        "concepts": scored,
        "selected_concept": selected["name"],
        "selection_rationale": selection_rationale.strip(),
        "design_principles": [item.strip() for item in design_principles],
        "print_settings": print_settings,
        "quality_gates": gates,
        "status": "approved_for_modeling",
    }
    path = folder / f"design-brief-{brief_id}.json"
    path.write_text(json.dumps(brief, indent=2), encoding="utf-8")
    (folder / "latest-design-brief.json").write_text(json.dumps(brief, indent=2), encoding="utf-8")
    diagnostics.event(
        "engineering_design_brief_created", request_id=_request_id, project=safe,
        brief_id=brief_id, artifact_type=artifact_type, process=manufacturing_process,
        precedents=len(precedents), concepts=len(concepts), selected_score=selected["weighted_score"],
    )
    return {
        "ok": True,
        "brief_id": brief_id,
        "project": safe,
        "brief_path": str(path),
        "selected_concept": selected["name"],
        "selected_score": selected["weighted_score"],
        "quality_gates": gates,
        "requires_followup": True,
        "next_action": "Build the selected concept with the appropriate Blender, FreeCAD, or OpenSCAD worker and pass this brief_id.",
    }


def load_brief(brief_id: str, project_name: str) -> tuple[dict | None, str]:
    identifier = str(brief_id).strip()
    safe = _safe_name(project_name)
    if not identifier:
        return None, "A design brief is required before advanced or engineering modeling."
    if not re.fullmatch(r"[a-f0-9]{12}", identifier):
        return None, "The design brief identifier is invalid."
    path = workspace.ROOT / safe / "Design" / f"design-brief-{identifier}.json"
    try:
        brief = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, f"No approved design brief {identifier} exists for {safe}."
    if brief.get("project") != safe or brief.get("status") != "approved_for_modeling":
        return None, "The design brief does not match this project or is not approved for modeling."
    return brief, ""


def attach(manifest: dict, brief: dict) -> None:
    manifest.update({
        "design_brief_id": brief["brief_id"],
        "artifact_type": brief["artifact_type"],
        "manufacturing_process": brief["manufacturing_process"],
        "selected_concept": brief["selected_concept"],
        "design_principles": brief["design_principles"],
        "quality_gates": brief["quality_gates"],
    })


def _validate(
    project_name: str, intent: str, artifact_type: str, intended_use: str,
    target_dimensions: list[float], units: str, material: str, process: str,
    requirements: list[str], constraints: list[str], precedents: list[dict],
    concepts: list[dict], selected_concept: str, selection_rationale: str,
    design_principles: list[str], print_settings: dict,
) -> str:
    if not _safe_name(project_name) or len(intent.strip()) < 20 or len(intended_use.strip()) < 12:
        return "Define the project, design intent, and intended use before modeling."
    if artifact_type not in ARTIFACT_TYPES or process not in PROCESSES or units not in {"mm", "cm", "m"}:
        return "Choose a supported artifact type, manufacturing process, and unit system."
    if len(target_dimensions) != 3 or any(float(value) < 0 for value in target_dimensions):
        return "Target dimensions must contain three non-negative values."
    if len([item for item in requirements if item.strip()]) < 5 or len([item for item in constraints if item.strip()]) < 3:
        return "A serious design needs at least five requirements and three constraints."
    if len(design_principles) < 4 or any(len(item.strip()) < 8 for item in design_principles):
        return "State at least four concrete design principles, not style adjectives alone."
    if len(precedents) < 2:
        return "Research at least two relevant precedents before selecting a concept."
    for item in precedents:
        if not str(item.get("source_url", "")).startswith(("https://", "http://")):
            return "Every precedent needs a source URL from research."
        if len(str(item.get("learned_principle", "")).strip()) < 15 or len(str(item.get("avoid_copying", "")).strip()) < 10:
            return "Extract a useful principle from each precedent and state what will not be copied."
    if len(concepts) < 3:
        return "Compare at least three distinct concepts before committing to geometry."
    names = set()
    for item in concepts:
        name = str(item.get("name", "")).strip()
        if not name or name.casefold() in names or len(str(item.get("strategy", "")).strip()) < 20:
            return "Each concept needs a unique name and a real design strategy."
        names.add(name.casefold())
        for key in SCORE_KEYS:
            score = float(item.get(key, 0))
            if score < 1 or score > 10:
                return f"Concept score {key} must be between 1 and 10."
    if selected_concept.strip().casefold() not in names or len(selection_rationale.strip()) < 20:
        return "Select one compared concept and explain the tradeoff behind that decision."
    functional = artifact_type in {"functional_part", "3d_print", "assembly"}
    if functional and (any(float(value) <= 0 for value in target_dimensions) or not material.strip() or process == "visual_only"):
        return "Functional and printable designs require real dimensions, a material, and a manufacturing process."
    if artifact_type == "3d_print":
        required = ("nozzle_mm", "layer_height_mm", "min_wall_mm", "clearance_mm", "max_overhang_deg")
        if any(float(print_settings.get(key, 0)) <= 0 for key in required):
            return "3D-print designs require nozzle, layer height, minimum wall, clearance, and overhang limits."
    return ""


def _quality_gates(artifact_type: str, process: str, print_settings: dict) -> list[str]:
    gates = [
        "Every major form traces to a requirement or selected design principle.",
        "Primary, secondary, and tertiary detail have a deliberate visual hierarchy.",
        "Assembly relationships, access, clearances, and likely failure points are resolved.",
        "The result is reviewed against all precedents without directly copying any one design.",
    ]
    if artifact_type in {"functional_part", "assembly", "3d_print"}:
        gates.extend([
            "Overall dimensions and interfaces match the engineering brief.",
            "The final solid is valid, non-empty, and exported in an editable engineering format.",
        ])
    if artifact_type == "3d_print" or process in {"fdm_3d_print", "resin_3d_print"}:
        gates.extend([
            f"Minimum wall thickness is at least {print_settings.get('min_wall_mm', 0)} mm.",
            f"Assembly clearance is at least {print_settings.get('clearance_mm', 0)} mm where parts must move or fit.",
            f"Unsupported overhangs stay within {print_settings.get('max_overhang_deg', 0)} degrees or receive supports.",
            "STL mesh is checked for degenerate facets and a closed manifold boundary.",
        ])
    return gates
