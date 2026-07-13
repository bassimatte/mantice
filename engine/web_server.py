"""
engine/web_server.py — MANTICE V15.0
-----------------------------------
FastAPI-based web UI server.

Provides:
  - Preset browsing & loading
  - Parameter editing with live preview
  - Offline rendering with progress
  - Generator / mutator controls
  - WebSocket audio streaming for preview

Launch: python main.py --gui
"""

from __future__ import annotations

import asyncio
import json
import io
import os
import re
import base64
import hashlib
import threading
import uuid
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, Response, FileResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError:
    raise ImportError(
        "Web UI requires fastapi and uvicorn.\n"
        "Install with: pip install fastapi uvicorn[standard]"
    )

from . import config
from .preset_loader import load_preset, load_preset_from_yaml_string
from .streaming_engine import StreamingDroneEngine
from .exporter import export_audio
from .generator import generate_preset, mutate_preset, mutate_ui_params, save_generated_preset, _NAME_PARTS_A, _NAME_PARTS_B
from .convolution_reverb import apply_convolution_reverb
from .post_processing import oversampled_saturate

# Load .env file if present (for local development with GITHUB_TOKEN, FREESOUND_API_KEY)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, rely on system environment variables

# ── Helpers ───────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent
_PRESETS_DIR = _ROOT / "presets"
_EXPORTS_DIR = _ROOT / "exports"
_SHARED_DIR = _ROOT / "shared"
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_SAMPLES_DIR = _ROOT / "samples"
_WAVETABLES_DIR = _SAMPLES_DIR / "wavetables"
_FS_CACHE_DIR = _SAMPLES_DIR / "freesound_cache"
_PITCH_CACHE_FILE = _SAMPLES_DIR / "pitch_cache.json"

# In-memory pitch cache; populated at startup and on-demand
_pitch_cache: dict = {}

# Global engine for /api/meters endpoint (used by WebSocket preview)
engine: Optional[StreamingDroneEngine] = None


def final_limit_normalize(audio: np.ndarray, ceiling: float = 0.97,
                           sr: int = 22050) -> np.ndarray:
    """
    True-peak normalize the full render buffer to ``ceiling``.

    For offline drone renders (constant-level material) a single static scale
    factor is the correct approach — no attack lag, no pumping, no transients
    slipping through before the envelope catches up.

    Algorithm:
      1. True-peak detection: upsample 4× to find inter-sample peaks (prevents
         MP3/AAC encode clipping caused by intersample overs).
      2. If the true peak exceeds ``ceiling``, scale the whole buffer uniformly
         by ceiling/peak.  Never boost — if peak < ceiling, return as-is.
      3. Hard clip as final safety net (should be a no-op after step 2).

    Args:
        audio:    (N, 2) stereo float32 array.
        ceiling:  Linear ceiling (default 0.97 ≈ −1 dBFS).
        sr:       Sample rate (unused; kept for API compatibility).

    Returns:
        Same shape — normalized to ceiling if over, untouched if under.
    """
    from scipy.signal import resample_poly
    factor = 4
    up      = resample_poly(audio, factor, 1, axis=0)
    tp      = float(np.max(np.abs(up)))          # true-peak
    if tp > ceiling:
        audio = audio * (ceiling / tp)
    return np.clip(audio, -1.0, 1.0).astype(audio.dtype)


def _load_pitch_cache():
    global _pitch_cache
    try:
        if _PITCH_CACHE_FILE.exists():
            with open(_PITCH_CACHE_FILE) as _f:
                _pitch_cache = json.load(_f)
    except Exception:
        _pitch_cache = {}
    try:
        from .granular_layer import _PITCH_CACHE as _gl_cache
        _gl_cache.update(_pitch_cache)
    except Exception:
        pass


def _save_pitch_cache():
    try:
        with open(_PITCH_CACHE_FILE, 'w') as _f:
            json.dump(_pitch_cache, _f, indent=2)
    except Exception:
        pass


def _detect_pitch_hz_sync(filepath: str):
    """Detect fundamental pitch of an audio file using librosa.yin. Returns Hz or None."""
    try:
        import librosa
        y, sr = librosa.load(filepath, sr=22050, duration=5.0, mono=True)
        f0 = librosa.yin(y, fmin=50, fmax=2000, sr=sr)
        voiced = f0[(f0 > 50) & (f0 < 2000)]
        if len(voiced) > 20:
            return float(round(float(np.median(voiced)), 2))
    except Exception:
        pass
    return None


def _background_pitch_scan():
    """Scan all sample files for pitch (runs in thread pool at startup)."""
    import time
    changed = False
    for directory, prefix in [(_SAMPLES_DIR, ""), (_FS_CACHE_DIR, "freesound_cache/")]:
        if not directory.exists():
            continue
        for fname in os.listdir(directory):
            if not fname.endswith((".ogg", ".wav", ".flac", ".mp3")):
                continue
            key = prefix + fname if prefix else fname
            if key in _pitch_cache:
                continue  # already cached
            path = directory / fname
            hz = _detect_pitch_hz_sync(str(path))
            _pitch_cache[key] = hz
            changed = True
            time.sleep(0.01)  # yield between files
    if changed:
        _save_pitch_cache()
        try:
            from .granular_layer import _PITCH_CACHE as _gl_cache
            _gl_cache.update(_pitch_cache)
        except Exception:
            pass

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "bassimatte/mantice"
GITHUB_BRANCH = "main"
FREESOUND_API_KEY = os.environ.get("FREESOUND_API_KEY", "zwjXCAeWopixCMievVQ5q1FLmyh1DBvMf4HJuqNE")
FREESOUND_BASE = "https://freesound.org/apiv2"

_GH_API_BASE = f"https://api.github.com/repos/{GITHUB_REPO}/contents"
_GH_RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}"


def _gh_headers(auth: bool = False) -> dict:
    h = {"User-Agent": "Mantice/1.0", "Accept": "application/vnd.github.v3+json"}
    if auth and GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h


