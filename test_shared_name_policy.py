import json
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from engine.web_server import (
    _fresh_shared_preset_name,
    _requested_shared_name,
    _shared_name_set,
)


ROOT = Path(__file__).resolve().parent


class SharedNamePolicyTests(unittest.TestCase):
    def test_manifest_names_are_normalized_across_both_formats(self):
        manifest = {
            "old": "  Magnetic Tape ",
            "new": {"name": "Spectral Timbre"},
            "empty": {"author": "Nobody"},
        }
        self.assertEqual(
            _shared_name_set(manifest),
            {"magnetic tape", "spectral timbre"},
        )
        self.assertEqual(
            _shared_name_set(manifest, exclude_id="new"),
            {"magnetic tape"},
        )

    def test_fresh_name_skips_existing_names_without_numbering_them(self):
        manifest = {"existing": {"name": "Magnetic Tape"}}
        with patch(
            "engine.generator._random_name",
            side_effect=["Magnetic Tape", "Copper Nebula"],
        ):
            suggestion = _fresh_shared_preset_name(manifest)
        self.assertEqual(suggestion, "Copper Nebula")
        self.assertNotRegex(suggestion, r" \(\d+\)$")

    def test_stock_placeholders_are_not_accepted_as_shared_names(self):
        for name in ("", "MANTICE", "untitled", " Untitled Preset "):
            self.assertEqual(_requested_shared_name(name), "")
        self.assertEqual(_requested_shared_name("  Quiet Engine  "), "Quiet Engine")

    def test_renamed_presets_keep_ids_and_metadata_in_sync(self):
        expected_names = {
            "Magnetic_Tape_2_20260720_c8f830": "Carvetoy Tape Quartet",
            "Magnetic_Tape_3_20260720_f86541": "Brown Noise Tape Array",
            "Spectral_Timbre_2_20260720_be5b34": "Lunar Spectral Pressure",
            "Spectral_Timbre_3_20260725_e6ea33": "Nearfield Granular Spectrum",
        }
        manifest = json.loads((ROOT / "shared/manifest.json").read_text(encoding="utf-8"))
        for preset_id, expected_name in expected_names.items():
            yaml_data = yaml.safe_load(
                (ROOT / f"shared/{preset_id}.yaml").read_text(encoding="utf-8")
            )
            json_data = json.loads(
                (ROOT / f"shared/{preset_id}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest[preset_id]["name"], expected_name)
            self.assertEqual(yaml_data["meta"]["name"], expected_name)
            self.assertEqual(json_data["name"], expected_name)

    def test_browser_prompts_and_backend_enforces_unique_names(self):
        server = (ROOT / "engine/web_server.py").read_text(encoding="utf-8")
        local_html = (ROOT / "engine/static/index.html").read_text(encoding="utf-8")
        deployed_html = (ROOT / "docs/index.html").read_text(encoding="utf-8")
        self.assertEqual(local_html, deployed_html)
        self.assertIn("/api/share-name-suggestion?name=", local_html)
        self.assertIn("Choose a unique preset name:", local_html)
        self.assertIn("name: sharedPresetName", local_html)
        self.assertIn('"code": "duplicate_name"', server)
        self.assertNotIn('candidate = f"{preset_name} ({i})"', server)


if __name__ == "__main__":
    unittest.main()
