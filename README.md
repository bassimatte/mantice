# MANTICE — The Breath Behind the Drone

A procedural sacred/ambient drone audio generator with FM synthesis, granular clouds,
spatial panning, binaural beats, FDN reverb, and a real-time Web UI.

**Created by Matteo Bassi** — [freesound.org/people/bassimat](https://freesound.org/people/bassimat/)

> *"Mantice"* — Italian for the bellows of an organ: the invisible breath engine
> that gives life to the pipes. The soul behind the sound.

---

## 🎧 Try it Online

**[▶ Launch Mantice](https://bassimatte.github.io/mantice/)** — runs in your browser, no install needed.

---

## 💻 Run Locally

```bash
git clone https://github.com/bassimatte/mantice.git
cd mantice
pip install -r requirements.txt
python main.py --gui
```

Opens `http://127.0.0.1:8432` — a full browser-based interface.

### Terminal-only mode (no browser)

```bash
python main.py --preset "presets/essentials/Warm Pad.yaml" --duration 120
```

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────┐
│  GitHub Pages (docs/index.html)                         │
│  Static frontend — no server needed                     │
└──────────────────────┬──────────────────────────────────┘
                       │ WebSocket + REST API
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Render.com (Python backend)                            │
│  FastAPI + NumPy/SciPy synthesis engine                 │
│  Streams PCM audio chunks to browser                    │
└─────────────────────────────────────────────────────────┘
```

**Local mode:** Both frontend and backend run on your machine (`python main.py --gui`).

---

## 🎛 Features

- **FM Synthesis** — up to 12 detuned voices per layer with configurable harmonics
- **Subtractive Synthesis** — dual detuned oscillators (saw/square/triangle) + sub-oscillator, Reese bass style
- **Per-Layer Filter & LFO** — biquad LP/HP/BP filter with LFO modulation (sine/triangle/square)
- **Granular Clouds** — sample-based grain synthesis with CC0 sound sources
- **Spatial Motion** — per-layer panning trajectories (orbit, drift, bounce) with elevation
- **Binaural Beats** — theta/delta/alpha entrainment with configurable depth
- **FDN Reverb** — 8-tap feedback delay network (or custom impulse responses)
- **Chorus** — multi-voice modulation for width and shimmer
- **Master EQ & Compressor** — 4-band EQ + feedforward compressor on master bus
- **44 Presets** — across 6 categories (essentials, cinematic, experimental, sacred, subharmonic, reese)
- **Real-time Web UI** — stream, tweak, save, and export from your browser; layer sub-tabs (Synth/Filter/Space/FX)
- **Generator** — mood-biased random preset generator with FM/Subtractive type selection
- **Preset Save/Load** — create, modify, and share YAML preset files

---

## 📦 Deployment

### GitHub Pages (frontend)
1. Push to GitHub
2. Settings → Pages → Source: `/docs` folder
3. Your UI is live at `https://bassimatte.github.io/mantice/`

### Render (backend)
1. Connect your GitHub repo on [render.com](https://render.com)
2. It auto-detects the `Dockerfile`
3. Backend runs at `https://mantice.onrender.com`
4. Update `docs/index.html` → `MANTICE_API_BASE` with your actual Render URL

---

## All Settings Reference

### Global Settings

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Duration | `global.duration_seconds` | 1–3600 s | 60 | Total audio length |
| Sample Rate | `global.sample_rate` | 44100/48000 | 44100 | Audio sample rate |
| Bit Depth | `global.bit_depth` | 16-bit/24-bit | 16-bit | Output resolution |
| Seed | `seed` | any integer | random | Reproducible output |
| Saturation (Warmth) | `saturation` | 0.0–1.0 | 0.3 | Master soft saturation / tape warmth (normalized tanh waveshaping) |

### Layer Settings (per layer)

#### Synthesis

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Root Frequency | `synthesis.root` | 20–8000 Hz | 110 | Fundamental frequency |
| Voices | `synthesis.voices` | 1–20 | 8 | Number of oscillator voices (detuned copies) |
| Ratios | `synthesis.ratios` | list of floats | [1.0] | Frequency multipliers relative to root |

#### FM Synthesis

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| FM Ratios | `fm.ratios` | list of floats | [1.0] | Modulator frequency ratios |
| FM Index | `fm.index` | 0.0–5.0 | 0.1 | Modulation depth (higher = more harmonics) |

#### Subtractive Synthesis

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Waveform | `waveform` | saw / square / triangle | saw | Oscillator waveform shape |
| Detune | `detune_cents` | 0–50 cents | 8.0 | Spread between detuned oscillator pairs |
| Sub Mix | `sub_mix` | 0.0–1.0 | 0.3 | Level of the sub-oscillator (one octave below) |

Set `type: subtractive` at layer level to use this engine instead of FM.

#### Per-Layer Filter & LFO

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Filter Type | `filter_type` | off / lp / hp / bp | off | Biquad filter type |
| Cutoff | `filter_cutoff` | 20–20000 Hz | 2000 | Filter cutoff frequency |
| Resonance | `filter_resonance` | 0.1–10 | 1.0 | Q factor / resonance peak |
| LFO Rate | `filter_lfo_rate` | 0.01–5 Hz | 0.1 | Cutoff modulation speed |
| LFO Depth | `filter_lfo_depth` | 0.0–1.0 | 0.0 | Modulation amount (0 = off) |
| LFO Shape | `filter_lfo_shape` | sine / triangle / square | sine | LFO waveform |

Works on all layer types. Filter is applied after chorus.

#### Harmonics (V15)

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Harmonics | `harmonics` | 1–16 | 4 | Number of harmonic overtones per voice |
| Harmonic Decay | `harmonic_decay` | 0.0–1.0 | 0.7 | Amplitude decay per harmonic (0.7 = each partial is 70% of previous) |

#### Filtered Noise (V15)

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Noise Amount | `noise_amount` | 0.0–1.0 | 0.0 | Amount of noise mixed into the layer |
| Noise Color | `noise_color` | white/pink/brown | pink | Noise spectrum shape (white=flat, pink=1/f, brown=1/f²) |

#### Dynamics

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Mix | `dynamics.mix` | 0.0–1.0 | 1.0 | Layer volume in final mix |
| Amp Min | `dynamics.amp_min` | 0.0–1.0 | 0.001 | Minimum amplitude envelope |
| Amp Max | `dynamics.amp_max` | 0.0–1.0 | 0.05 | Maximum amplitude envelope |
| Drift | `dynamics.drift` | 0.0–0.1 | 0.01 | Pitch drift amount (organic beating) |

#### Spatial Motion

| Setting | YAML Key | Values | Default | Description |
|---------|----------|--------|---------|-------------|
| Quadrant | `spatial_motion.quadrant` | center, front_left, front_right, rear_left, rear_right | center | Starting stereo position |
| Speed | `spatial_motion.speed` | 0.0–1.0 | 0.01 | Spatial movement speed |
| Trajectory X | `spatial_motion.trajectory_x` | none, drift, orbit, bounce, random | none | Horizontal motion pattern |
| Trajectory Y | `spatial_motion.trajectory_y` | none, drift, orbit, bounce, random | none | Depth motion pattern |

#### Elevation Panning (V15)

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Elevation | `elevation` | -90 to +90° | 0.0 | Vertical angle (negative=below, positive=above) |
| Elevation Motion | `elevation_motion` | static, rise, fall, float, breathe | static | Vertical movement pattern |
| Elevation Speed | `elevation_speed` | 0.0–1.0 | 0.1 | Speed of elevation movement |
| Elevation Range | `elevation_range` | 0–180° | 60.0 | Sweep range for elevation motion |

Elevation panning uses HRTF-like frequency filtering: high elevation boosts high frequencies and attenuates lows (sound "above"), low elevation does the opposite (sound "below"). Uses an 800 Hz Butterworth crossover.

### Reverb (FDN)

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Enabled | `reverb.enabled` | true/false | false | Toggle reverb |
| Space | `reverb.space` | cathedral, chamber, hall, cave, plate | cathedral | Reverb character preset |
| Mix | `reverb.mix` | 0.0–1.0 | 0.3 | Dry/wet balance |
| Decay Trim | `reverb.decay_trim` | 0.0–2.0 | 1.0 | Multiplier on decay length |

The FDN reverb uses an 8-line Feedback Delay Network with Hadamard mixing, per-line damping, and stereo decorrelation.

### Binaural Beats

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Enabled | `binaural.enabled` | true/false | false | Toggle binaural |
| Method | `binaural.method` | detune, carrier | detune | Beat generation mode |
| Beat Hz | `binaural.beat_hz` | 0.5–40 Hz | 6.0 | Perceived beat frequency |
| Carrier Hz | `binaural.carrier_hz` | 50–500 Hz | 200.0 | Base frequency (carrier mode only) |
| Carrier Amplitude | `binaural.carrier_amplitude` | 0.0–1.0 | 0.15 | Carrier level (carrier mode only) |

**Brainwave bands:** Delta 0.5–4 Hz (sleep) · Theta 4–8 Hz (meditation) · Alpha 8–13 Hz (focus) · Beta 13–30 Hz (alert) · Gamma 30–100 Hz (peak)

### Earth (Sub-bass Texture)

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Enabled | `earth.enabled` | true/false | false | Toggle earth rumble |
| Tectonic Frequency | `earth.tectonic_frequency` | 10–40 Hz | 18 | Sub-bass center frequency |
| Pressure | `earth.pressure` | 0.0–1.0 | 0.4 | Earth layer intensity |
| Movement | `earth.movement` | 0.0–0.1 | 0.02 | Slow tectonic drift |

### Air (High-frequency Texture)

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Enabled | `air.enabled` | true/false | false | Toggle air/breath texture |
| Intensity | `air.intensity` | 0.0–1.0 | 0.12 | Air layer volume |
| Movement | `air.movement` | 0.0–0.1 | 0.01 | Air drift speed |
| Turbulence | `air.turbulence` | 0.0–0.2 | 0.04 | High-freq turbulence amount |

### Spatial

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Depth | `spatial.depth` | 0.0–5.0 | 1.0 | Overall spatial spread |
| Wetness | `spatial.wetness` | 0.0–1.0 | 0.7 | Spatial processing wet mix |
| Swarm Density | `spatial.swarm_density` | 0.0–1.0 | 0.5 | Voice swarm spread |

---

## Preset YAML Structure (V2)

```yaml
meta:
  name: My Drone
  category: sacred
  description: A meditative drone...
  tags: [sacred, ambient]

global:
  duration_seconds: 60
  sample_rate: 44100
  bit_depth: 16-bit

saturation: 0.3        # Master warmth (0=clean, 1=heavy saturation)

reverb:
  enabled: true
  space: cathedral
  mix: 0.4
  decay_trim: 1.0

binaural:
  enabled: true
  method: detune
  beat_hz: 6.0

spatial:
  depth: 2.0
  wetness: 0.5
  swarm_density: 0.5

earth:
  enabled: true
  tectonic_frequency: 18
  pressure: 0.3
  movement: 0.02

air:
  enabled: false

layers:
  - name: Foundation
    enabled: true
    synthesis:
      root: 110
      voices: 8
      ratios: [1.0, 2.0, 3.0]
    fm:
      ratios: [1.0, 2.0]
      index: 0.3
    dynamics:
      mix: 1.0
      amp_min: 0.005
      amp_max: 0.08
      drift: 0.003
    harmonics: 6                # V15: overtone count
    harmonic_decay: 0.7         # V15: partial decay
    noise_amount: 0.02          # V15: filtered noise
    noise_color: pink           # V15: white/pink/brown
    elevation: 30               # V15: vertical angle (-90 to +90)
    elevation_motion: float     # V15: static/rise/fall/float/breathe
    elevation_speed: 0.08       # V15: motion speed
    elevation_range: 60         # V15: sweep range
    spatial_motion:
      quadrant: front_left
      speed: 0.03
      trajectory_x: orbit
      trajectory_y: none
```

---

## Web UI Features

- **Preset browser** — sidebar with all categories, click to load
- **Parameter editor** — sliders for every layer parameter
- **Aurora ribbon visualization** — per-layer frequency ribbons + global RMS ribbon
- **Log-scale spectrum analyzer** — 20 Hz to Nyquist
- **Transport** — Play, Stop, Render (full), Download
- **Generator panel** — mood selector + generate/mutate buttons
- **Format selector** — WAV, FLAC, OGG export
- **Hi-Res toggle** — 48kHz/24-bit mode
- **Settings reference** — ⓘ button opens in-app docs modal

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Space | Preview / Play rendered audio |
| S | Stop |
| R | Render full audio |
| P | Play rendered audio |
| 1–5 | Switch to layer 1–5 |
| Ctrl+Z | Undo |
| Ctrl+Shift+Z | Redo |
| Ctrl+ / Ctrl- | Zoom in/out |

---

## What's New in V21.0

### Subtractive Synthesis
- New layer type: **Subtractive** — dual detuned oscillator pairs (saw/square/triangle) + sine sub-oscillator one octave below
- Classic Reese bass character: set waveform=saw, detune=15–25 cents, sub_mix=0.4–0.6
- Per-layer **biquad filter** (LP/HP/BP) with resonance, applied after synthesis
- Filter **LFO** modulates cutoff with sine/triangle/square at configurable rate and depth

### UI Restructuring
- Layer parameters reorganised into sub-tabs: **Synth** / **Filter** / **Space** / **FX**
- New **Global FX** card consolidates Binaural, Reverb, and Earth & Air in one place
- **Add / Remove** layer buttons (max 5 layers)
- Solo toggle now correctly un-solos on second click
- Chorus label added in FX tab

### Generator Improvements
- Generator now picks **FM or Subtractive** layers per mood profile (checkboxes: ☑ FM ☑ Subtractive)
- Layers capped at 3, voices at 12 (FM) / 6 (Subtractive) for streaming safety
- Mood-specific subtractive character: waveform, detune range, filter type, LFO rate/depth

### New Presets
| Preset | Category | Showcase |
|--------|----------|----------|
| **Reese Protocol** | experimental | Saw Reese bass + LP filter sweep + sub floor |
| **Steel Cathedral** | cinematic | Triangle choir + LP/BP moving filters + hall reverb |

### Bug Fixes
- Mutate after Generate now works correctly (nested v2 structure reconstruction)
- `preset_loader.py`: filter and subtractive fields now survive normalisation

---

## What's New in V15.0

### Audio Engine

- **Harmonic overtones** — each voice generates configurable partials (1–16) with exponential decay
- **Filtered noise** — per-layer noise injection (white/pink/brown) for organic texture
- **Soft saturation** — master bus warmth via normalized tanh waveshaping
- **Elevation panning** — HRTF-inspired vertical positioning with 5 motion patterns and 800 Hz crossover filtering

### New Presets

| Preset | Category | Showcase |
|--------|----------|----------|
| Cathedral Ascension | sacred | 4-layer vertical journey, earth to heaven |
| Breath of the Forest | experimental | Organic noise textures, natural movement |
| Singing Bowls | ritual | 8 harmonics, metallic inharmonic ratios |

### UI (from V13–V14)

- Aurora ribbon visualization (per-layer, frequency-reactive)
- Log-scale spectrum analyzer (20 Hz – Nyquist)
- Transport buttons in header bar
- 50/50 visualizer/spectrum layout

---

## What's new in V10.0

### Web UI

A full browser-based interface for MANTICE — no Node.js, no build step. Just Python.

```bash
python main.py --gui
```

### Voice cap: max 20 voices per layer

All presets have been capped to a maximum of 20 voices per layer.

### Architecture

```
python main.py --gui          →  engine/web_server.py  →  browser
python main.py --name "Om"    →  same engine core      →  file export
```

---

## What's new in V9.0

### Binaural beats

Binaural beats produce a phantom rhythmic pulse perceived in the brain when
slightly different frequencies are played to each ear. Requires **headphones**.

**Two modes:**

| Mode | How it works | Best for |
|------|-------------|----------|
| `detune` | Each voice is split into L/R with ±beat_hz/2 offset | Organic, integrated with musical content |
| `carrier` | Adds a dedicated pure-sine pair at a specified carrier frequency | Clinical precision, independent of music |

**Preset YAML syntax:**

```yaml
binaural:
  enabled: true
  method: detune          # or "carrier"
  beat_hz: 6.0            # perceived beat frequency (Hz)
  # carrier-mode only:
  carrier_hz: 200.0       # base frequency for the sine pair
  carrier_amplitude: 0.15 # level of the carrier layer
```

**Brainwave frequency guide:**

| Beat Hz | Band | State |
|---------|------|-------|
| 0.5–4 | Delta | Deep sleep, healing |
| 4–8 | Theta | Meditation, creativity |
| 8–13 | Alpha | Relaxed focus |
| 13–30 | Beta | Alertness |
| 30–100 | Gamma | Peak awareness |

### New preset: Theta Gateway

A dedicated binaural meditation drone at 6 Hz (theta band) built on the
136.1 Hz Om frequency. Three layers with minimal drift let the binaural
beating dominate the perceptual field. 5-minute default duration.

Located at: `presets/sacred/Theta Gateway.yaml`

---

## What's new in V8.0

### Random preset generator
- **`--generate`** creates random presets with musically-constrained randomness.
- **`--mood`** biases generation toward a sonic character:
  `dark`, `bright`, `cinematic`, `minimal`, `industrial`, `nature`, `chaotic`
- **`--generate-count N`** produces multiple presets in one run.
- Output is ephemeral (not saved to disk) — use **Share Link** to preserve a generated preset permanently.
- Generated presets include `meta.origin: "generated"` for traceability.

### Preset mutation
- **`--mutate "Preset Name"`** loads an existing preset and creates a random
  variation, preserving the overall character while introducing controlled chaos.
- **`--amount 0.0–1.0`** controls how wild the mutation is:
  - 0.1 = subtle (slightly different root frequencies, minor drift changes)
  - 0.5 = moderate (reharmonised, different spatial placement)
  - 1.0 = wild (layers may be added/removed, quadrants reassigned)
- Combinable with `--generate-count` to produce multiple mutations at once.

### Usage examples

```bash
# Generate a random dark preset
python main.py --generate --mood dark

# Generate 5 cinematic presets
python main.py --generate --mood cinematic --generate-count 5

# Mutate an existing preset (subtle)
python main.py --mutate "Breathing Cathedral" --amount 0.2

# Mutate with heavy variation, produce 3 variants
python main.py --mutate "Cavern of Echoes" --amount 0.7 --generate-count 3

# Reproducible generation
python main.py --generate --mood minimal --seed 42
```

### 8 new presets filling key gaps

| Preset | Category | Sonic territory |
|--------|----------|-----------------|
| **Abyssal Dread** | cinematic | Dark, dissonant, horror/tension |
| **Event Horizon** | cinematic | Epic, massive, multi-layered |
| **Iron Foundry** | cinematic | Industrial, metallic, mechanical |
| **Glass Firmament** | experimental | Bright, crystalline, shimmering |
| **Magnetic Tape** | experimental | Warm, lo-fi, analog character |
| **Solar Wind** | experimental | Chaotic, 140 voices, extreme density |
| **Primordial Forest** | ritual | Organic, nature-inspired, air-heavy |
| **Om** | sacred | Minimal, pure tone, meditative |

Total preset count: **25** across 5 categories (sacred, experimental, cinematic, ritual, subharmonic).

## What's new in V7.0

### Real-time preview
- **`--preview`** streams audio directly to your speakers via sounddevice.
  Hear your drone within ~50ms of pressing Enter — no waiting for full render.
- **Chunk-based streaming engine** (`engine/streaming_engine.py`): all voices,
  filters, panners, and the FDN reverb maintain state across chunks for
  seamless, glitch-free playback.

### Hot-reload
- **Edit your preset while it plays.** The preview watches the YAML file for
  changes. When you save, it automatically crossfades (3 seconds) from the old
  sound to the new parameters — no restart needed.
- Workflow: open the preset in your editor, tweak values, save → hear the
  difference immediately.

### Infinite mode
- **`--infinite`** removes the duration limit. The drone plays forever until
  you press Ctrl+C. Perfect for meditation, focus, or live performance.
- Can be combined with hot-reload for a live sound design session.

### Usage examples

```bash
# Preview a preset (plays for its configured duration)
python main.py --preview --name "Cavern of Echoes"

# Infinite drone — runs forever
python main.py --preview --name "Breathing Cathedral" --infinite

# Preview with custom duration
python main.py --preview --preset presets/sacred/Solar\ Choir.yaml --duration 30

# Live design session: start preview, then edit the YAML in your editor
python main.py --preview --preset presets/experimental/Cavern\ of\ Echoes.yaml --infinite
# (edit and save the YAML file → audio crossfades automatically)
```

### New dependency
- `sounddevice` — lightweight PortAudio wrapper for audio I/O.
  Only required for `--preview` mode; offline rendering works without it.

## Earlier Versions (V1–V6)

| Version | Key Features |
|---------|-------------|
| V6 | Progress bar, multi-format export (WAV/FLAC/OGG/MP3) |
| V5 | FDN reverb (8-line feedback delay network, Hadamard mixing) |
| V4 | Preset inheritance (`inherits:` key with deep merge, chaining) |
| V3 | CLI: `--list`, `--name`, `--duration` flags |
| V2 | Removed BellEngine, YAML V2 presets as primary format |
| V1 | Spatial positioning, earth/air engines, per-layer envelopes, sosfilt filters, unified preset loader |

---

## CLI Usage

```bash
pip install -r requirements.txt

# Web UI
python main.py --gui

# List available presets
python main.py --list

# Render a specific preset
python main.py --name "Breathing Cathedral"

# Custom duration
python main.py --name "Solar Choir" --duration 120

# Preview (real-time playback)
python main.py --preview --name "Cathedral Ascension"

# Infinite drone
python main.py --preview --name "Om" --infinite

# Generate random preset
python main.py --generate --mood dark

# Mutate existing preset
python main.py --mutate "Breathing Cathedral" --amount 0.3

# Export as FLAC
python main.py --name "Cavern" --format flac

# Reproducible output
python main.py --seed 42
```

## Requirements

- Python 3.8+
- `numpy`, `scipy`, `soundfile`, `pyyaml`
- `fastapi`, `uvicorn[standard]` (for `--gui`)
- `sounddevice` (for `--preview`)
- `ffmpeg` in PATH (for MP3 export only)