def _fetch_shared_manifest() -> dict:
    """Fetch shared/manifest.json from GitHub raw URL. Returns {} on any error."""
    try:
        req = urllib.request.Request(f"{_GH_RAW_BASE}/shared/manifest.json",
                                     headers={"User-Agent": "Mantice/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {}


def _update_shared_manifest(updates: dict) -> None:
    """Merge updates into shared/manifest.json on GitHub (creates if absent). No-op if no token."""
    if not GITHUB_TOKEN:
        return
    manifest: dict = {}
    sha: str | None = None
    try:
        req = urllib.request.Request(f"{_GH_API_BASE}/shared/manifest.json",
                                     headers=_gh_headers(auth=True))
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
            sha = data.get("sha")
            manifest = json.loads(base64.b64decode(data["content"]).decode())
    except Exception:
        pass
    manifest.update(updates)
    payload: dict = {
        "message": "Update shared preset manifest",
        "content": base64.b64encode(json.dumps(manifest, indent=2, sort_keys=True).encode()).decode(),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    req = urllib.request.Request(
        f"{_GH_API_BASE}/shared/manifest.json",
        data=json.dumps(payload).encode(),
        method="PUT",
        headers={**_gh_headers(auth=True), "Content-Type": "application/json"},
    )
    urllib.request.urlopen(req)


def _github_content_exists(repo_path: str) -> bool:
    req = urllib.request.Request(
        f"{_GH_API_BASE}/{repo_path}?ref={GITHUB_BRANCH}",
        headers=_gh_headers(auth=True),
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def _github_put_content(repo_path: str, content: bytes, message: str, *, skip_existing: bool = False) -> None:
    """Create a repository file through GitHub's Contents API."""
    if skip_existing and _github_content_exists(repo_path):
        return
    payload = {
        "message": message,
        "content": base64.b64encode(content).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }
    req = urllib.request.Request(
        f"{_GH_API_BASE}/{repo_path}",
        data=json.dumps(payload).encode("utf-8"),
        method="PUT",
        headers={**_gh_headers(auth=True), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        if response.status not in (200, 201):
            raise RuntimeError(f"GitHub API returned {response.status} for {repo_path}")


def _publish_shared_wavetables(preset_data: dict) -> list[dict]:
    """Publish local wavetable sources by content hash and rewrite preset references."""
    published = []
    for layer in preset_data.get("layers", []):
        if layer.get("type") != "wavetable":
            continue
        source = str(layer.get("wavetable_source") or "")
        if not re.match(r"^[\w\-./]+\.wav$", source) or ".." in source:
            raise ValueError(f"Invalid wavetable source: {source or 'missing'}")
        local_path = (_SAMPLES_DIR / source).resolve()
        if _SAMPLES_DIR.resolve() not in local_path.parents or not local_path.is_file():
            raise ValueError(f"Wavetable file is unavailable: {source}")
        content = local_path.read_bytes()
        if len(content) > 16 * 1024 * 1024:
            raise ValueError(f"Wavetable is too large to share: {local_path.name}")
        digest = hashlib.sha256(content).hexdigest()
        repo_path = f"shared/wavetables/{digest}.wav"
        _github_put_content(repo_path, content, f"Add shared wavetable: {local_path.stem}", skip_existing=True)
        original_name = str(layer.get("wavetable_name") or local_path.stem)
        layer["wavetable_source"] = repo_path
        layer["wavetable_name"] = original_name
        layer["wavetable_sha256"] = digest
        published.append({"sha256": digest, "path": repo_path, "name": original_name})
    return published


def _materialize_shared_wavetables(preset_data: dict) -> None:
    """Download repository-backed tables into the runtime cache and rewrite local paths."""
    for layer in preset_data.get("layers", []):
        if layer.get("type") != "wavetable":
            continue
        source = str(layer.get("wavetable_source") or "")
        match = re.fullmatch(r"shared/wavetables/([a-f0-9]{64})\.wav", source)
        if not match:
            continue
        digest = match.group(1)
        relative = f"wavetables/shared/{digest}.wav"
        destination = _SAMPLES_DIR / relative
        if not destination.exists():
            req = urllib.request.Request(f"{_GH_RAW_BASE}/{source}", headers={"User-Agent": "Mantice/1.0"})
            with urllib.request.urlopen(req, timeout=20) as response:
                content = response.read(16 * 1024 * 1024 + 1)
            if len(content) > 16 * 1024 * 1024:
                raise ValueError("Shared wavetable exceeds the 16 MB limit")
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("Shared wavetable hash verification failed")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".tmp")
            temporary.write_bytes(content)
            os.replace(temporary, destination)
        layer["wavetable_source"] = relative


def _find_all_presets() -> list[dict]:
    """Scan preset directories and return metadata list with source field."""
    import yaml as _yaml
    presets = []

    def _parse(yaml_file):
        name, tags = yaml_file.stem, []
        try:
            with yaml_file.open(encoding="utf-8") as f:
                raw = _yaml.safe_load(f)
            if raw:
                name = raw.get("name") or (raw.get("meta") or {}).get("name") or name
                tags = (raw.get("meta") or {}).get("tags", [])
        except Exception:
            pass
        return name, tags

    # Official presets — skip generated/ folder
    for yaml_file in sorted(_PRESETS_DIR.rglob("*.yaml")):
        rel = yaml_file.relative_to(_PRESETS_DIR)
        if rel.parts[0] == "generated":
            continue
        category = rel.parts[0] if len(rel.parts) > 1 else "uncategorized"
        name, tags = _parse(yaml_file)
        presets.append({"name": name, "category": category, "tags": tags,
                        "path": str(yaml_file), "filename": yaml_file.name, "source": "official"})

    # Community presets — fetch live from GitHub Contents API so new shares appear immediately
    # (Render's local shared/ folder is stale until next deploy)
    try:
        manifest = _fetch_shared_manifest()

        gh_req = urllib.request.Request(
            f"{_GH_API_BASE}/shared",
            headers=_gh_headers(auth=bool(GITHUB_TOKEN))
        )
        with urllib.request.urlopen(gh_req, timeout=6) as resp:
            files = json.loads(resp.read().decode())
        for f in files:
            if not isinstance(f, dict):
                continue
            fname = f.get("name", "")
            if not fname.endswith(".yaml") or fname in (".gitkeep.yaml", ".gitkeep"):
                continue
            stem = fname[:-5]
            # Manifest name takes priority; fall back to filename-derived name (without # suffix)
            if stem in manifest:
                manifest_entry = manifest[stem]
                # Handle both old (string) and new (object) manifest formats
                if isinstance(manifest_entry, str):
                    display_name = manifest_entry
                elif isinstance(manifest_entry, dict):
                    display_name = manifest_entry.get("name", stem)
                else:
                    display_name = str(manifest_entry)  # Fallback for unexpected types
            else:
                # Derive clean name from filename without # suffix
                base_name = re.sub(r'_\d{8}_[a-f0-9]+$', '', stem).replace('_', ' ').strip()
                display_name = base_name or stem
            presets.append({
                "name": display_name or stem,
                "category": "community",
                "tags": [],
                "id": stem,
                "path": f"shared/{fname}",
                "filename": fname,
                "source": "community"
            })
    except Exception:
        # Fallback: scan local shared/ dir (available after deploy)
        if _SHARED_DIR.exists():
            manifest = _fetch_shared_manifest()
            for yaml_file in sorted(_SHARED_DIR.glob("*.yaml")):
                stem = yaml_file.stem
                name, tags = _parse(yaml_file)
                if stem in manifest:
                    # Handle both old and new manifest formats
                    manifest_entry = manifest[stem]
                    if isinstance(manifest_entry, str):
                        display_name = manifest_entry
                    elif isinstance(manifest_entry, dict):
                        display_name = manifest_entry.get("name", stem)
                    else:
                        display_name = str(manifest_entry)
                else:
                    # Derive clean name from filename without # suffix
                    base_name = re.sub(r'_\d{8}_[a-f0-9]+$', '', stem).replace('_', ' ').strip()
                    display_name = base_name or name
                presets.append({
                    "name": display_name or name,
                    "category": "community",
                    "tags": tags,
                    "id": stem,
                    "path": str(yaml_file),
                    "filename": yaml_file.name,
                    "source": "community"
                })

    return presets


def _preset_to_ui_params(preset: dict) -> dict:
    """Extract editable parameters from a loaded preset for the UI."""
    layers_info = []
    for i, layer in enumerate(preset.get("layers", [])):
        layers_info.append({
            "index": i,
            "name": layer.get("name", f"Layer {i}"),
                "type": layer.get("type", "fm"),
                "source": layer.get("source", "singing_bowl.ogg"),
                "grain_size": layer.get("grain_size", 80),
                "density": layer.get("density", 15),
                "pitch_spread": layer.get("pitch_spread", 0.3),
                "position": layer.get("position", 0.5),
                "scatter": layer.get("scatter", 0.5),
                "envelope": layer.get("envelope", "hann"),
                "wavetable_source": layer.get("wavetable_source", ""),
                "wavetable_frame_size": layer.get("wavetable_frame_size", 2048),
                "wavetable_position": layer.get("wavetable_position", 0.0),
                "wavetable_scan_start": layer.get("wavetable_scan_start", 0.0),
                "wavetable_scan_end": layer.get("wavetable_scan_end", 1.0),
                "wavetable_scan_rate": layer.get("wavetable_scan_rate", 0.01),
                "wavetable_scan_mode": layer.get("wavetable_scan_mode", "pingpong"),
                "wavetable_detune_cents": layer.get("wavetable_detune_cents", 7.0),
                "wavetable_name": layer.get("wavetable_name", ""),
                "wavetable_sha256": layer.get("wavetable_sha256", ""),
                "wavetable_source_url": layer.get("wavetable_source_url", ""),
                "wavetable_creator": layer.get("wavetable_creator", ""),
                "wavetable_license": layer.get("wavetable_license", ""),
                "root": layer.get("root", 100),
                "tuning_degree": layer.get("tuning_degree", "unison"),
                "voices": layer.get("voices", 4),
                "ratios": layer.get("ratios", [1.0]),
                "fm_ratios": layer.get("fm_ratios", [1.0]),
                "fm_index": layer.get("fm_index", 0.5),
                "amp_min": layer.get("amp_min", 0.1),
                "amp_max": layer.get("amp_max", 0.4),
                "drift": layer.get("drift", 0.002),
                "volume_db": float(layer.get("volume_db", 0.0)),
                "band": layer.get("band", "mid"),
                "quadrant": layer.get("quadrant", "center"),
                "trajectory_x": layer.get("trajectory_x", "drift"),
                "trajectory_y": layer.get("trajectory_y", "none"),
                "speed": layer.get("speed", 0.01),
                "spatial_motion": {
                    "quadrant": layer.get("quadrant", "center"),
                    "trajectory_x": layer.get("trajectory_x", "drift"),
                    "trajectory_y": layer.get("trajectory_y", "none"),
                    "speed": layer.get("speed", 0.01),
                },
                "pan": float(layer.get("pan", 0.0)),
                "width": float(layer.get("width", 1.0)),
                "spread": float(layer.get("spread", 1.0)),
                "blend": float(layer.get("blend", 1.0)),
                "muted": bool(layer.get("muted", False)) or not bool(layer.get("enabled", True)),
                "harmonics": layer.get("harmonics", 4),
                "harmonic_decay": layer.get("harmonic_decay", 0.7),
                "noise_amount": layer.get("noise_amount", 0.0),
                "noise_color": layer.get("noise_color", "pink"),
                "elevation": layer.get("elevation", 0.0),
                "elevation_motion": layer.get("elevation_motion", "static"),
                "elevation_speed": layer.get("elevation_speed", 0.1),
                "elevation_range": layer.get("elevation_range", 60.0),
                "chorus_rate": layer.get("chorus_rate", 0.5),
                "chorus_depth": layer.get("chorus_depth", 0.005),
                "chorus_mix": layer.get("chorus_mix", 0.0),
                "chorus_voices": layer.get("chorus_voices", 2),
                "flanger_wet": layer.get("flanger_wet", 0.0),
                "flanger_rate": layer.get("flanger_rate", 0.25),
                "flanger_depth": layer.get("flanger_depth", 0.5),
                "flanger_feedback": layer.get("flanger_feedback", 0.4),
                "phaser_wet": layer.get("phaser_wet", 0.0),
                "phaser_rate": layer.get("phaser_rate", 0.5),
                "phaser_depth": layer.get("phaser_depth", 0.7),
                "phaser_center_hz": layer.get("phaser_center_hz", 800.0),
                "phaser_feedback": layer.get("phaser_feedback", 0.0),
                "phaser_stages": layer.get("phaser_stages", 4),
                "filter_type": layer.get("filter_type", "off"),
                "filter_cutoff": layer.get("filter_cutoff", 2000),
                "filter_resonance": layer.get("filter_resonance", 1.0),
                "filter_lfo_rate": layer.get("filter_lfo_rate", 0.1),
                "filter_lfo_depth": layer.get("filter_lfo_depth", 0.0),
                "filter_lfo_shape": layer.get("filter_lfo_shape", "sine"),
                "filter_vowel": layer.get("filter_vowel", "a"),
                "waveform": layer.get("waveform", "saw"),
                "detune_cents": layer.get("detune_cents", 8.0),
                "sub_mix": layer.get("sub_mix", 0.3),
                "distortion_drive": layer.get("distortion_drive", 0.0),
                "distortion_type": layer.get("distortion_type", "soft"),
                "position_mode": layer.get("position_mode", "linear"),
                "position_chaos": layer.get("position_chaos", 0.3),
                "automation": layer.get("automation") or {},
            })

    binaural = preset.get("binaural") or {}
    reverb = preset.get("reverb") or {}
    earth = preset.get("earth") or {}
    air = preset.get("air") or {}
    shimmer = preset.get("shimmer") or {}
    flanger = preset.get("flanger") or {}
    master = preset.get("master", {}) or {}
    eq = master.get("eq", {}) or {}
    comp = master.get("comp", {}) or {}

    return {
        "name": preset.get("meta", {}).get("name", "MANTICE"),
        "duration": preset.get("duration", 60),
        "spatial_depth": preset.get("spatial_depth", 1.0),
        "spatial_wet": preset.get("spatial_wet", 0.7),
        "saturation": preset.get("saturation", 0.3),
        "master": {
            "eq_low_cut_hz":  float(eq.get("low_cut_hz", 20.0)),
            "eq_bass_db":     float(eq.get("bass_db", 0.0)),
            "eq_bass_hz":     float(eq.get("bass_hz", 100.0)),
            "eq_lo_mid_db":   float(eq.get("lo_mid_db", eq.get("mid_db", 0.0))),
            "eq_lo_mid_hz":   float(eq.get("lo_mid_hz", 250.0)),
            "eq_lo_mid_q":    float(eq.get("lo_mid_q", 1.0)),
            "eq_hi_mid_db":   float(eq.get("hi_mid_db", 0.0)),
            "eq_hi_mid_hz":   float(eq.get("hi_mid_hz", 2500.0)),
            "eq_hi_mid_q":    float(eq.get("hi_mid_q", 1.0)),
            "eq_air_db":      float(eq.get("air_db", 0.0)),
            "eq_air_hz":      float(eq.get("air_hz", 10000.0)),
            "comp_threshold_db": float(comp.get("threshold_db", -18.0)),
            "comp_ratio":        float(comp.get("ratio", 2.5)),
            "comp_attack_ms":    float(comp.get("attack_ms", 50.0)),
            "comp_release_ms":   float(comp.get("release_ms", 200.0)),
            "comp_knee_db":      float(comp.get("knee_db", 3.0)),
            "comp_makeup_db":    float(comp.get("makeup_db", 4.0)),
            "output_gain_db":    float(master.get("output_gain_db", 3.0)),
        },
        "layers": layers_info,
        "binaural": {
            "enabled": binaural.get("enabled", False),
            "method": binaural.get("method", "detune"),
            "beat_hz": binaural.get("beat_hz", 6.0),
            "carrier_hz": binaural.get("carrier_hz", 200.0),
            "carrier_amplitude": binaural.get("carrier_amplitude", 0.15),
        },
        "reverb": {
            "enabled": reverb.get("enabled", False),
            "space": reverb.get("space", "cathedral"),
            "mix": reverb.get("mix", 0.3),
            "decay_trim": reverb.get("decay_trim", 1.0),
            "pre_delay_ms": reverb.get("pre_delay_ms", 0.0),
            "modulation_depth": reverb.get("modulation_depth", 0.0),
        },
        "earth": {
            "enabled": earth.get("enabled", False),
            "tectonic_frequency": earth.get("tectonic_frequency", 18),
            "pressure": earth.get("pressure", 0.4),
            "movement": earth.get("movement", 0.02),
        },
        "air": {
            "enabled": air.get("enabled", False),
            "intensity": air.get("intensity", 0.12),
            "movement": air.get("movement", 0.01),
            "turbulence": air.get("turbulence", 0.04),
        },
        "shimmer": {
            "wet":              float(shimmer.get("wet", 0.0)),
            "pitch_semitones":  float(shimmer.get("pitch_semitones", 12.0)),
            "feedback":         float(shimmer.get("feedback", 0.5)),
        },
        "flanger": {
            "wet":      float(flanger.get("wet", 0.0)),
            "rate":     float(flanger.get("rate", 0.25)),
            "depth":    float(flanger.get("depth", 0.5)),
            "feedback": float(flanger.get("feedback", 0.4)),
        },
        "automation": preset.get("automation") or {},
    }


def _ui_params_to_preset(params: dict) -> dict:
    """Convert UI parameter dict back to engine-compatible preset dict."""
    layers = []
    for l in params.get("layers", []):
        layers.append({
            "name": l.get("name", "Layer"),
            "muted": bool(l.get("muted", False)),
            "type": l.get("type", "fm"),
            "source": l.get("source", "singing_bowl.ogg"),
            "grain_size": float(l.get("grain_size", 80)),
            "density": float(l.get("density", 15)),
            "pitch_spread": float(l.get("pitch_spread", 0.3)),
            "position": float(l.get("position", 0.5)),
            "scatter": float(l.get("scatter", 0.5)),
            "envelope": l.get("envelope", "hann"),
            "wavetable_source": l.get("wavetable_source", ""),
            "wavetable_frame_size": int(l.get("wavetable_frame_size", 2048)),
            "wavetable_position": float(l.get("wavetable_position", 0.0)),
            "wavetable_scan_start": float(l.get("wavetable_scan_start", 0.0)),
            "wavetable_scan_end": float(l.get("wavetable_scan_end", 1.0)),
            "wavetable_scan_rate": float(l.get("wavetable_scan_rate", 0.01)),
            "wavetable_scan_mode": l.get("wavetable_scan_mode", "pingpong"),
            "wavetable_detune_cents": float(l.get("wavetable_detune_cents", 7.0)),
            "wavetable_name": l.get("wavetable_name", ""),
            "wavetable_sha256": l.get("wavetable_sha256", ""),
            "wavetable_source_url": l.get("wavetable_source_url", ""),
            "wavetable_creator": l.get("wavetable_creator", ""),
            "wavetable_license": l.get("wavetable_license", ""),
            "root": float(l.get("root", 100)),
            "tuning_degree": l.get("tuning_degree", "unison"),
            "voices": int(l.get("voices", 4)),
            "ratios": l.get("ratios", [1.0]),
            "fm_ratios": l.get("fm_ratios", [1.0]),
            "fm_index": float(l.get("fm_index", 0.5)),
            "amp_min": float(l.get("amp_min", 0.1)),
            "amp_max": float(l.get("amp_max", 0.4)),
            "drift": float(l.get("drift", 0.002)),
            "volume_db": float(l.get("volume_db", 0.0)),
            "band": l.get("band", "mid"),
            "quadrant": l.get("quadrant", "center"),
            "trajectory_x": l.get("trajectory_x", "drift"),
            "trajectory_y": l.get("trajectory_y", "none"),
            "speed": float(l.get("speed", 0.01)),
            "pan": float(l.get("pan", 0.0)),
            "width": float(l.get("width", 1.0)),
            "spread": float(l.get("spread", 1.0)),
            "blend": float(l.get("blend", 1.0)),
            "flanger_wet":      float(l.get("flanger_wet", 0.0)),
            "flanger_rate":     float(l.get("flanger_rate", 0.25)),
            "flanger_depth":    float(l.get("flanger_depth", 0.5)),
            "flanger_feedback": float(l.get("flanger_feedback", 0.4)),
            "phaser_wet":       float(l.get("phaser_wet", 0.0)),
            "phaser_rate":      float(l.get("phaser_rate", 0.5)),
            "phaser_depth":     float(l.get("phaser_depth", 0.7)),
            "phaser_center_hz": float(l.get("phaser_center_hz", 800.0)),
            "phaser_feedback":  float(l.get("phaser_feedback", 0.0)),
            "phaser_stages":    int(l.get("phaser_stages", 4)),
            "harmonics": int(l.get("harmonics", 4)),
            "harmonic_decay": float(l.get("harmonic_decay", 0.7)),
            "noise_amount": float(l.get("noise_amount", 0.0)),
            "noise_color": l.get("noise_color", "pink"),
            "elevation": float(l.get("elevation", 0.0)),
            "elevation_motion": l.get("elevation_motion", "static"),
            "elevation_speed": float(l.get("elevation_speed", 0.1)),
            "elevation_range": float(l.get("elevation_range", 60.0)),
            "chorus_rate": float(l.get("chorus_rate", 0.5)),
            "chorus_depth": float(l.get("chorus_depth", 0.005)),
            "chorus_mix": float(l.get("chorus_mix", 0.0)),
            "chorus_voices": int(l.get("chorus_voices", 2)),
            "filter_type": l.get("filter_type", "off"),
            "filter_cutoff": float(l.get("filter_cutoff", 2000)),
            "filter_resonance": float(l.get("filter_resonance", 1.0)),
            "filter_lfo_rate": float(l.get("filter_lfo_rate", 0.1)),
            "filter_lfo_depth": float(l.get("filter_lfo_depth", 0.0)),
            "filter_lfo_shape": l.get("filter_lfo_shape", "sine"),
            "filter_vowel": l.get("filter_vowel", "a"),
            "waveform": l.get("waveform", "saw"),
            "detune_cents": float(l.get("detune_cents", 8.0)),
            "sub_mix": float(l.get("sub_mix", 0.3)),
            "distortion_drive": float(l.get("distortion_drive", 0.0)),
            "distortion_type": l.get("distortion_type", "soft"),
            "position_mode": l.get("position_mode", "linear"),
            "position_chaos": float(l.get("position_chaos", 0.3)),
            "automation": l.get("automation") or {},
        })
    binaural = params.get("binaural", {})
    reverb = params.get("reverb", {})
    earth = params.get("earth", {})
    air = params.get("air", {})
    shimmer_ui = params.get("shimmer", {})
    flanger_ui = params.get("flanger", {})
    master_ui = params.get("master", {})

    preset = {
        "meta": {
            "name": params.get("name", "Untitled"),
        },
        "seed": None,
        "duration": float(params.get("duration", 60)),
        "spatial_depth": float(params.get("spatial_depth", 1.0)),
        "spatial_wet": float(params.get("spatial_wet", 0.7)),
        "saturation": float(params.get("saturation", 0.3)),
        "master": {
            "eq": {
                "low_cut_hz": float(master_ui.get("eq_low_cut_hz", 20.0)),
                "bass_db":    float(master_ui.get("eq_bass_db", 0.0)),
                "bass_hz":    float(master_ui.get("eq_bass_hz", 100.0)),
                "lo_mid_db":  float(master_ui.get("eq_lo_mid_db", 0.0)),
                "lo_mid_hz":  float(master_ui.get("eq_lo_mid_hz", 250.0)),
                "lo_mid_q":   float(master_ui.get("eq_lo_mid_q", 1.0)),
                "hi_mid_db":  float(master_ui.get("eq_hi_mid_db", 0.0)),
                "hi_mid_hz":  float(master_ui.get("eq_hi_mid_hz", 2500.0)),
                "hi_mid_q":   float(master_ui.get("eq_hi_mid_q", 1.0)),
                "air_db":     float(master_ui.get("eq_air_db", 0.0)),
                "air_hz":     float(master_ui.get("eq_air_hz", 10000.0)),
            },
            "comp": {
                "threshold_db": float(master_ui.get("comp_threshold_db", -18.0)),
                "ratio":        float(master_ui.get("comp_ratio", 2.5)),
                "attack_ms":    float(master_ui.get("comp_attack_ms", 50.0)),
                "release_ms":   float(master_ui.get("comp_release_ms", 200.0)),
                "knee_db":      float(master_ui.get("comp_knee_db", 3.0)),
                "makeup_db":    float(master_ui.get("comp_makeup_db", 4.0)),
            },
            "output_gain_db": float(master_ui.get("output_gain_db", 0.0)),
        },
        "swarm_density": 0.5,
        "layers": layers,
        "tuning_mode":      params.get("tuning_mode", "free"),
        "tonic_hz":         float(params.get("tonic_hz", 432.0)),
        "tuning_system_ji": params.get("tuning_system_ji", "5limit_ji"),
        "pure_mode":        bool(params.get("pure_mode", False)),
        "binaural": binaural if binaural.get("enabled") else None,
        "reverb": reverb if reverb.get("enabled") else None,
        "earth": earth if earth.get("enabled") else None,
        "air": air if air.get("enabled") else None,
        "shimmer": {
            "wet":             float(shimmer_ui.get("wet", 0.0)),
            "pitch_semitones": float(shimmer_ui.get("pitch_semitones", 12.0)),
            "feedback":        float(shimmer_ui.get("feedback", 0.5)),
        } if float(shimmer_ui.get("wet", 0.0)) > 0 else None,
        "flanger": {
            "wet":      float(flanger_ui.get("wet", 0.0)),
            "rate":     float(flanger_ui.get("rate", 0.25)),
            "depth":    float(flanger_ui.get("depth", 0.5)),
            "feedback": float(flanger_ui.get("feedback", 0.4)),
        } if float(flanger_ui.get("wet", 0.0)) > 0 else None,
        "automation": params.get("automation") or {},
    }
    return preset


# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title="MANTICE", version="19.0")

# CORS — allow GitHub Pages and local dev origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten to your GitHub Pages URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Length", "X-Export-Path"],
)

# Load pitch detection cache at startup, then scan new files in background
_load_pitch_cache()
import threading as _threading
_threading.Thread(target=_background_pitch_scan, daemon=True).start()


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = _STATIC_DIR / "index.html"
    return html_path.read_text(encoding="utf-8")


@app.get("/favicon.ico")
async def favicon_ico():
    """Serve favicon.ico to avoid 404 errors in browser console."""
    favicon_path = _STATIC_DIR / "favicon.ico"
    return FileResponse(favicon_path, media_type="image/x-icon")


@app.get("/favicon.png")
async def favicon_png():
    """Serve PNG favicon for modern browsers."""
    favicon_path = _STATIC_DIR / "favicon.png"
    return FileResponse(favicon_path, media_type="image/png")


@app.get("/api/presets")
async def list_presets():
    loop = asyncio.get_event_loop()
    presets = await loop.run_in_executor(None, _find_all_presets)
    return JSONResponse(presets)


@app.get("/api/version")
async def get_version():
    """Return the running git commit SHA and GitHub repo URL."""
    import subprocess
    sha = os.environ.get("GIT_SHA", "")
    if not sha:
        try:
            sha = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(Path(__file__).parent.parent),
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except Exception:
            sha = "unknown"
    return JSONResponse({
        "sha": sha,
        "repo": "https://github.com/bassimatte/mantice",
    })


@app.get("/api/meters")
async def get_meters():
    """Return per-layer peak meter levels in dBFS (decaying envelope, ~-100 = silent)."""
    global engine
    if engine is None:
        return JSONResponse({"layers": []})
    return JSONResponse({"layers": engine.get_peak_meters()})


@app.get("/api/samples")
async def list_samples():
    """List available audio samples for granular synthesis (built-in + Freesound cache)."""
    import json as _json
    label_map = {}
    if (_SAMPLES_DIR / "manifest.json").exists():
        try:
            with open(_SAMPLES_DIR / "manifest.json") as f:
                for e in _json.load(f):
                    label_map[e["file"]] = e.get("label", "").replace("_", " ").title()
        except Exception:
            pass

    # Built-in samples
    files = sorted(f for f in os.listdir(_SAMPLES_DIR) if f.endswith((".ogg", ".wav", ".flac", ".mp3")))
    samples = [{"file": f, "label": label_map.get(f) or f.rsplit(".", 1)[0].replace("_", " ").title(), "source": "builtin"} for f in files]

    # Freesound cached samples
    if _FS_CACHE_DIR.exists():
        cache_manifest_path = _FS_CACHE_DIR / "manifest.json"
        cache_meta = {}
        if cache_manifest_path.exists():
            try:
                with open(cache_manifest_path) as f:
                    cache_meta = {str(e["id"]): e for e in _json.load(f)}
            except Exception:
                pass
        for f in sorted(os.listdir(_FS_CACHE_DIR)):
            if f.endswith((".ogg", ".wav", ".flac", ".mp3")):
                fid = f.rsplit(".", 1)[0]
                meta = cache_meta.get(fid, {})
                label = meta.get("name", fid)[:40]
                user = meta.get("username", "")
                samples.append({"file": f"freesound_cache/{f}", "label": f"FS: {label}", "user": user, "source": "freesound"})

    return {"samples": samples}


@app.post("/api/wavetables/import")
async def import_wavetable(request: Request):
    """Validate and store an uploaded WAV as a local 2048-sample-frame wavetable."""
    import soundfile as sf

    payload = await request.body()
    if not payload:
        return JSONResponse({"ok": False, "error": "Empty WAV file"}, status_code=400)
    if len(payload) > 16 * 1024 * 1024:
        return JSONResponse({"ok": False, "error": "Wavetable must be smaller than 16 MB"}, status_code=413)
    original = request.headers.get("x-filename", "wavetable.wav")
    if not original.lower().endswith(".wav"):
        return JSONResponse({"ok": False, "error": "Only WAV files are supported"}, status_code=400)
    try:
        audio, sample_rate = sf.read(io.BytesIO(payload), dtype="float32", always_2d=True)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"Invalid WAV file: {exc}"}, status_code=400)
    if len(audio) < 32:
        return JSONResponse({"ok": False, "error": "Wavetable WAV is too short"}, status_code=400)

    mono = np.mean(audio, axis=1, dtype=np.float32)
    frame_size = 2048
    frame_count = min(256, max(1, len(mono) // frame_size))
    used_samples = frame_count * frame_size
    if len(mono) < frame_size:
        old_x = np.linspace(0.0, 1.0, len(mono), endpoint=False)
        new_x = np.linspace(0.0, 1.0, frame_size, endpoint=False)
        mono = np.interp(new_x, old_x, mono).astype(np.float32)
        used_samples = frame_size
    else:
        mono = mono[:used_samples]

    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(original).stem).strip("_")[:48] or "wavetable"
    filename = f"{safe_stem}_{uuid.uuid4().hex[:8]}.wav"
    _WAVETABLES_DIR.mkdir(parents=True, exist_ok=True)
    destination = _WAVETABLES_DIR / filename
    try:
        sf.write(str(destination), mono, int(sample_rate), format="WAV", subtype="FLOAT")
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"Could not store wavetable: {exc}"}, status_code=500)
    return JSONResponse({
        "ok": True,
        "source": f"wavetables/{filename}",
        "name": Path(original).stem,
        "frame_size": frame_size,
        "frames": frame_count,
        "samples": used_samples,
    })


@app.get("/samples/{filepath:path}")
async def serve_sample(filepath: str):
    """Serve a sample audio file (supports freesound_cache/ subdirectory)."""
    from fastapi.responses import FileResponse
    # Sanitize: only allow safe filenames/subdirs
    if not re.match(r'^[\w\-./]+\.(ogg|wav|flac|mp3)$', filepath) or ".." in filepath:
        return JSONResponse({"error": "Invalid path"}, status_code=400)
    sample_path = _SAMPLES_DIR / filepath
    if not sample_path.exists():
        return JSONResponse({"error": "Not found"}, status_code=404)
    return FileResponse(str(sample_path))


@app.get("/api/sample-pitch/{filepath:path}")
async def get_sample_pitch(filepath: str):
    """Return detected fundamental Hz for a sample. Detects on demand if not cached."""
    if not re.match(r'^[\w\-./]+\.(ogg|wav|flac|mp3)$', filepath) or ".." in filepath:
        return JSONResponse({"hz": None, "error": "Invalid path"}, status_code=400)
    if filepath in _pitch_cache:
        return {"hz": _pitch_cache[filepath], "cached": True}
    # On-demand detection (runs in thread executor to avoid blocking)
    sample_path = _SAMPLES_DIR / filepath
    if not sample_path.exists():
        return JSONResponse({"hz": None, "error": "Not found"}, status_code=404)
    loop = asyncio.get_event_loop()
    hz = await loop.run_in_executor(None, _detect_pitch_hz_sync, str(sample_path))
    _pitch_cache[filepath] = hz
    _save_pitch_cache()
    try:
        from .granular_layer import _PITCH_CACHE as _gl_cache
        _gl_cache[filepath] = hz
    except Exception:
        pass
    return {"hz": hz, "cached": False}


@app.get("/api/freesound/search")
async def freesound_search(q: str, page_size: int = 10):
    """Proxy Freesound search — returns CC0-licensed sounds matching the query."""
    import json as _json
    # Only filter by CC0 license — no duration limit (previews are always ~30s clips regardless)
    filt = urllib.request.quote('license:"Creative Commons 0"')
    url = (f"{FREESOUND_BASE}/search/text/"
           f"?query={urllib.request.quote(q)}"
           f"&filter={filt}"
           f"&sort=rating_desc"
           f"&fields=id,name,duration,previews,username,avg_rating"
           f"&page_size={min(page_size, 15)}"
           f"&token={FREESOUND_API_KEY}")
    try:
        loop = asyncio.get_event_loop()
        def _fetch():
            req = urllib.request.Request(url, headers={"User-Agent": "MANTICE/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return _json.loads(r.read())
        data = await loop.run_in_executor(None, _fetch)
        results = []
        for r in data.get("results", []):
            preview = r["previews"].get("preview-hq-ogg") or r["previews"].get("preview-hq-mp3", "")
            if preview:
                results.append({"id": r["id"], "name": r["name"], "duration": round(r["duration"], 1),
                                 "username": r["username"], "preview_url": preview,
                                 "rating": r.get("avg_rating", 0)})
        return JSONResponse({"ok": True, "results": results})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/freesound/cache")
async def freesound_cache_sound(request: Request):
    """Download a Freesound preview to local cache and return the filename for use in granular layer."""
    import json as _json
    body = await request.json()
    sound_id = str(body.get("id", ""))
    preview_url = body.get("preview_url", "")
    name = body.get("name", sound_id)[:60]
    username = body.get("username", "")

    if not sound_id or not preview_url:
        return JSONResponse({"ok": False, "error": "id and preview_url required"}, status_code=400)
    if not re.match(r'^https://cdn\.freesound\.org/', preview_url):
        return JSONResponse({"ok": False, "error": "Invalid preview URL"}, status_code=400)

    _FS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ext = "ogg" if preview_url.endswith(".ogg") else "mp3"
    filename = f"{sound_id}.{ext}"
    cache_path = _FS_CACHE_DIR / filename
    relative_path = f"freesound_cache/{filename}"

    if not cache_path.exists():
        try:
            loop = asyncio.get_event_loop()
            def _download():
                urllib.request.urlretrieve(preview_url, str(cache_path))
            await loop.run_in_executor(None, _download)
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"Download failed: {e}"}, status_code=500)

    # Update cache manifest
    cache_manifest_path = _FS_CACHE_DIR / "manifest.json"
    cache_manifest = []
    if cache_manifest_path.exists():
        try:
            with open(cache_manifest_path) as f:
                cache_manifest = _json.load(f)
        except Exception:
            pass
    if not any(str(e.get("id")) == sound_id for e in cache_manifest):
        cache_manifest.append({"id": sound_id, "name": name, "username": username, "file": filename, "preview_url": preview_url})
        with open(cache_manifest_path, "w") as f:
            _json.dump(cache_manifest, f, indent=2)

    return JSONResponse({"ok": True, "filename": relative_path, "label": f"FS: {name}"})


@app.get("/api/freesound/load_by_id")
async def freesound_load_by_id(id: str):
    """Fetch a Freesound sound by its ID, cache the preview, and return filename + label.
    Used by the paste-URL feature in the granular UI."""
    if not re.match(r'^\d+$', id):
        return JSONResponse({"ok": False, "error": "Invalid sound ID"}, status_code=400)
    try:
        loop = asyncio.get_event_loop()
        def _fetch():
            url = f"{FREESOUND_BASE}/sounds/{id}/?token={FREESOUND_API_KEY}&fields=name,username,previews"
            with urllib.request.urlopen(url, timeout=10) as resp:
                return json.loads(resp.read())
        data = await loop.run_in_executor(None, _fetch)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Freesound API error: {e}"}, status_code=502)

    preview_url = (data.get("previews") or {}).get("preview-hq-ogg") or \
                  (data.get("previews") or {}).get("preview-hq-mp3")
    if not preview_url:
        return JSONResponse({"ok": False, "error": "No preview URL found"}, status_code=404)

    name = (data.get("name") or id)[:60]
    username = data.get("username", "")

    # Reuse the cache endpoint logic
    _FS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ext = "ogg" if preview_url.endswith(".ogg") else "mp3"
    filename = f"{id}.{ext}"
    cache_path = _FS_CACHE_DIR / filename
    relative_path = f"freesound_cache/{filename}"

    if not cache_path.exists():
        try:
            loop2 = asyncio.get_event_loop()
            def _dl():
                urllib.request.urlretrieve(preview_url, str(cache_path))
            await loop2.run_in_executor(None, _dl)
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"Download failed: {e}"}, status_code=500)

    # Update cache manifest
    import json as _json
    cache_manifest_path = _FS_CACHE_DIR / "manifest.json"
    cache_manifest = []
    if cache_manifest_path.exists():
        try:
            with open(cache_manifest_path) as f:
                cache_manifest = _json.load(f)
        except Exception:
            pass
    if not any(str(e.get("id")) == id for e in cache_manifest):
        cache_manifest.append({"id": id, "name": name, "username": username,
                                "file": filename, "preview_url": preview_url})
        with open(cache_manifest_path, "w") as f:
            _json.dump(cache_manifest, f, indent=2)

    return JSONResponse({"ok": True, "filename": relative_path, "label": f"FS: {name}"})


