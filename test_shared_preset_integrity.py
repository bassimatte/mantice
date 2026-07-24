import json
import unittest
from pathlib import Path

from engine.shared_presets import (
    manifest_entry_from_record,
    normalize_shared_record,
    validate_shared_repository,
)


class SharedPresetIntegrityTests(unittest.TestCase):
    def test_repository_manifest_yaml_and_assets_are_consistent(self):
        shared_dir = Path(__file__).resolve().parent / "shared"
        manifest = json.loads(
            (shared_dir / "manifest.json").read_text(encoding="utf-8")
        )

        self.assertEqual(validate_shared_repository(manifest, shared_dir), [])

    def test_legacy_records_normalize_to_the_canonical_shape(self):
        record = normalize_shared_record(
            "Example_20260724_abc123",
            "Example",
        )

        self.assertEqual(record["id"], "Example_20260724_abc123")
        self.assertEqual(record["name"], "Example")
        self.assertEqual(record["plays"], 0)
        self.assertEqual(record["created"], "2026-07-24T00:00:00Z")
        self.assertTrue(record["visible"])

    def test_manifest_serialization_keeps_id_immutable_and_out_of_payload(self):
        record = normalize_shared_record(
            "Example_20260724_abc123",
            {
                "name": "Renamed Example",
                "author": "Lunar Loom",
                "plays": 4,
            },
        )

        entry = manifest_entry_from_record(record)

        self.assertNotIn("id", entry)
        self.assertEqual(entry["name"], "Renamed Example")
        self.assertEqual(entry["plays"], 4)


if __name__ == "__main__":
    unittest.main()
