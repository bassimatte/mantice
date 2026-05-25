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

import asyncio
import json
import io
import os
import re
import base64
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
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, Response
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
from .generator import generate_preset, mutate_preset, save_generated_preset

# ── Helpers ───────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent
_PRESETS_DIR = _ROOT / "presets"
_EXPORTS_DIR = _ROOT / "exports"
_SHARED_DIR = _ROOT / "shared"
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_SAMPLES_DIR = _ROOT / "samples"
_FS_CACHE_DIR = _SAMPLES_DIR / "freesound_cache"
_PITCH_CACHE_FILE = _SAMPLES_DIR / "pitch_cache.json"

# In-memory pitch cache; populated at startup and on-demand
_pitch_cache: dict = {}


def _load_pitch_cache():
    """Load cached sample pitches from disk and share with granular_layer module."""
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
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/shared"
        gh_req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "Mantice/1.0", "Accept": "application/vnd.github.v3+json"}
        )
        if GITHUB_TOKEN:
            gh_req.add_header("Authorization", f"token {GITHUB_TOKEN}")
        with urllib.request.urlopen(gh_req, timeout=6) as resp:
            files = json.loads(resp.read().decode())
        for f in files:
            if not isinstance(f, dict):
                continue
            fname = f.get("name", "")
            if not fname.endswith(".yaml") or fname in (".gitkeep.yaml", ".gitkeep"):
                continue
            stem = fname[:-5]
            m = re.search(r'_(\d{8}_[a-f0-9]+)$', stem)
            short_id = m.group(1)[-6:] if m else None
            base_name = re.sub(r'_\d{8}_[a-f0-9]+$', '', stem).replace('_', ' ').strip()
            display_name = f"{base_name} #{short_id}" if short_id else base_name
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
            for yaml_file in sorted(_SHARED_DIR.glob("*.yaml")):
                stem = yaml_file.stem
                name, tags = _parse(yaml_file)
                m = re.search(r'_(\d{8}_[a-f0-9]+)$', stem)
                short_id = m.group(1)[-6:] if m else None
                base_name = re.sub(r'_\d{8}_[a-f0-9]+$', '', stem).replace('_', ' ').strip()
                display_name = f"{base_name} #{short_id}" if short_id else base_name
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
                "root": layer.get("root", 100),
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
            "root": float(l.get("root", 100)),
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
        print(f"  [render] Starting {duration}s render ({fmt})…")

        # Check hires flag from request
        hires = body.get("hires", False)
        if hires:
            config.set_hires()

        # Run CPU-heavy render in thread
        loop = asyncio.get_event_loop()
        seed = int(body.get("seed", 42))

        def _render():
            engine = StreamingDroneEngine(preset, seed=seed)
            sr = config.STREAM_SAMPLE_RATE
            total_samples = int(preset["duration"] * sr)
            chunk_size = 2048  # must match engine's FDN reverb buffer size
            chunks = []
            remaining = total_samples
            while remaining > 0:
                n = min(chunk_size, remaining)
                chunks.append(engine.next_chunk(n))
                remaining -= n
            return np.concatenate(chunks, axis=0)

        audio = await loop.run_in_executor(None, _render)

        print(f"  [render] Done. Encoding {fmt}…")
        import soundfile as sf

        # Save to exports/ folder
        exports_dir = _ROOT / "exports"
        exports_dir.mkdir(exist_ok=True)
        # Use preset name for filename (sanitize for filesystem)
        import re
        preset_name = params.get("name", "MANTICE") or "MANTICE"
        safe_name = re.sub(r'[^\w\s\-]', '', preset_name).strip()
        if not safe_name:
            safe_name = "MANTICE"
        filename = f"{safe_name}.{fmt}"
        export_path = exports_dir / filename

        sr = config.STREAM_SAMPLE_RATE
        bd = config.BIT_DEPTH

        def _encode_audio(audio_arr, fmt, sr, bd):
            """Encode audio array to bytes in the requested format. Returns (bytes, media_type)."""
            if fmt == "mp3":
                import lameenc
                pcm = (audio_arr * 32767).clip(-32768, 32767).astype(np.int16)
                encoder = lameenc.Encoder()
                encoder.set_bit_rate(192)
                encoder.set_in_sample_rate(sr)
                encoder.set_channels(2)
                encoder.set_quality(2)
                data = encoder.encode(pcm.tobytes()) + encoder.flush()
                return data, "audio/mpeg"
            else:
                subtypes = {"wav": bd, "flac": bd, "ogg": "VORBIS"}
                buf = io.BytesIO()
                sf.write(buf, audio_arr, sr, format=fmt.upper(), subtype=subtypes.get(fmt))
                buf.seek(0)
                media = {"wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg"}
                return buf.read(), media.get(fmt, "application/octet-stream")

        # Save to disk
        audio_bytes, media_type = _encode_audio(audio, fmt, sr, bd)
        with open(str(export_path), "wb") as _f:
            _f.write(audio_bytes)
        print(f"  [render] Saved: {export_path}")

        file_size = len(audio_bytes)
        buf = io.BytesIO(audio_bytes)
        print(f"  [render] Sending file ({file_size // 1024} KB)")

        return StreamingResponse(
            buf,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(file_size),
                "X-Export-Path": str(export_path),
            }
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


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
        sf.write(buf, audio, config.SAMPLE_RATE, format="WAV", subtype="PCM_16")
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
    allowed_types = body.get("allowed_types") or ["fm", "subtractive"]
    harmonic_mode = bool(body.get("harmonic_mode", False))
    harmonic_key = str(body.get("harmonic_key", "C"))
    harmonic_scale = str(body.get("harmonic_scale", "major"))
    try:
        import yaml as _yaml, tempfile
        preset_data = generate_preset(mood=mood, seed=seed, allowed_types=allowed_types,
                                      harmonic_mode=harmonic_mode,
                                      harmonic_key=harmonic_key,
                                      harmonic_scale=harmonic_scale)
        with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False, mode='w', encoding='utf-8') as f:
            _yaml.dump(preset_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            tmp_path = Path(f.name)
        try:
            preset = load_preset(tmp_path)
            params = _preset_to_ui_params(preset)
        finally:
            tmp_path.unlink(missing_ok=True)
        return JSONResponse({"ok": True, "params": params})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/mutate")
async def mutate_endpoint(request: Request):
    """Mutate a preset and return the mutated parameters.
    Accepts either {path, amount} or {params, amount}."""
    body = await request.json()
    path = body.get("path")
    ui_params = body.get("params")
    amount = float(body.get("amount", 0.3))
    if not path and not ui_params:
        return JSONResponse({"ok": False, "error": "No preset path or params"}, status_code=400)
    try:
        import yaml as _yaml, tempfile
        if path:
            # Load raw YAML (mutate_preset expects the raw v2 dict, not the normalised one)
            with open(path, encoding="utf-8") as f:
                raw_preset = _yaml.safe_load(f)
        else:
            # Build a v2-structured raw preset from current UI params
            flat = _ui_params_to_preset(ui_params)
            raw_layers = []
            for l in flat.get("layers", []):
                raw_layers.append({
                    "name": l.get("name", "Layer"),
                    "muted": bool(l.get("muted", False)),
                    "type": l.get("type", "fm"),
                    "source": l.get("source", "singing_bowl.ogg"),
                    "grain_size": l.get("grain_size", 80),
                    "density": l.get("density", 15),
                    "pitch_spread": l.get("pitch_spread", 0.3),
                    "position": l.get("position", 0.5),
                    "scatter": l.get("scatter", 0.5),
                    "envelope": l.get("envelope", "hann"),
                    "synthesis": {
                        "root": l.get("root", 220),
                        "voices": l.get("voices", 4),
                        "ratios": l.get("ratios", [1.0]),
                    },
                    "fm": {
                        "ratios": l.get("fm_ratios", [1.0]),
                        "index": l.get("fm_index", 0.5),
                    },
                    "dynamics": {
                        "volume_db": l.get("volume_db", 0.0),
                        "amp_min": l.get("amp_min", 0.005),
                        "amp_max": l.get("amp_max", 0.04),
                        "drift": l.get("drift", 0.002),
                    },
                    "spatial_motion": {
                        "quadrant": l.get("quadrant", "center"),
                        "speed": l.get("speed", 0.005),
                        "trajectory_x": l.get("trajectory_x", "drift"),
                        "trajectory_y": l.get("trajectory_y", "none"),
                    },
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
                    "harmonics": l.get("harmonics", 4),
                    "harmonic_decay": l.get("harmonic_decay", 0.7),
                    "noise_amount": l.get("noise_amount", 0.0),
                    "noise_color": l.get("noise_color", "pink"),
                    "elevation": l.get("elevation", 0.0),
                    "elevation_motion": l.get("elevation_motion", "static"),
                    "elevation_speed": l.get("elevation_speed", 0.1),
                    "elevation_range": l.get("elevation_range", 60.0),
                    "chorus_mix": l.get("chorus_mix", 0.0),
                    "chorus_rate": l.get("chorus_rate", 0.5),
                    "chorus_depth": l.get("chorus_depth", 0.005),
                    "chorus_voices": l.get("chorus_voices", 2),
                    "filter_type": l.get("filter_type", "off"),
                    "filter_cutoff": float(l.get("filter_cutoff", 2000)),
                    "filter_resonance": float(l.get("filter_resonance", 1.0)),
                    "filter_lfo_rate": float(l.get("filter_lfo_rate", 0.1)),
                    "filter_lfo_depth": float(l.get("filter_lfo_depth", 0.0)),
                    "filter_lfo_shape": l.get("filter_lfo_shape", "sine"),
                    "waveform": l.get("waveform", "saw"),
                    "detune_cents": float(l.get("detune_cents", 8.0)),
                    "sub_mix": float(l.get("sub_mix", 0.3)),
                })
            m = flat.get("master", {})
            raw_preset = {
                "meta": flat.get("meta", {}),
                "global": {"duration_seconds": int(flat.get("duration", 60))},
                "spatial": {"depth": flat.get("spatial_depth", 1.0), "wetness": flat.get("spatial_wet", 0.7)},
                "saturation": flat.get("saturation", 0.3),
                "master": m,
                "reverb": flat.get("reverb"),
                "binaural": flat.get("binaural"),
                "earth": flat.get("earth"),
                "air": flat.get("air"),
                "layers": raw_layers,
            }
        mutated_data = mutate_preset(raw_preset, amount=amount)
        with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False, mode='w', encoding='utf-8') as f:
            _yaml.dump(mutated_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            tmp_path = Path(f.name)
        try:
            preset = load_preset(tmp_path)
            params = _preset_to_ui_params(preset)
        finally:
            tmp_path.unlink(missing_ok=True)
        return JSONResponse({"ok": True, "params": params})
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
    if not params:
        return JSONResponse({"ok": False, "error": "No params"}, status_code=400)
    try:
        import yaml as _yaml
        preset_data = _ui_params_to_preset(params)
        from .generator import _random_name
        # Fetch existing names from GitHub to avoid duplicates (best-effort)
        existing_names: set = set()
        try:
            list_req = urllib.request.Request(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/shared",
                headers={"User-Agent": "Mantice/1.0", "Accept": "application/vnd.github.v3+json",
                         "Authorization": f"token {GITHUB_TOKEN}"}
            )
            with urllib.request.urlopen(list_req, timeout=6) as resp:
                for f in json.loads(resp.read().decode()):
                    stem = f.get("name", "")[:-5]  # strip .yaml
                    base = re.sub(r'_\d{8}_[a-f0-9]+$', '', stem).replace('_', ' ').strip()
                    if base:
                        existing_names.add(base.lower())
        except Exception:
            pass  # if we can't check, proceed anyway
        # Pick a name not already in use (up to 20 attempts)
        for _ in range(20):
            preset_name = _random_name()
            if preset_name.lower() not in existing_names:
                break
        preset_data["meta"]["name"] = preset_name
        safe_name = "".join(c for c in preset_name if c.isalnum() or c in " -_").strip().replace(" ", "_")
        short_id = uuid.uuid4().hex[:6]
        date_str = datetime.utcnow().strftime("%Y%m%d")
        file_id = f"{safe_name}_{date_str}_{short_id}"
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
        loop = asyncio.get_event_loop()
        def do_gh_put():
            with urllib.request.urlopen(req) as resp:
                return resp.status
        status = await loop.run_in_executor(None, do_gh_put)
        if status not in (200, 201):
            return JSONResponse({"ok": False, "error": f"GitHub API returned {status}"}, status_code=500)
        # Also upload JSON params — enables backend-free loading on GitHub Pages
        params["name"] = preset_name
        json_b64 = base64.b64encode(json.dumps(params).encode("utf-8")).decode("ascii")
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
        return JSONResponse({"ok": True, "id": file_id})
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
        params = _preset_to_ui_params(preset_data)
        return JSONResponse({"ok": True, "params": params})
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return JSONResponse({"ok": False, "error": "Shared preset not found"}, status_code=404)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
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
            if layer.get("type") == "granular":
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

    except WebSocketDisconnect:
        _active_streams[stream_id] = False
    except Exception:
        _active_streams[stream_id] = False


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


# ── Server launcher ───────────────────────────────────────────────────────────

def launch_gui(host: str = "127.0.0.1", port: int = 8432, open_browser: bool = True):
    """Start the web server and optionally open the browser."""
    import signal
    import sys
    import webbrowser

    url = f"http://{host}:{port}"
    print(f"\n  🔊 MANTICE Web UI starting at {url}")
    print(f"  Press Ctrl+C or close this terminal to stop.\n")

    if open_browser:
        def _open():
            import time
            time.sleep(1.0)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    # Force clean exit on Ctrl+C (uvicorn on Windows ignores SIGINT sometimes)
    def _force_exit(sig, frame):
        print("\n  Shutting down…")
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