@app.get("/api/preset/load")
async def load_preset_endpoint(path: str):
    try:
        preset = load_preset(path)
        params = _preset_to_ui_params(preset)
        return JSONResponse({"ok": True, "params": params})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.post("/api/preset/load-yaml")
async def load_preset_yaml_endpoint(request: Request):
    """Accept raw YAML text from a user-uploaded file and return UI params."""
    try:
        body = await request.json()
        yaml_text = body.get("yaml", "")
        if not yaml_text:
            return JSONResponse({"ok": False, "error": "Empty YAML"}, status_code=400)
        preset = load_preset_from_yaml_string(yaml_text)
        params = _preset_to_ui_params(preset)
        name = preset.get("name") or ""
        return JSONResponse({"ok": True, "params": params, "name": name})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.post("/api/render")
async def render_endpoint(request: Request):
    """Render audio, save to exports/ folder, and return as download."""
    body = await request.json()
    params = body.get("params")
    fmt = body.get("format", "wav")
    if not params:
        return JSONResponse({"ok": False, "error": "No params"}, status_code=400)

    try:
        preset = _ui_params_to_preset(params)
        duration = preset["duration"]

        # Determine output quality locally — never mutate global config
        hires = body.get("hires", False)
        out_sr      = 48_000 if hires else 22_050        # output sample rate
        out_bd      = "PCM_24" if hires else "PCM_16"
        mp3_bitrate = 320 if hires else 192

        # Memory limit check: Estimate memory needed for post-processing
        # Post-processing loads full audio buffer: duration * sample_rate * 2 channels * 4 bytes (float32)
        # Plus overhead for convolution reverb (~2-3× audio size) and oversampling (2× temp buffers)
        estimated_audio_mb = (duration * out_sr * 2 * 4) / (1024 * 1024)
        estimated_total_mb = estimated_audio_mb * 4  # Conservative: 4× for reverb + oversampling
        
        # Render.com free tier: 512MB limit, keep render under ~200MB to be safe
        MAX_MEMORY_MB = 200
        
        if estimated_total_mb > MAX_MEMORY_MB:
            max_duration = int((MAX_MEMORY_MB / estimated_total_mb) * duration)
            error_msg = (
                f"Render too long: {duration}s would use ~{estimated_total_mb:.0f}MB (limit: {MAX_MEMORY_MB}MB). "
                f"Maximum duration: {max_duration}s {'(hi-res)' if hires else '(standard)'}. "
                f"For longer renders, use the Python CLI: python main.py --preset your_preset.yaml --duration {duration}"
            )
            print(f"  [render] MEMORY ERROR: {error_msg}")
            return JSONResponse({
                "ok": False, 
                "error": error_msg,
                "max_duration": max_duration,
                "estimated_memory_mb": int(estimated_total_mb)
            }, status_code=413)  # 413 Payload Too Large

        print(f"  [render] Starting {duration}s render ({fmt}, {'hi-res 48k/24b' if hires else '22k/16b'}, ~{estimated_total_mb:.0f}MB)…")

        loop = asyncio.get_event_loop()
        seed = int(body.get("seed", 42))
        render_sr = out_sr  # Declare in outer scope for _encode_audio access

        def _render():
            # Optional memory tracking
            try:
                import psutil
                import os
                process = psutil.Process(os.getpid())
                def log_memory(stage):
                    mem_mb = process.memory_info().rss / 1024 / 1024
                    print(f"  [render] {stage}: {mem_mb:.1f} MB used")
            except ImportError:
                def log_memory(stage):
                    pass  # psutil not available
            
            # Disable FDN reverb in the engine — convolution IR replaces it for renders
            preset_for_render = {**preset}
            reverb_cfg = dict(preset.get("reverb") or {})
            reverb_enabled = reverb_cfg.get("enabled", False)
            if reverb_enabled:
                preset_for_render["reverb"] = {**reverb_cfg, "enabled": False}

            # Capture saturation value and zero it out in the engine — we apply
            # it post-synthesis with 4× oversampling to eliminate alias artefacts.
            sat = float(preset.get("saturation", 0.3))
            preset_for_render["saturation"] = 0.0

            log_memory("Start")
            
            # Import gc at top of function for all paths
            import gc
            
            # MANT-1: Engine synthesizes at target SR directly (no upsample needed)
            print(f"  [render] Creating engine (hires={hires})...")
            nonlocal render_sr
            
            # SEGMENTED RENDERING: Split long renders into chunks to stay under 512MB
            # FIXED: Keep ONE engine alive and stream chunks to file instead of creating
            # fresh engines per segment. This preserves automation continuity, reverb tails,
            # FM phase continuity, and limiter state.
            SEGMENT_DURATION = 60.0  # seconds per segment write (memory management)
            total_duration = preset["duration"]
            
            # Determine if we need segmented rendering (>15s with hi-res)
            use_segments = hires and total_duration > 15.0
            
            if use_segments:
                print(f"  [render] Using streaming render for {total_duration}s @ 48kHz (preserves continuity)")
                import soundfile as sf
                import tempfile
                
                # Create ONE engine for the entire render (preserves all state)
                engine = StreamingDroneEngine(preset_for_render, seed=seed, render_mode=hires)
                render_sr = engine.SR
                total_samples = int(total_duration * render_sr)
                chunk_size = 4096
                
                log_memory(f"Engine created (SR={render_sr})")
                
                # Create temp file for streaming render
                temp_dir = Path(tempfile.mkdtemp(prefix="mantice_render_"))
                temp_path = temp_dir / "render_stream.wav"
                
                try:
                    # Open soundfile for streaming write
                    print(f"  [render] Streaming synthesis to disk (continuous engine)...")
                    with sf.SoundFile(str(temp_path), 'w', render_sr, 2, subtype='PCM_24') as out_file:
                        offset = 0
                        remaining = total_samples
                        segment_samples = int(SEGMENT_DURATION * render_sr)
                        
                        while remaining > 0:
                            # Render one chunk at a time
                            n = min(chunk_size, remaining)
                            chunk = engine.next_chunk(n)
                            
                            # Write immediately to disk (memory efficient)
                            out_file.write(chunk)
                            
                            offset += n
                            remaining -= n
                            
                            # Progress logging every segment
                            if offset % segment_samples < chunk_size:
                                progress_pct = (offset / total_samples) * 100
                                print(f"    [render] {offset / render_sr:.0f}s / {total_samples / render_sr:.0f}s ({progress_pct:.0f}%)")
                                log_memory(f"Synthesis {progress_pct:.0f}%")
                                gc.collect()  # Periodic GC during long renders
                    
                    log_memory("Synthesis complete")
                    
                    # Now read the fully-synthesized file and apply post-effects
                    print(f"  [render] Loading synthesized audio for post-processing...")
                    raw, _ = sf.read(str(temp_path))
                    log_memory("Audio loaded")
                    
                    # Apply post-effects to full buffer
                    if sat > 0.01:
                        print(f"  [render] Oversampled saturation ×4: drive={1.0 + sat * 3.0:.2f}…")
                        raw = oversampled_saturate(raw, sat)
                        log_memory("Saturation complete")
                        gc.collect()
                    
                    if reverb_enabled:
                        space = reverb_cfg.get("space", "cathedral")
                        mix = float(reverb_cfg.get("mix", 0.3))
                        decay_trim = float(reverb_cfg.get("decay_trim", 1.0))
                        print(f"  [render] Convolution reverb: {space} (mix={mix:.2f})…")
                        raw = apply_convolution_reverb(raw, space=space, mix=mix, decay_trim=decay_trim, sr=render_sr)
                        log_memory("Reverb complete")
                        gc.collect()
                    
                finally:
                    # Clean up temp files
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
            
            else:
                # ORIGINAL PATH: Single-pass rendering for short/low-res renders
                engine = StreamingDroneEngine(preset_for_render, seed=seed, render_mode=hires)
                render_sr = engine.SR
                total_samples = int(preset["duration"] * render_sr)
                chunk_size = 4096
                
                log_memory(f"Engine created (SR={render_sr})")
                
                print(f"  [render] Allocating buffer: {total_samples} samples = {total_samples * 8 / 1024 / 1024:.1f} MB...")
                raw = np.zeros((total_samples, 2), dtype=np.float32)
                log_memory("Buffer allocated")
                
                print(f"  [render] Synthesizing...")
                offset = 0
                remaining = total_samples
                while remaining > 0:
                    n = min(chunk_size, remaining)
                    raw[offset:offset+n] = engine.next_chunk(n)
                    offset += n
                    remaining -= n
                    if offset % (render_sr * 10) == 0:
                        progress_pct = (offset / total_samples) * 100
                        print(f"    [render] {offset / render_sr:.0f}s / {total_samples / render_sr:.0f}s ({progress_pct:.0f}%)")
                        log_memory(f"Synthesis {progress_pct:.0f}%")

                log_memory("Synthesis complete")

                # Oversampled saturation — apply on full buffer at final SR (no chunk artefacts)
                if sat > 0.01:
                    print(f"  [render] Oversampled saturation ×4: drive={1.0 + sat * 3.0:.2f}…")
                    raw = oversampled_saturate(raw, sat)
                    log_memory("Saturation complete")

                # Apply convolution reverb against real IR (replaces streaming FDN for renders)
                if reverb_enabled:
                    space      = reverb_cfg.get("space", "cathedral")
                    mix        = float(reverb_cfg.get("mix", 0.3))
                    decay_trim = float(reverb_cfg.get("decay_trim", 1.0))
                    print(f"  [render] Applying IR convolution reverb: space={space} mix={mix:.2f}…")
                    raw = apply_convolution_reverb(raw, space=space, mix=mix, decay_trim=decay_trim, sr=render_sr)
                    log_memory("Reverb complete")

            # Full-buffer true-peak normalize — zero attack lag, zero pumping
            print("  [render] True-peak normalize (ceiling −1 dBFS)…")
            raw = final_limit_normalize(raw, ceiling=0.97)
            log_memory("Normalize complete")

            # TPDF dither before quantisation (adds 1 LSB of shaped noise, eliminates truncation distortion)
            if out_bd == "PCM_24":
                lsb = 1.0 / (1 << 23)
                raw = raw + lsb * (np.random.uniform(-1, 1, raw.shape) + np.random.uniform(-1, 1, raw.shape))

            return np.clip(raw, -1.0, 1.0)  # safety net after dither

        audio = await loop.run_in_executor(None, _render)

        print(f"  [render] Done. Encoding {fmt} @ {render_sr} Hz…")
        import soundfile as sf

        exports_dir = _ROOT / "exports"
        exports_dir.mkdir(exist_ok=True)
        preset_name = params.get("name", "MANTICE") or "MANTICE"
        safe_name = re.sub(r'[^\w\s\-]', '', preset_name).strip() or "MANTICE"
        filename = f"{safe_name}.{fmt}"
        export_path = exports_dir / filename

        def _encode_to_file(audio_arr, path, fmt, sr, bd):
            """Encode audio array directly to disk file. Returns media_type."""
            if fmt == "mp3":
                import lameenc
                pcm = (audio_arr * 32767).clip(-32768, 32767).astype(np.int16)
                encoder = lameenc.Encoder()
                encoder.set_bit_rate(mp3_bitrate)
                encoder.set_in_sample_rate(sr)
                encoder.set_channels(2)
                encoder.set_quality(2)
                data = encoder.encode(pcm.tobytes()) + encoder.flush()
                # Convert bytearray to bytes for write
                if isinstance(data, bytearray):
                    data = bytes(data)
                with open(str(path), "wb") as f:
                    f.write(data)
                return "audio/mpeg"
            else:
                subtypes = {"wav": bd, "flac": bd, "ogg": "VORBIS"}
                sf.write(str(path), audio_arr, sr, format=fmt.upper(), subtype=subtypes.get(fmt, bd))
                media = {"wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg"}
                return media.get(fmt, "application/octet-stream")

        media_type = await loop.run_in_executor(None, _encode_to_file, audio, export_path, fmt, render_sr, out_bd)
        
        file_size_kb = export_path.stat().st_size // 1024
        print(f"  [render] Saved: {export_path} ({file_size_kb} KB)")

        # Stream from disk instead of loading into memory
        # Use Content-Disposition header manually to avoid FileResponse encoding issues
        from urllib.parse import quote
        
        return FileResponse(
            path=str(export_path),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}',
                "X-Export-Path": str(export_path),
            }
        )
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"  [render] ERROR: {error_detail}")
        return JSONResponse({"ok": False, "error": str(e), "traceback": error_detail}, status_code=500)


