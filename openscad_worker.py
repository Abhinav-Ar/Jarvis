"""OpenSCAD projects with engineering briefs and deterministic mesh checks."""

from __future__ import annotations

import math
import re
import struct
import subprocess
from collections import Counter
from pathlib import Path

import design_intelligence
import project_workspace as workspace


BINARY = Path("/Applications/OpenSCAD-2021.01.app/Contents/MacOS/OpenSCAD")


def create_project(
    project_name: str, description: str, source: str, confirmed: bool,
    design_brief_id: str = "", _request_id: str = "",
) -> dict:
    blocked = workspace.require_confirmation(confirmed, "OpenSCAD")
    if blocked:
        return blocked
    if not source.strip() or len(source) > 100000 or re.search(r"\b(?:include|use)\s*<", source, re.I):
        return {"ok": False, "error_code": "unsafe_scad_source", "error": "OpenSCAD source must be self-contained and under 100,000 characters."}
    if not BINARY.is_file():
        return {"ok": False, "error_code": "openscad_unavailable", "error": "OpenSCAD is not installed."}
    brief, brief_error = design_intelligence.load_brief(design_brief_id, project_name)
    if brief_error:
        return {"ok": False, "error_code": "design_brief_required", "error": brief_error}
    _, folder, manifest = workspace.project("OpenSCAD", project_name, _request_id)
    scad = folder / f"{manifest['project']}.scad"
    stl = folder / f"{manifest['project']}.stl"
    verification = folder / "printability-verification.json"
    manifest.update({"description": description[:3000], "source_characters": len(source)})
    design_intelligence.attach(manifest, brief or {})
    workspace.progress(manifest, folder, "Writing engineered parametric source", 1, "Self-contained design with brief-linked parameters")
    scad.write_text(source, encoding="utf-8")
    workspace.progress(manifest, folder, "Compiling solid geometry", 2, "OpenSCAD CGAL pipeline")
    try:
        result = subprocess.run([str(BINARY), "-o", str(stl), str(scad)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=900, check=False)
        (folder / "worker.log").write_text(result.stdout[-80000:], encoding="utf-8")
        if result.returncode != 0:
            return workspace.finish(manifest, folder, [scad, stl, verification], f"OpenSCAD exited with status {result.returncode}.")
        workspace.progress(manifest, folder, "Checking print mesh", 3, "Testing facets, closed edges, degeneracy, and physical bounds")
        report = inspect_stl(stl)
        report.update({
            "brief_id": (brief or {}).get("brief_id", ""),
            "selected_concept": (brief or {}).get("selected_concept", ""),
            "quality_gates": (brief or {}).get("quality_gates", []),
            "print_settings": (brief or {}).get("print_settings", {}),
            "limitations": ["Wall thickness, load simulation, and support placement still require slicer or engineering review."],
        })
        verification.write_text(__import__("json").dumps(report, indent=2), encoding="utf-8")
        error = "" if report.get("passed") else "; ".join(report.get("issues", []))
        finished = workspace.finish(manifest, folder, [scad, stl, verification], error)
        finished["printability_verification"] = report
        if finished.get("ok"):
            opened = workspace.open_project("OpenSCAD", manifest["project"])
            finished.update({"opened": bool(opened.get("ok")), "loaded": bool(opened.get("loaded")), "open_result": opened})
        return finished
    except (OSError, subprocess.SubprocessError) as exc:
        return workspace.finish(manifest, folder, [scad, stl, verification], str(exc))


def inspect_stl(path: Path) -> dict:
    """Perform a dependency-free boundary and degeneracy audit of an STL mesh."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"passed": False, "issues": [str(exc)], "triangles": 0}
    triangles: list[tuple[tuple[float, float, float], ...]] = []
    if len(data) >= 84 and 84 + struct.unpack_from("<I", data, 80)[0] * 50 == len(data):
        count = struct.unpack_from("<I", data, 80)[0]
        for index in range(count):
            values = struct.unpack_from("<12fH", data, 84 + index * 50)
            triangles.append((tuple(values[3:6]), tuple(values[6:9]), tuple(values[9:12])))
    else:
        vertices = [tuple(map(float, match)) for match in re.findall(rb"vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)", data)]
        triangles = [tuple(vertices[index:index + 3]) for index in range(0, len(vertices) - 2, 3)]
    issues = []
    if not triangles:
        return {"passed": False, "issues": ["The STL contains no triangles."], "triangles": 0}
    def key(vertex):
        return tuple(round(float(value), 5) for value in vertex)
    edges = Counter()
    degenerate = 0
    coordinates = []
    for triangle in triangles:
        a, b, c = triangle
        coordinates.extend(triangle)
        ab = tuple(b[i] - a[i] for i in range(3)); ac = tuple(c[i] - a[i] for i in range(3))
        cross = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0])
        if math.sqrt(sum(value * value for value in cross)) < 1e-9:
            degenerate += 1
        points = [key(a), key(b), key(c)]
        for start, end in ((0, 1), (1, 2), (2, 0)):
            edges[tuple(sorted((points[start], points[end])))] += 1
    boundary = sum(count != 2 for count in edges.values())
    if degenerate:
        issues.append(f"The mesh contains {degenerate} degenerate facets.")
    if boundary:
        issues.append(f"The mesh has {boundary} non-manifold or open boundary edges.")
    minimum = [min(point[axis] for point in coordinates) for axis in range(3)]
    maximum = [max(point[axis] for point in coordinates) for axis in range(3)]
    dimensions = [maximum[axis] - minimum[axis] for axis in range(3)]
    if any(value <= 0 for value in dimensions):
        issues.append("The mesh has zero extent on at least one axis.")
    return {
        "passed": not issues, "triangles": len(triangles), "degenerate_facets": degenerate,
        "boundary_edge_issues": boundary, "dimensions": dimensions, "issues": issues,
    }
