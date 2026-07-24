"""Versioning and migrations for Mantice preset documents.

The schema version describes preset semantics, not the document layout. Mantice
continues to accept both flat website exports and grouped factory YAML.
Unversioned documents are legacy schema 1 and are migrated in memory.
"""

from __future__ import annotations

import copy
from typing import Any


CURRENT_PRESET_SCHEMA_VERSION = 2
LEGACY_PRESET_SCHEMA_VERSION = 1


def preset_schema_version(raw: dict[str, Any]) -> int:
    """Return and validate the declared schema version."""
    value = raw.get("schema_version", LEGACY_PRESET_SCHEMA_VERSION)
    if isinstance(value, bool):
        raise ValueError("preset schema_version must be an integer")
    try:
        version = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("preset schema_version must be an integer") from exc
    if version < LEGACY_PRESET_SCHEMA_VERSION:
        raise ValueError(f"unsupported preset schema_version {version}")
    if version > CURRENT_PRESET_SCHEMA_VERSION:
        raise ValueError(
            f"preset schema_version {version} is newer than this Mantice "
            f"build (supports up to {CURRENT_PRESET_SCHEMA_VERSION})"
        )
    return version


def migrate_preset_document(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a schema-2 copy of a raw flat or grouped preset document."""
    if not isinstance(raw, dict):
        raise ValueError("preset root must be an object")

    migrated = copy.deepcopy(raw)
    version = preset_schema_version(migrated)

    if version == 1:
        # Early master EQ documents called the low-mid bell simply ``mid``.
        # Preserve the old value while moving it to the unambiguous schema-2
        # name. Explicit schema-2 values always win.
        master = migrated.get("master")
        if isinstance(master, dict):
            eq = master.get("eq")
            if isinstance(eq, dict):
                aliases = (
                    ("mid_db", "lo_mid_db"),
                    ("mid_hz", "lo_mid_hz"),
                    ("mid_q", "lo_mid_q"),
                )
                for old_name, new_name in aliases:
                    if old_name in eq and new_name not in eq:
                        eq[new_name] = eq[old_name]
                    eq.pop(old_name, None)

        # Legacy top-level names were accepted by the browser but disappeared
        # when loaded through Python. Retain them in canonical metadata.
        if migrated.get("name"):
            meta = migrated.setdefault("meta", {})
            if isinstance(meta, dict):
                meta.setdefault("name", migrated["name"])

    migrated["schema_version"] = CURRENT_PRESET_SCHEMA_VERSION
    return migrated