@app.post("/api/preview-audio")
async def preview_audio(request: Request):
    """Render a short preview and return as WAV for WebAudio playback."""
    body = await request.json()
    params = body.get("params")
    if not params:
        return JSONResponse({"ok": False, "error": "No params"}, status_code=400)

    try:
        preset = _ui_params_to_preset(params)
        # Short preview for fast response — 5 seconds max
        preset["duration"] = min(float(params.get("duration", 60)), 5.0)

        # Run CPU-heavy render in thread to avoid blocking the event loop
        loop = asyncio.get_event_loop()

        def _render_preview():
            engine = StreamingDroneEngine(preset)
            sr = config.STREAM_SAMPLE_RATE
            total_samples = int(preset["duration"] * sr)
            chunks, remaining = [], total_samples
            while remaining > 0:
                n = min(2048, remaining)
                chunks.append(engine.next_chunk(n))
                remaining -= n
            return np.concatenate(chunks, axis=0)

        audio = await loop.run_in_executor(None, _render_preview)

        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, audio, config.STREAM_SAMPLE_RATE, format="WAV", subtype="PCM_16")
        buf.seek(0)

        return StreamingResponse(buf, media_type="audio/wav")
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/generate")
async def generate_endpoint(request: Request):
    """Generate a random preset and return its parameters."""
    body = await request.json()
    mood = body.get("mood")
    seed = body.get("seed")
    allowed_types = body.get("allowed_types") if isinstance(body.get("allowed_types"), list) else None
    harmonic_mode = bool(body.get("harmonic_mode", False))
    harmonic_key = str(body.get("harmonic_key", "C"))
    harmonic_scale = str(body.get("harmonic_scale", "major"))
    intent = body.get("intent") if isinstance(body.get("intent"), dict) else None
    strategy = str(body.get("strategy") or "scratch")
    locks = {str(value) for value in (body.get("locks") or [])}
    base_params = body.get("base_params") if isinstance(body.get("base_params"), dict) else None
    try:
        import copy, yaml as _yaml, tempfile
        effective_intent = dict(intent or {})
        if strategy == "contrast":
            effective_intent = {key: 1.0 - float(value) for key, value in effective_intent.items()}

        if strategy == "variation" and base_params:
            preset_data = mutate_preset(_ui_params_to_preset(base_params), amount=0.24, seed=seed)
        else:
            preset_data = generate_preset(mood=mood, seed=seed, allowed_types=allowed_types,
                                          harmonic_mode=harmonic_mode,
                                          harmonic_key=harmonic_key,
                                          harmonic_scale=harmonic_scale,
                                          intent=effective_intent)
        with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False, mode='w', encoding='utf-8') as f:
            _yaml.dump(preset_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            tmp_path = Path(f.name)
        try:
            preset = load_preset(tmp_path)
            params = _preset_to_ui_params(preset)
        finally:
            tmp_path.unlink(missing_ok=True)

        if base_params:
            effective_locks = set(locks)
            if strategy == "related":
                effective_locks.update({"harmony", "tuning"})

            base_layers = base_params.get("layers") or []
            generated_layers = params.get("layers") or []
            if "layers" in effective_locks and base_layers and generated_layers:
                structured_layers = []
                for index, base_layer in enumerate(base_layers):
                    layer = copy.deepcopy(generated_layers[index % len(generated_layers)])
                    layer["type"] = base_layer.get("type", layer.get("type", "fm"))
                    layer["name"] = base_layer.get("name", layer.get("name"))
                    if layer["type"] == "granular":
                        layer["source"] = base_layer.get("source", layer.get("source", "singing_bowl.ogg"))
                    structured_layers.append(layer)
                params["layers"] = structured_layers
                generated_layers = structured_layers

            if "harmony" in effective_locks and base_layers and generated_layers:
                for index, layer in enumerate(generated_layers):
                    base_layer = base_layers[index % len(base_layers)]
                    for key in ("root", "ratios", "fm_ratios"):
                        if key in base_layer:
                            layer[key] = copy.deepcopy(base_layer[key])

            if "tuning" in effective_locks:
                for key in ("tuning_system", "tuning_mode", "tonic_hz", "tuning_system_ji", "pure_mode", "tuning_ref_a4"):
                    if key in base_params:
                        params[key] = copy.deepcopy(base_params[key])

            if "space" in effective_locks:
                for key in ("spatial_depth", "spatial_wet", "reverb"):
                    if key in base_params:
                        params[key] = copy.deepcopy(base_params[key])
                for index, layer in enumerate(generated_layers):
                    if not base_layers:
                        break
                    base_layer = base_layers[index % len(base_layers)]
                    for key in ("pan", "width", "quadrant", "spatial_motion", "elevation", "elevation_motion", "elevation_speed", "elevation_range"):
                        if key in base_layer:
                            layer[key] = copy.deepcopy(base_layer[key])

            if "duration" in effective_locks and "duration" in base_params:
                params["duration"] = base_params["duration"]
        return JSONResponse({"ok": True, "params": params})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/mutate")
async def mutate_endpoint(request: Request):
    """Mutate the exact current UI state and return balanced parameter variations."""
    body = await request.json()
    path = body.get("path")
    ui_params = body.get("params")
    amount = float(body.get("amount", 0.3))
    if not path and not ui_params:
        return JSONResponse({"ok": False, "error": "No preset path or params"}, status_code=400)
    try:
        if ui_params:
            current = ui_params
        else:
            current = _preset_to_ui_params(load_preset(Path(path)))
        mutated = mutate_ui_params(current, amount=amount)
        return JSONResponse({"ok": True, "params": mutated})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/export-preset")
async def export_preset_endpoint(request: Request):
    """Export the current preset parameters as a downloadable YAML file."""
    body = await request.json()
    params = body.get("params")
    if not params:
        return JSONResponse({"ok": False, "error": "No params"}, status_code=400)
    try:
        import yaml as _yaml
        preset_data = _ui_params_to_preset(params)
        preset_name = params.get("name", "Untitled Preset")
        yaml_str = _yaml.dump(preset_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        safe_name = "".join(c for c in preset_name if c.isalnum() or c in " -_").strip()
        filename = f"{safe_name}.yaml"
        return Response(
            content=yaml_str.encode("utf-8"),
            media_type="application/x-yaml",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/share")
async def share_preset_endpoint(request: Request):
    """Save current preset YAML to the shared/ folder in the GitHub repo and return its ID."""
    if not GITHUB_TOKEN:
        return JSONResponse({"ok": False, "error": "Sharing not configured on this server"}, status_code=503)
    body = await request.json()
    params = body.get("params")
    author = str(body.get("author") or "").strip()
    if not author or author.lower() == "anonymous":
        creator_adjectives = ("Velvet", "Lunar", "Quiet", "Oblique", "Astral", "Moss", "Copper", "Polar", "Soft", "Phantom", "Amber", "Hidden")
        creator_nouns = ("Circuit", "Nomad", "Signal", "Orchard", "Relay", "Lattice", "Comet", "Scribe", "Bloom", "Vector", "Loom", "Tuner")
        alias_seed = uuid.uuid4().int
        author = f"{creator_adjectives[alias_seed % len(creator_adjectives)]} {creator_nouns[(alias_seed >> 8) % len(creator_nouns)]}"
    parent_id = str(body.get("parent_id") or "").strip()
    if parent_id and not re.match(r'^[a-zA-Z0-9_\-]{1,120}$', parent_id):
        parent_id = ""
    if not params:
        return JSONResponse({"ok": False, "error": "No params"}, status_code=400)
    try:
        import yaml as _yaml
        preset_data = _ui_params_to_preset(params)
        from .generator import _random_name
        # Fetch existing names from manifest to avoid duplicates (best-effort)
        manifest = _fetch_shared_manifest()
        # Handle both old format (string) and new format (dict with metadata)
        existing_names = set()
        for v in manifest.values():
            if isinstance(v, str):
                existing_names.add(v.lower())  # old format: "Preset Name"
            elif isinstance(v, dict):
                existing_names.add(v.get("name", "").lower())  # new format: {"name": "...", "author": "..."}
        
        # Use the user's preset name if it exists and is meaningful, otherwise generate one
        user_name = params.get("name", "").strip()
        generic_names = ['MANTICE', 'Untitled', 'untitled', '']
        if user_name and user_name not in generic_names:
            # User has a meaningful name, use it (add suffix if duplicate)
            preset_name = user_name
            if preset_name.lower() in existing_names:
                # Add a numeric suffix to avoid collision
                for i in range(2, 100):
                    candidate = f"{preset_name} ({i})"
                    if candidate.lower() not in existing_names:
                        preset_name = candidate
                        break
        else:
            # No meaningful name, generate a random one (up to 20 attempts)
            for _ in range(20):
                preset_name = _random_name()
                if preset_name.lower() not in existing_names:
                    break
        
        preset_data["meta"]["name"] = preset_name
        preset_data["meta"]["author"] = author  # NEW: Store author in YAML metadata
        safe_name = "".join(c for c in preset_name if c.isalnum() or c in " -_").strip().replace(" ", "_")
        short_id = uuid.uuid4().hex[:6]
        date_str = datetime.utcnow().strftime("%Y%m%d")
        file_id = f"{safe_name}_{date_str}_{short_id}"
        loop = asyncio.get_event_loop()
        wavetable_assets = await loop.run_in_executor(None, lambda: _publish_shared_wavetables(preset_data))
        yaml_str = _yaml.dump(preset_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        content_b64 = base64.b64encode(yaml_str.encode("utf-8")).decode("ascii")
        api_gh_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/shared/{file_id}.yaml"
        payload = json.dumps({
            "message": f"Share preset: {preset_name}",
            "content": content_b64,
            "branch": GITHUB_BRANCH
        }).encode("utf-8")
        req = urllib.request.Request(
            api_gh_url, data=payload, method="PUT",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
                "User-Agent": "Mantice/1.0",
            }
        )
        def do_gh_put():
            with urllib.request.urlopen(req) as resp:
                return resp.status
        status = await loop.run_in_executor(None, do_gh_put)
        if status not in (200, 201):
            return JSONResponse({"ok": False, "error": f"GitHub API returned {status}"}, status_code=500)
        # Also upload JSON params — enables backend-free loading on GitHub Pages
        shared_params = _preset_to_ui_params(preset_data)
        shared_params["name"] = preset_name
        json_b64 = base64.b64encode(json.dumps(shared_params).encode("utf-8")).decode("ascii")
        json_req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/contents/shared/{file_id}.json",
            data=json.dumps({"message": f"Share preset params: {preset_name}", "content": json_b64, "branch": GITHUB_BRANCH}).encode("utf-8"),
            method="PUT",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
                "User-Agent": "Mantice/1.0",
            }
        )
        try:
            await loop.run_in_executor(None, lambda: urllib.request.urlopen(json_req))
        except Exception:
            pass  # JSON upload is best-effort; YAML is the source of truth
        # Register preset metadata in manifest for gallery
        try:
            manifest_entry = {
                "name": preset_name,
                "author": author,
                "created": datetime.utcnow().isoformat() + "Z",
                "plays": 0,
            }
            if parent_id:
                manifest_entry["parent_id"] = parent_id
            if wavetable_assets:
                manifest_entry["wavetables"] = wavetable_assets
            await loop.run_in_executor(None, lambda: _update_shared_manifest({file_id: manifest_entry}))
        except Exception:
            pass
        return JSONResponse({"ok": True, "id": file_id, "name": preset_name})
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        return JSONResponse({"ok": False, "error": f"GitHub API error {e.code}: {err_body}"}, status_code=500)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/load-shared")
async def load_shared_preset(id: str):
    """Fetch a shared preset YAML from the GitHub repo and return parsed params."""
    if not re.match(r'^[a-zA-Z0-9_\-]{1,120}$', id):
        return JSONResponse({"ok": False, "error": "Invalid ID"}, status_code=400)
    raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/shared/{id}.yaml"
    try:
        import yaml as _yaml
        loop = asyncio.get_event_loop()
        def fetch_yaml():
            req = urllib.request.Request(raw_url, headers={"User-Agent": "Mantice/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read().decode("utf-8")
        yaml_str = await loop.run_in_executor(None, fetch_yaml)
        preset_data = _yaml.safe_load(yaml_str)
        await loop.run_in_executor(None, lambda: _materialize_shared_wavetables(preset_data))
        params = _preset_to_ui_params(preset_data)
        return JSONResponse({"ok": True, "params": params})
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return JSONResponse({"ok": False, "error": "Shared preset not found"}, status_code=404)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/rename-shared")
async def rename_shared_preset(request: Request):
    """Rename a shared preset's display name without changing its file ID (link stays valid)."""
    if not GITHUB_TOKEN:
        return JSONResponse({"ok": False, "error": "Not configured"}, status_code=503)
    body = await request.json()
    preset_id = (body.get("id") or "").strip()
    new_name = (body.get("name") or "").strip()
    if not preset_id or not new_name:
        return JSONResponse({"ok": False, "error": "id and name required"}, status_code=400)
    if not re.match(r'^[a-zA-Z0-9_\-]{1,120}$', preset_id):
        return JSONResponse({"ok": False, "error": "Invalid id"}, status_code=400)
    try:
        manifest = _fetch_shared_manifest()
        # Handle both old format (string) and new format (dict with metadata)
        taken = set()
        for k, v in manifest.items():
            if k != preset_id:
                if isinstance(v, str):
                    taken.add(v.lower())
                elif isinstance(v, dict):
                    taken.add(v.get("name", "").lower())
        if new_name.lower() in taken:
            return JSONResponse({"ok": False, "error": "Name already in use"}, status_code=409)
        
        # Preserve existing metadata if present
        existing_entry = manifest.get(preset_id)
        if isinstance(existing_entry, dict):
            # Update name but keep other metadata
            existing_entry["name"] = new_name
            update_entry = existing_entry
        else:
            # Old format or missing - just store the name
            update_entry = new_name
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: _update_shared_manifest({preset_id: update_entry}))
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/gallery")
async def get_gallery_manifest():
    """Return the full shared presets manifest for the gallery UI."""
    try:
        manifest = _fetch_shared_manifest()

        # A manifest entry can outlive its preset file after manual cleanup.
        # Match the sidebar's source of truth by only exposing IDs that still
        # have a shared YAML file. Fall back to the bundled shared directory
        # when GitHub is unavailable.
        available_ids = None
        try:
            req = urllib.request.Request(
                f"{_GH_API_BASE}/shared",
                headers=_gh_headers(auth=bool(GITHUB_TOKEN)),
            )
            with urllib.request.urlopen(req, timeout=6) as response:
                files = json.loads(response.read().decode())
            available_ids = {
                item.get("name", "")[:-5]
                for item in files if isinstance(item, dict) and item.get("name", "").endswith(".yaml")
            }
        except Exception:
            if _SHARED_DIR.exists():
                available_ids = {path.stem for path in _SHARED_DIR.glob("*.yaml")}

        def preset_summary(preset_id: str) -> dict:
            """Build small, gallery-safe discovery metadata from a local preset."""
            params = None
            json_path = _SHARED_DIR / f"{preset_id}.json"
            yaml_path = _SHARED_DIR / f"{preset_id}.yaml"
            try:
                if json_path.exists():
                    params = json.loads(json_path.read_text(encoding="utf-8"))
                elif yaml_path.exists():
                    import yaml as _yaml
                    raw = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                    params = _preset_to_ui_params(raw or {})
            except Exception:
                params = None
            if not isinstance(params, dict):
                return {}

            layers = [layer for layer in (params.get("layers") or []) if isinstance(layer, dict)]
            roots = []
            synth_types = []
            widths = []
            moving = False
            fingerprint = []
            for index, layer in enumerate(layers):
                root = layer.get("root", layer.get("base_freq"))
                root_value = None
                try:
                    if float(root) > 0:
                        root_value = float(root)
                        roots.append(root_value)
                except (TypeError, ValueError):
                    pass
                synth_type = str(layer.get("type") or "fm").lower()
                if synth_type not in synth_types:
                    synth_types.append(synth_type)
                try:
                    widths.append(float(layer.get("width", 1)))
                except (TypeError, ValueError):
                    pass
                motion = layer.get("spatial_motion") or {}
                trajectory = str(motion.get("trajectory_x") or "none").lower()
                moving = moving or trajectory not in ("none", "static", "off")
                try:
                    volume_db = float(layer.get("volume_db", 0) or 0)
                except (TypeError, ValueError):
                    volume_db = 0
                try:
                    width = float(layer.get("width", 1) or 1)
                except (TypeError, ValueError):
                    width = 1
                try:
                    motion_speed = float(motion.get("speed", 0) or 0)
                except (TypeError, ValueError):
                    motion_speed = 0
                fingerprint.append({
                    "index": index,
                    "name": str(layer.get("name") or f"Layer {index + 1}"),
                    "root": round(root_value, 2) if root_value is not None else None,
                    "volume_db": round(volume_db, 2),
                    "width": round(width, 2),
                    "type": synth_type,
                    "trajectory": trajectory,
                    "motion_speed": round(motion_speed, 4),
                })

            traits = list(synth_types)
            lowest_hz = min(roots) if roots else None
            if lowest_hz is not None and lowest_hz < 80:
                traits.append("sub-heavy")
            if len(layers) >= 4:
                traits.append("dense")
            if widths and sum(widths) / len(widths) > 1.15:
                traits.append("wide")
            if moving:
                traits.append("motion")
            reverb = params.get("reverb") or {}
            if reverb.get("enabled") and float(reverb.get("mix", 0) or 0) >= 0.3:
                traits.append("deep space")
            shimmer = params.get("shimmer") or {}
            if float(shimmer.get("wet", 0) or 0) >= 0.08:
                traits.append("shimmer")
            binaural = params.get("binaural") or {}
            if binaural.get("enabled"):
                traits.append("binaural")
            tuning = params.get("tuning_system_ji") if params.get("tuning_mode") == "ji" else params.get("tuning_system")
            if params.get("tuning_mode") == "ji":
                traits.append("just intonation")

            return {
                "layer_count": len(layers),
                "lowest_hz": round(lowest_hz, 1) if lowest_hz is not None else None,
                "synth_types": synth_types,
                "traits": list(dict.fromkeys(traits))[:6],
                "duration": params.get("duration"),
                "tuning": tuning or "12-TET",
                "complexity": len(layers) + len(traits),
                "fingerprint": fingerprint,
                "reverb_mix": round(float(reverb.get("mix", 0) or 0), 3),
                "shimmer_wet": round(float(shimmer.get("wet", 0) or 0), 3),
            }

        def inferred_created(preset_id: str):
            match = re.search(r"_(\d{8})_[a-f0-9]+$", preset_id)
            if not match:
                return None
            stamp = match.group(1)
            return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}T00:00:00Z"

        # Normalize to new format (dict with metadata)
        normalized = []
        for preset_id, value in manifest.items():
            if available_ids is not None and preset_id not in available_ids:
                continue
            if isinstance(value, str):
                # Old format: just name
                entry = {
                    "id": preset_id,
                    "name": value,
                    "author": "Anonymous",
                    "created": inferred_created(preset_id)
                }
            elif isinstance(value, dict):
                # New format: full metadata
                entry = {
                    "id": preset_id,
                    "name": value.get("name", "Untitled"),
                    "author": value.get("author", "Anonymous"),
                    "created": value.get("created") or inferred_created(preset_id),
                    "plays": int(value.get("plays", 0) or 0),
                    "parent_id": value.get("parent_id"),
                }
            else:
                continue
            entry.update(preset_summary(preset_id))
            normalized.append(entry)
        by_id = {entry["id"]: entry for entry in normalized}
        remix_counts = {}
        for entry in normalized:
            parent_id = entry.get("parent_id")
            if parent_id:
                remix_counts[parent_id] = remix_counts.get(parent_id, 0) + 1
                parent = by_id.get(parent_id)
                entry["parent_name"] = parent.get("name") if parent else None
        for entry in normalized:
            entry["remix_count"] = remix_counts.get(entry["id"], 0)
        return JSONResponse({"ok": True, "presets": normalized})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/gallery/play")
async def record_gallery_play(request: Request):
    """Increment a shared preset's audition count in the gallery manifest."""
    body = await request.json()
    preset_id = str(body.get("id") or "").strip()
    if not re.match(r'^[a-zA-Z0-9_\-]{1,120}$', preset_id):
        return JSONResponse({"ok": False, "error": "Invalid id"}, status_code=400)
    if not GITHUB_TOKEN:
        return JSONResponse({"ok": False, "error": "Play persistence not configured"}, status_code=503)
    try:
        manifest = _fetch_shared_manifest()
        existing = manifest.get(preset_id)
        if existing is None:
            return JSONResponse({"ok": False, "error": "Preset not found"}, status_code=404)
        if isinstance(existing, str):
            entry = {"name": existing, "author": "Anonymous", "plays": 1}
        else:
            entry = dict(existing)
            entry["plays"] = int(entry.get("plays", 0) or 0) + 1
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: _update_shared_manifest({preset_id: entry}))
        return JSONResponse({"ok": True, "plays": entry["plays"]})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/save-preset")
