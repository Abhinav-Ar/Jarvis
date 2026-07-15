import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import design_intelligence


def complete_brief(**overrides):
    values = {
        "project_name": "Field Instrument",
        "intent": "Create a durable handheld field instrument with legible controls and protected interfaces.",
        "artifact_type": "3d_print",
        "intended_use": "Repeated outdoor measurement work while wearing light gloves.",
        "target_dimensions": [160, 82, 32],
        "units": "mm",
        "material": "PETG",
        "manufacturing_process": "fdm_3d_print",
        "requirements": [
            "Protect the display", "Allow gloved control", "Provide cable strain relief",
            "Survive routine drops", "Open for service without destructive fasteners",
        ],
        "constraints": ["Fit a 220 mm print bed", "Avoid trapped supports", "Use M3 hardware"],
        "precedents": [
            {"name": "Rugged meter", "source_url": "https://example.com/meter", "learned_principle": "A raised perimeter protects the display during face-down impacts.", "avoid_copying": "Do not copy its exact silhouette."},
            {"name": "Field radio", "source_url": "https://example.com/radio", "learned_principle": "Recessed interfaces reduce accidental cable and switch damage.", "avoid_copying": "Do not reproduce its control layout."},
        ],
        "concepts": [
            {"name": "Protective spine", "strategy": "Use a structural center spine with replaceable impact shells on both sides.", "strengths": "Serviceable and robust", "risks": "More fasteners", "function": 9, "manufacturability": 8, "usability": 8, "visual_coherence": 8, "originality": 7},
            {"name": "Monocoque", "strategy": "Use a two-part clamshell with ribs concentrated around the display and ports.", "strengths": "Simple assembly", "risks": "Harder local repair", "function": 8, "manufacturability": 9, "usability": 8, "visual_coherence": 7, "originality": 6},
            {"name": "Corner cage", "strategy": "Use a thin internal case surrounded by four mechanically isolated corner bumpers.", "strengths": "Strong impact protection", "risks": "Larger envelope", "function": 8, "manufacturability": 7, "usability": 7, "visual_coherence": 9, "originality": 8},
        ],
        "selected_concept": "Protective spine",
        "selection_rationale": "It offers the best balance of impact protection, service access, and repeatable printing.",
        "design_principles": [
            "Protect fragile elements with proud sacrificial geometry.",
            "Make service seams and fasteners visually intentional.",
            "Use consistent radii to unify primary and secondary forms.",
            "Keep controls discoverable by touch and sight.",
        ],
        "print_settings": {"nozzle_mm": 0.4, "layer_height_mm": 0.2, "min_wall_mm": 1.6, "clearance_mm": 0.3, "max_overhang_deg": 45, "load_case": "One-meter drop and normal hand loads"},
        "confirmed": True,
    }
    values.update(overrides)
    return values


class DesignIntelligenceTests(unittest.TestCase):
    def test_rejects_shape_list_without_precedent_work(self):
        result = design_intelligence.create_brief(**complete_brief(precedents=[]))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "incomplete_design_brief")

    def test_persists_scored_engineering_brief(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(design_intelligence.workspace, "ROOT", Path(folder)):
            result = design_intelligence.create_brief(**complete_brief())
            self.assertTrue(result["ok"])
            loaded, error = design_intelligence.load_brief(result["brief_id"], "Field Instrument")
            self.assertFalse(error)
            self.assertEqual(loaded["selected_concept"], "Protective spine")
            self.assertGreaterEqual(len(loaded["quality_gates"]), 8)


if __name__ == "__main__":
    unittest.main()
