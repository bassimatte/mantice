"""Canonical shared-preset records and repository integrity checks."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


SHARED_PRESET_SCHEMA_VERSION = 1
SHARED_PRESET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
SHARED_WAVETABLE_RE = re.compile(
    r"^shared/wavetables/([a-f0-9]{64})\.wav$"
)


def inferred_created(preset_id: str) -> str | None:
    """Infer a stable creation date from the immutable preset ID."""
    match = re.search(r"_(\d{8})_[a-f0-9]+$", preset_id)
    if not match:
        return None
    stamp = match.group(1)
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}T00:00:00Z"


def normalize_shared_record(preset_id: str, value: Any) -> dict:
    """Return the one public record shape used by sidebar, gallery, and writes.

    The manifest key is the immutable ID. Older string entries remain readable,
    while all new writes use the versioned dictionary representation.
    """
    if not SHARED_PRESET_ID_RE.fullmatch(str(preset_id)):
        raise ValueError(f"Invalid shared preset ID: {preset_id!r}")

    if isinstance(value, str):
        source = {"name": value}
    elif isinstance(value, dict):
        source = dict(value)
    else:
        raise ValueError(f"Invalid manifest entry for {preset_id}")

    name = str(source.get("name") or "Untitled").strip() or "Untitled"
    author = str(source.get("author") or "Anonymous").strip() or "Anonymous"
    created = source.get("created") or inferred_created(preset_id)
    parent_id = str(source.get("parent_id") or "").strip() or None
    if parent_id and not SHARED_PRESET_ID_RE.fullmatch(parent_id):
        parent_id = None

    try:
        plays = max(0, int(source.get("plays", 0) or 0))
    except (TypeError, ValueError):
        plays = 0

    record = {
        "schema_version": SHARED_PRESET_SCHEMA_VERSION,
        "id": preset_id,
        "name": name,
        "author": author,
        "created": created,
        "plays": plays,
        "parent_id": parent_id,
        "visible": bool(source.get("visible", True)),
        "wavetables": list(source.get("wavetables") or []),
    }
    return record


def manifest_entry_from_record(record: dict) -> dict:
    """Serialize a normalized record without duplicating its manifest-key ID."""
    entry = {
        "schema_version": SHARED_PRESET_SCHEMA_VERSION,
        "name": record["name"],
        "author": record["author"],
        "created": record.get("created"),
        "plays": max(0, int(record.get("plays", 0) or 0)),
        "visible": bool(record.get("visible", True)),
    }
    if record.get("parent_id"):
        entry["parent_id"] = record["parent_id"]
    if record.get("wavetables"):
        entry["wavetables"] = list(record["wavetables"])
    return entry


def new_shared_record(
    preset_id: str,
    *,
    name: str,
    author: str,
    parent_id: str | None = None,
    wavetables: list[dict] | None = None,
    created: str | None = None,
) -> dict:
    """Create a validated record for a newly shared preset."""
    return normalize_shared_record(preset_id, {
        "schema_version": SHARED_PRESET_SCHEMA_VERSION,
        "name": name,
        "author": author,
        "created": created or datetime.utcnow().isoformat() + "Z",
        "plays": 0,
        "parent_id": parent_id,
        "visible": True,
        "wavetables": list(wavetables or []),
    })


def validate_shared_repository(manifest: dict, shared_dir: Path) -> list[str]:
    """Return integrity errors for the manifest, YAML files, and assets."""
    shared_dir = Path(shared_dir)
    errors: list[str] = []
    yaml_ids = {path.stem for path in shared_dir.glob("*.yaml")}
    manifest_ids = set(manifest)
    all_referenced_assets: set[str] = set()

    for preset_id in sorted(manifest_ids - yaml_ids):
        errors.append(f"{preset_id}: manifest entry has no YAML preset")
    for preset_id in sorted(yaml_ids - manifest_ids):
        errors.append(f"{preset_id}: YAML preset has no manifest entry")

    names: dict[str, str] = {}
    records: dict[str, dict] = {}
    for preset_id, value in sorted(manifest.items()):
        try:
            record = normalize_shared_record(preset_id, value)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        records[preset_id] = record

        folded_name = record["name"].casefold()
        if folded_name in names:
            errors.append(
                f"{preset_id}: display name duplicates {names[folded_name]} "
                f"({record['name']!r})"
            )
        else:
            names[folded_name] = preset_id

        parent_id = record.get("parent_id")
        if parent_id == preset_id:
            errors.append(f"{preset_id}: cannot remix itself")
        elif parent_id and parent_id not in manifest:
            errors.append(f"{preset_id}: parent {parent_id!r} is missing")

    for preset_id in sorted(yaml_ids):
        yaml_path = shared_dir / f"{preset_id}.yaml"
        try:
            preset = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            errors.append(f"{preset_id}: invalid YAML ({exc})")
            continue
        if not isinstance(preset, dict):
            errors.append(f"{preset_id}: YAML root must be an object")
            continue

        record = records.get(preset_id)
        referenced_assets: set[str] = set()
        for layer_index, layer in enumerate(preset.get("layers") or []):
            if not isinstance(layer, dict) or layer.get("type") != "wavetable":
                continue
            source = str(layer.get("wavetable_source") or "")
            match = SHARED_WAVETABLE_RE.fullmatch(source)
            if not match:
                errors.append(
                    f"{preset_id}: wavetable layer {layer_index + 1} has "
                    f"non-canonical source {source!r}"
                )
                continue
            digest = match.group(1)
            referenced_assets.add(digest)
            all_referenced_assets.add(f"{digest}.wav")
            asset_path = shared_dir.parent / source
            if not asset_path.is_file():
                errors.append(f"{preset_id}: missing wavetable asset {source}")
                continue
            actual_digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
            if actual_digest != digest:
                errors.append(f"{preset_id}: wavetable hash mismatch for {source}")

        if record:
            for item in record.get("wavetables", []):
                if not isinstance(item, dict):
                    errors.append(f"{preset_id}: invalid manifest wavetable record")
                    continue
                digest = str(item.get("sha256") or "")
                expected_path = f"shared/wavetables/{digest}.wav"
                if not re.fullmatch(r"[a-f0-9]{64}", digest):
                    errors.append(f"{preset_id}: invalid manifest wavetable hash")
                if item.get("path") != expected_path:
                    errors.append(
                        f"{preset_id}: manifest wavetable path must be "
                        f"{expected_path!r}"
                    )
            declared_assets = {
                str(item.get("sha256") or "")
                for item in record.get("wavetables", [])
                if isinstance(item, dict)
            }
            if declared_assets != referenced_assets:
                errors.append(
                    f"{preset_id}: manifest wavetable hashes do not match YAML "
                    f"(manifest={sorted(declared_assets)}, "
                    f"yaml={sorted(referenced_assets)})"
                )

    asset_dir = shared_dir / "wavetables"
    repository_assets = {path.name for path in asset_dir.glob("*.wav")}
    for filename in sorted(repository_assets - all_referenced_assets):
        errors.append(f"shared/wavetables/{filename}: unreferenced asset")

    return errors