async def save_preset_endpoint(request: Request):
    """Save current parameters back to the original preset file."""
    body = await request.json()
    params = body.get("params")
    path = body.get("path")
    create_new = body.get("create_new", False)
    if not params or not path:
        return JSONResponse({"ok": False, "error": "Missing params or path"}, status_code=400)
    try:
        import yaml as _yaml
        # Resolve path relative to project root
        project_root = Path(__file__).resolve().parent.parent
        preset_path = project_root / path
        if not preset_path.exists() and not create_new:
            return JSONResponse({"ok": False, "error": "Preset file not found"}, status_code=404)
        # Ensure parent directory exists for new files
        preset_path.parent.mkdir(parents=True, exist_ok=True)

        preset_data = _ui_params_to_preset(params)
        # Build a proper YAML structure with meta
        save_data = {
            "meta": {
                "name": params.get("name", "Untitled"),
                "slug": params.get("name", "untitled").lower().replace(" ", "_"),
                "category": "custom",
                "author": "Matteo Bassi",
                "engine_version": "MANTICE_V17",
            },
            "global": {
                "duration_seconds": preset_data.get("duration", 60),
                "sample_rate": 44100,
                "bit_depth": "16-bit",
            },
            "saturation": preset_data.get("saturation", 0.3),
            "reverb": preset_data.get("reverb", {}),
            "spatial": {
                "depth": preset_data.get("spatial_depth", 1.0),
                "wetness": preset_data.get("spatial_wet", 0.7),
                "swarm_density": 0.5,
            },
            "earth": preset_data.get("earth", {}),
            "air": preset_data.get("air", {}),
            "binaural": preset_data.get("binaural", {}),
            "layers": [],
        }

        # Rebuild layers in V2 YAML format
        for layer in preset_data.get("layers", []):
            l_out = {
                "name": layer.get("name", "Layer"),
                "muted": bool(layer.get("muted", False)),
                "type": layer.get("type", "fm"),
            }
            if layer.get("type") == "wavetable":
                l_out["wavetable_source"] = layer.get("wavetable_source", "")
                l_out["wavetable_frame_size"] = int(layer.get("wavetable_frame_size", 2048))
                l_out["wavetable_position"] = float(layer.get("wavetable_position", 0.0))
                l_out["wavetable_scan_start"] = float(layer.get("wavetable_scan_start", 0.0))
                l_out["wavetable_scan_end"] = float(layer.get("wavetable_scan_end", 1.0))
                l_out["wavetable_scan_rate"] = float(layer.get("wavetable_scan_rate", 0.01))
                l_out["wavetable_scan_mode"] = layer.get("wavetable_scan_mode", "pingpong")
                l_out["wavetable_detune_cents"] = float(layer.get("wavetable_detune_cents", 7.0))
                for metadata_key in ("wavetable_name", "wavetable_sha256", "wavetable_source_url", "wavetable_creator", "wavetable_license"):
                    if layer.get(metadata_key):
                        l_out[metadata_key] = layer[metadata_key]
                l_out["synthesis"] = {
                    "root": layer.get("root", 110),
                    "voices": layer.get("voices", 3),
                    "ratios": layer.get("ratios", [1.0]),
                }
            elif layer.get("type") == "granular":
                l_out["source"] = layer.get("source", "singing_bowl.ogg")
                l_out["grain_size"] = layer.get("grain_size", 80)
                l_out["density"] = layer.get("density", 15)
                l_out["pitch_spread"] = layer.get("pitch_spread", 0.3)
                l_out["position"] = layer.get("position", 0.5)
                l_out["scatter"] = layer.get("scatter", 0.5)
                l_out["envelope"] = layer.get("envelope", "hann")
            else:
                l_out["synthesis"] = {
                    "root": layer.get("root", 110),
                    "voices": layer.get("voices", 4),
                    "ratios": layer.get("ratios", [1.0]),
                }
                l_out["fm"] = {
                    "ratios": layer.get("fm_ratios", [1.0]),
                    "index": layer.get("fm_index", 0.1),
                }
                l_out["harmonics"] = layer.get("harmonics", 4)
                l_out["harmonic_decay"] = layer.get("harmonic_decay", 0.7)
                l_out["noise_amount"] = layer.get("noise_amount", 0.0)
                l_out["noise_color"] = layer.get("noise_color", "pink")
                l_out["spread"] = float(layer.get("spread", 1.0))
                l_out["blend"] = float(layer.get("blend", 1.0))
                l_out["flanger_wet"]      = float(layer.get("flanger_wet", 0.0))
                l_out["flanger_rate"]     = float(layer.get("flanger_rate", 0.25))
                l_out["flanger_depth"]    = float(layer.get("flanger_depth", 0.5))
                l_out["flanger_feedback"] = float(layer.get("flanger_feedback", 0.4))
                l_out["phaser_wet"]       = float(layer.get("phaser_wet", 0.0))
                l_out["phaser_rate"]      = float(layer.get("phaser_rate", 0.5))
                l_out["phaser_depth"]     = float(layer.get("phaser_depth", 0.7))
                l_out["phaser_center_hz"] = float(layer.get("phaser_center_hz", 800.0))
                l_out["phaser_feedback"]  = float(layer.get("phaser_feedback", 0.0))
                l_out["phaser_stages"]    = int(layer.get("phaser_stages", 4))
            l_out["dynamics"] = {
                "volume_db": layer.get("volume_db", 0.0),
                "amp_min": layer.get("amp_min", 0.001),
                "amp_max": layer.get("amp_max", 0.05),
                "drift": layer.get("drift", 0.01),
            }
            l_out["spatial_motion"] = {
                "quadrant": layer.get("quadrant", "center"),
                "speed": layer.get("speed", 0.01),
                "trajectory_x": layer.get("trajectory_x", "none"),
                "trajectory_y": layer.get("trajectory_y", "none"),
            }
            l_out["pan"] = float(layer.get("pan", 0.0))
            l_out["width"] = float(layer.get("width", 1.0))
            l_out["elevation"] = layer.get("elevation", 0.0)
            l_out["elevation_motion"] = layer.get("elevation_motion", "static")
            l_out["elevation_speed"] = layer.get("elevation_speed", 0.1)
            l_out["elevation_range"] = layer.get("elevation_range", 60.0)
            l_out["chorus_rate"] = layer.get("chorus_rate", 0.5)
            l_out["chorus_depth"] = layer.get("chorus_depth", 0.005)
            l_out["chorus_mix"] = layer.get("chorus_mix", 0.0)
            l_out["chorus_voices"] = layer.get("chorus_voices", 2)
            l_out["filter_type"] = layer.get("filter_type", "off")
            l_out["filter_cutoff"] = float(layer.get("filter_cutoff", 2000))
            l_out["filter_resonance"] = float(layer.get("filter_resonance", 1.0))
            l_out["filter_lfo_rate"] = float(layer.get("filter_lfo_rate", 0.1))
            l_out["filter_lfo_depth"] = float(layer.get("filter_lfo_depth", 0.0))
            l_out["filter_lfo_shape"] = layer.get("filter_lfo_shape", "sine")
            l_out["waveform"] = layer.get("waveform", "saw")
            l_out["detune_cents"] = float(layer.get("detune_cents", 8.0))
            l_out["sub_mix"] = float(layer.get("sub_mix", 0.3))
            save_data["layers"].append(l_out)

        # Try to preserve meta from original file
        try:
            with open(preset_path, "r", encoding="utf-8") as f:
                original = _yaml.safe_load(f)
            if original and "meta" in original:
                save_data["meta"] = original["meta"]
        except Exception:
            pass

        yaml_str = _yaml.dump(save_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        with open(preset_path, "w", encoding="utf-8") as f:
            f.write(yaml_str)

        return JSONResponse({"ok": True, "saved_to": path})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/delete-preset")
async def delete_preset_endpoint(request: Request):
    """Delete a preset file."""
    body = await request.json()
    path = body.get("path")
    if not path:
        return JSONResponse({"ok": False, "error": "Missing path"}, status_code=400)
    try:
        project_root = Path(__file__).resolve().parent.parent
        preset_path = project_root / path
        if not preset_path.exists():
            return JSONResponse({"ok": False, "error": "File not found"}, status_code=404)
        # Safety: only allow deleting .yaml files inside presets/
        if not str(preset_path.resolve()).startswith(str((project_root / "presets").resolve())):
            return JSONResponse({"ok": False, "error": "Cannot delete files outside presets/"}, status_code=403)
        preset_path.unlink()
        return JSONResponse({"ok": True, "deleted": path})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

_active_streams: dict[str, bool] = {}  # session_id -> running flag

# ── Segment player engines (MANT-16) ─────────────────────────────────────────
_segment_engines: dict[str, "StreamingDroneEngine"] = {}  # token → engine
_SEGMENT_ENGINE_MAX = 20  # max concurrent mobile sessions


@app.post("/api/preview-segment")
async def preview_segment(request: Request):
    """Render a compressed audio segment for mobile buffered playback (MANT-16).

    Body: { params, seed, segment_s?, token? }
    Omit ``token`` on the first call; subsequent calls with the same token
    continue rendering from where the engine left off (seamless gapless playback).
    Returns OGG audio bytes; the session token is in the X-Segment-Token header.
    """
    body = await request.json()
    params = body.get("params")
    if not params:
        return JSONResponse({"ok": False, "error": "No params"}, status_code=400)

    seed       = int(body.get("seed", 42))
    segment_s  = float(body.get("segment_s", 25.0))
    segment_s  = max(5.0, min(60.0, segment_s))
    token      = body.get("token") or ""
    reset      = bool(body.get("reset", False))

    try:
        preset = _ui_params_to_preset(params)
        # Create new engine or reuse existing session
        if not token or reset or token not in _segment_engines:
            token = uuid.uuid4().hex[:16]
            engine = StreamingDroneEngine(preset, seed=seed, render_mode=True)
            # Evict oldest entry when over the limit (simple LRU approximation)
            if len(_segment_engines) >= _SEGMENT_ENGINE_MAX:
                oldest = next(iter(_segment_engines))
                del _segment_engines[oldest]
            _segment_engines[token] = engine
        else:
            engine = _segment_engines[token]
        sr = engine.SR
        total_samples = int(segment_s * sr)
        chunk_size    = 2048

        def _render():
            remaining = total_samples
            chunks    = []
            while remaining > 0:
                n = min(chunk_size, remaining)
                chunks.append(engine.next_chunk(n))
                remaining -= n
            raw = np.concatenate(chunks, axis=0)
            return np.clip(raw, -1.0, 1.0).astype(np.float32)

        loop  = asyncio.get_event_loop()
        audio = await loop.run_in_executor(None, _render)

        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="OGG", subtype="VORBIS")
        buf.seek(0)
        audio_bytes = buf.read()

        return Response(
            content=audio_bytes,
            media_type="audio/ogg",
            headers={
                "X-Segment-Token":             token,
                "Content-Length":              str(len(audio_bytes)),
                "Access-Control-Expose-Headers": "X-Segment-Token",
            },
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.delete("/api/preview-segment/{token}")
async def delete_segment_engine(token: str):
    """Release the segment engine for a session (called by client on stop)."""
    _segment_engines.pop(token, None)
    return JSONResponse({"ok": True})


# ── Preset Journey (render multi-preset sequence with crossfades) ─────────────

@app.post("/api/render-journey")
async def render_journey_endpoint(request: Request):
    """Render a preset journey and return as a downloadable audio file.

    Body: {
        steps: [{ preset_path, hold_s, morph_s }, ...],
        loop: "none" | "loop" | "pingpong",
        format: "mp3" | "wav" | "ogg" | "flac",
        seed: int,
        preview: bool   -- if true, limit to first 60s and return OGG
    }
    """
    body = await request.json()
    steps   = body.get("steps", [])
    loop    = body.get("loop", "none")
    fmt     = body.get("format", "mp3")
    seed    = int(body.get("seed", 42))
    preview = bool(body.get("preview", False))

    if not steps:
        return JSONResponse({"ok": False, "error": "No steps provided"}, status_code=400)
    if not all(s.get("preset_path") for s in steps):
        return JSONResponse({"ok": False, "error": "All steps must have a preset_path"}, status_code=400)

    try:
        from .journey import render_journey, journey_total_seconds

        # Pre-resolve presets: use full params if provided, else load from file
        resolved_steps = []
        for step in steps:
            s = dict(step)
            if s.get("params"):
                s["preset"] = _ui_params_to_preset(s["params"])
            elif s.get("preset_path"):
                s["preset"] = load_preset(s["preset_path"])
            else:
                return JSONResponse({"ok": False, "error": "Step missing preset_path or params"}, status_code=400)
            resolved_steps.append(s)

        total_s = journey_total_seconds(resolved_steps, loop)
        max_samples = int(60 * config.STREAM_SAMPLE_RATE) if preview else None
        fmt_out = "ogg" if preview else fmt

        # Memory limit check (same as regular render endpoint)
        # Journeys always use hi-res (48kHz), so use that for estimation
        out_sr = 48_000  # Journeys always render at 48kHz
        estimated_audio_mb = (total_s * out_sr * 2 * 4) / (1024 * 1024)
        estimated_total_mb = estimated_audio_mb * 4  # Conservative: 4× for reverb + oversampling
        
        MAX_MEMORY_MB = 200
        
        if not preview and estimated_total_mb > MAX_MEMORY_MB:
            max_duration = int((MAX_MEMORY_MB / estimated_total_mb) * total_s)
            error_msg = (
                f"Journey too long: {int(total_s)}s would use ~{estimated_total_mb:.0f}MB (limit: {MAX_MEMORY_MB}MB). "
                f"Maximum duration: {max_duration}s (hi-res). "
                f"For longer journeys, use the Python CLI: python main.py --journey your_journey.yaml"
            )
            print(f"  [journey] MEMORY ERROR: {error_msg}")
            return JSONResponse({
                "ok": False, 
                "error": error_msg,
                "max_duration": max_duration,
                "estimated_memory_mb": int(estimated_total_mb)
            }, status_code=413)  # 413 Payload Too Large

        print(f"  [journey] {len(steps)} steps, loop={loop}, "
              f"total={total_s:.0f}s, preview={preview}, fmt={fmt_out}, ~{estimated_total_mb:.0f}MB")

        ev = asyncio.get_event_loop()

        def _render():
            return render_journey(resolved_steps, loop=loop, seed=seed, max_samples=max_samples)

        audio = await ev.run_in_executor(None, _render)
        
        # Generate random journey name from preset word lists
        import random
        word_a = random.choice(_NAME_PARTS_A)
        word_b = random.choice(_NAME_PARTS_B)
        journey_name = f"{word_a} {word_b}"

        # Use engine SR instead of module constant (48k for journeys due to render_mode=True)
        sr = 48_000  # Journeys always use render_mode=True, so always 48kHz
        import soundfile as sf

        # Create temp file path
        exports_dir = _ROOT / "exports"
        exports_dir.mkdir(exist_ok=True)
        filename = f"MANTICE Journey {journey_name} (preview).ogg" if preview else f"MANTICE Journey {journey_name}.{fmt_out}"
        export_path = exports_dir / filename

        def _encode_journey_to_file(audio_arr, path, fmt):
            """Encode journey audio directly to disk file. Returns media_type."""
            if fmt == "mp3":
                try:
                    import lameenc
                    pcm = (np.clip(audio_arr, -1.0, 1.0) * 32767).astype(np.int16)
                    enc = lameenc.Encoder()
                    enc.set_bit_rate(192)
                    enc.set_in_sample_rate(sr)
                    enc.set_channels(2)
                    enc.set_quality(2)
                    data = bytes(enc.encode(pcm.tobytes())) + bytes(enc.flush())
                    with open(str(path), "wb") as f:
                        f.write(data)
                    return "audio/mpeg"
                except ImportError:
                    # Fallback to OGG if lameenc unavailable
                    sf.write(str(path), audio_arr, sr, format="OGG", subtype="VORBIS")
                    return "audio/ogg"
            elif fmt == "flac":
                sf.write(str(path), audio_arr, sr, format="FLAC")
                return "audio/flac"
            elif fmt == "wav":
                sf.write(str(path), audio_arr, sr, format="WAV", subtype="PCM_16")
                return "audio/wav"
            else:  # ogg (default for preview)
                sf.write(str(path), audio_arr, sr, format="OGG", subtype="VORBIS")
                return "audio/ogg"

        media_type = await ev.run_in_executor(None, _encode_journey_to_file, audio, export_path, fmt_out)
        
        file_size_kb = export_path.stat().st_size // 1024
        print(f"  [journey] Saved: {export_path} ({file_size_kb} KB)")

        # Stream from disk instead of loading into memory
        from urllib.parse import quote
        
        return FileResponse(
            path=str(export_path),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}',
                "X-Journey-Duration": str(round(total_s, 1)),
                "X-Export-Path": str(export_path),
            },
        )
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"  [journey] ERROR: {error_detail}")
        return JSONResponse({"ok": False, "error": str(e), "traceback": error_detail}, status_code=500)


@app.websocket("/ws/preview")
async def ws_preview(websocket: WebSocket):
    """
    Stream audio chunks in real-time via WebSocket.

    Client sends JSON: {"action": "start", "params": {...}} to begin
    Client sends JSON: {"action": "stop"} to stop
    Server sends binary PCM16 frames (interleaved stereo, 48kHz)
    """
    await websocket.accept()
    stream_id = id(websocket)
    _active_streams[stream_id] = False
    engine = None

    try:
        while True:
            # Wait for commands from client
            msg = await websocket.receive_text()
            data = json.loads(msg)
            action = data.get("action")

            if action == "start":
                # Stop any existing stream
                _active_streams[stream_id] = False
                await asyncio.sleep(0.05)

                params = data.get("params")
                if not params:
                    await websocket.send_text(json.dumps({"error": "No params"}))
                    continue

                preset = _ui_params_to_preset(params)
                seed = int(data.get("seed", 42))
                engine = StreamingDroneEngine(preset, seed=seed)
                _active_streams[stream_id] = True

                # Send start confirmation with audio format info
                await websocket.send_text(json.dumps({
                    "status": "streaming",
                    "sample_rate": config.STREAM_SAMPLE_RATE,
                    "channels": 2,
                    "format": "pcm16"
                }))

                # Stream chunks in background
                asyncio.create_task(_stream_audio(websocket, engine, stream_id))

            elif action == "stop":
                _active_streams[stream_id] = False
                engine = None
                await websocket.send_text(json.dumps({"status": "stopped"}))

            elif action == "reload":
                # Hot-reload with new params (crossfade) — no interruption to streaming
                params = data.get("params")
                if params and engine:
                    new_preset = _ui_params_to_preset(params)
                    crossfade_secs = float(data.get("crossfade_secs", 1.0))
                    engine.reload(new_preset, crossfade_secs=crossfade_secs)
                    await websocket.send_text(json.dumps({
                        "status": "reloaded",
                        "crossfade_secs": crossfade_secs
                    }))
                elif not engine:
                    await websocket.send_text(json.dumps({
                        "error": "No active stream to reload"
                    }))

    except WebSocketDisconnect:
        _active_streams[stream_id] = False
    except Exception as e:
        logger.error(f"WebSocket error in stream {stream_id}: {e}")
        _active_streams[stream_id] = False
        try:
            await websocket.send_text(json.dumps({"error": str(e)}))
        except:
            pass


async def _stream_audio(websocket: WebSocket, engine: StreamingDroneEngine, stream_id: str):
    """Background task that generates and sends audio chunks."""
    chunk_size = 2048  # ~93ms at 22050Hz — small chunks for low-latency reload
    loop = asyncio.get_event_loop()
    sample_rate = config.STREAM_SAMPLE_RATE
    chunk_duration = chunk_size / sample_rate  # real-time duration of one chunk
    start_time = asyncio.get_event_loop().time()
    chunks_sent = 0
    # Allow buffering a few chunks ahead (pre-buffer), then pace to real-time
    max_ahead = 4  # chunks allowed ahead of real-time

    try:
        while _active_streams.get(stream_id, False):
            # Generate chunk in thread (avoid blocking event loop)
            chunk = await loop.run_in_executor(None, engine.next_chunk, chunk_size)

            # Convert float64 stereo to int16 PCM bytes
            pcm16 = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)
            await websocket.send_bytes(pcm16.tobytes())
            chunks_sent += 1

            # Pace: don't get too far ahead of real-time playback
            elapsed = asyncio.get_event_loop().time() - start_time
            audio_time = chunks_sent * chunk_duration
            ahead = audio_time - elapsed
            if ahead > max_ahead * chunk_duration:
                await asyncio.sleep(chunk_duration * 0.8)
            else:
                await asyncio.sleep(0.001)
    except Exception:
        pass  # Connection closed or stream stopped


@app.websocket("/ws/journey")
async def ws_journey(websocket: WebSocket):
    """
    Stream a Preset Journey in real-time via WebSocket.

    Client sends JSON: {"action": "start", "steps": [...], "loop": "none", "seed": 42}
    Server sends binary PCM16 frames (interleaved stereo) + text status messages.
    Client sends JSON: {"action": "stop"} to stop.
    """
    await websocket.accept()
    stream_id = id(websocket)
    _active_streams[stream_id] = False
    task = None

    try:
        while True:
            msg = await websocket.receive_text()
            data = json.loads(msg)
            action = data.get("action")

            if action == "start":
                _active_streams[stream_id] = False
                if task:
                    task.cancel()
                    await asyncio.sleep(0.05)

                steps = data.get("steps", [])
                loop  = data.get("loop", "none")
                seed  = int(data.get("seed", 42))

                if not steps:
                    await websocket.send_text(json.dumps({"error": "No steps"}))
                    continue

                # Pre-resolve presets: use full params if provided, else load from file
                resolved = []
                for step in steps:
                    s = dict(step)
                    if s.get("params"):
                        s["preset"] = _ui_params_to_preset(s["params"])
                    elif s.get("preset_path"):
                        s["preset"] = load_preset(s["preset_path"])
                    resolved.append(s)

                await websocket.send_text(json.dumps({
                    "status": "streaming",
                    "sample_rate": config.STREAM_SAMPLE_RATE,
                    "channels": 2,
                    "format": "pcm16",
                }))
                _active_streams[stream_id] = True
                task = asyncio.create_task(
                    _stream_journey_audio(websocket, resolved, loop, seed, stream_id)
                )

            elif action == "stop":
                _active_streams[stream_id] = False
                if task:
                    task.cancel()
                    task = None
                await websocket.send_text(json.dumps({"status": "stopped"}))

    except WebSocketDisconnect:
        _active_streams[stream_id] = False
        if task:
            task.cancel()
    except Exception:
        _active_streams[stream_id] = False
    finally:
        _active_streams.pop(stream_id, None)


async def _stream_journey_audio(websocket: WebSocket, steps: list, loop: str,
                                 seed: int, stream_id: str):
    """Background task: renders and streams journey steps as PCM16 chunks."""
    from .journey import _expand_steps, _resolve_steps

    SR    = config.STREAM_SAMPLE_RATE
    CHUNK = 2048
    ev    = asyncio.get_event_loop()

    try:
        expanded = _expand_steps(steps, loop)
        resolved = _resolve_steps(expanded)
        n        = len(resolved)

        prev_engine_b = None  # engine carried over from previous morph window

        for i, (step, preset) in enumerate(resolved):
            if not _active_streams.get(stream_id):
                break

            hold_s  = float(step.get("hold_s", 0.0))
            morph_s = float(step.get("morph_s", 0.0))
            is_last = (i == n - 1)

            # Notify client which step is now playing
            await websocket.send_text(json.dumps({"step_index": i}))

            # Reuse engine_b from previous morph (continuous audio), or start fresh
            if prev_engine_b is not None:
                engine_a      = prev_engine_b
                prev_engine_b = None
            else:
                engine_a = StreamingDroneEngine(
                    dict(preset) | {"duration": max(hold_s, 1.0)},
                    seed=seed,
                )

            # ── Hold window ──────────────────────────────────────────────────
            hold_samples = int(hold_s * SR)
            sent = 0
            while sent < hold_samples and _active_streams.get(stream_id):
                k     = min(CHUNK, hold_samples - sent)
                chunk = await ev.run_in_executor(None, engine_a.next_chunk, k)
                pcm16 = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)
                await websocket.send_bytes(pcm16.tobytes())
                sent += k

            # ── Morph window (crossfade to next preset) ──────────────────────
            if morph_s > 0.0 and not is_last and _active_streams.get(stream_id):
                _, next_preset    = resolved[i + 1]
                next_hold_s       = float(resolved[i + 1][0].get("hold_s", 60.0))
                engine_b = StreamingDroneEngine(
                    dict(next_preset) | {"duration": max(morph_s + next_hold_s, 1.0)},
                    seed=seed,
                )

                morph_samples = int(morph_s * SR)
                sent_m        = 0
                while sent_m < morph_samples and _active_streams.get(stream_id):
                    k   = min(CHUNK, morph_samples - sent_m)
                    t0  = sent_m / morph_samples
                    t1  = (sent_m + k) / morph_samples

                    def _blend(ea=engine_a, eb=engine_b, k=k, t0=t0, t1=t1):
                        ca   = ea.next_chunk(k)
                        cb   = eb.next_chunk(k)
                        t    = np.linspace(t0, t1, k, endpoint=False, dtype=np.float32)
                        fade = (t * t * (3.0 - 2.0 * t))[:, np.newaxis]
                        return np.clip(ca * (1.0 - fade) + cb * fade, -1.0, 1.0)

                    blended = await ev.run_in_executor(None, _blend)
                    pcm16   = (blended * 32767).astype(np.int16)
                    await websocket.send_bytes(pcm16.tobytes())
                    sent_m += k

                prev_engine_b = engine_b  # hand off for next hold window

        if _active_streams.get(stream_id):
            await websocket.send_text(json.dumps({"status": "done"}))

    except asyncio.CancelledError:
        pass
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_text(json.dumps({"error": str(e)}))
        except Exception:
            pass


# ── Server launcher ───────────────────────────────────────────────────────────

def launch_gui(host: str = "127.0.0.1", port: int = 8432, open_browser: bool = True):
    """Start the web server and optionally open the browser."""
    import signal
    import sys
    import webbrowser

    url = f"http://{host}:{port}"
    print(f"\n  MANTICE Web UI starting at {url}")
    print(f"  Press Ctrl+C or close this terminal to stop.\n")

    if open_browser:
        def _open():
            import time
            time.sleep(1.0)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    # Force clean exit on Ctrl+C (uvicorn on Windows ignores SIGINT sometimes)
    def _force_exit(sig, frame):
        print("\n  Shutting down...")
        import os
        os._exit(0)

    signal.signal(signal.SIGINT, _force_exit)
    try:
        signal.signal(signal.SIGBREAK, _force_exit)  # Windows Ctrl+Break
    except (AttributeError, OSError):
        pass  # Not available on all platforms

    # Use uvicorn with a server instance so we can potentially shut it down
    uvi_cfg = uvicorn.Config(
        app, host=host, port=port, log_level="warning",
        timeout_keep_alive=300,  # allow long-running renders
    )
    server = uvicorn.Server(uvi_cfg)
    server.run()
