# MANTICE — The Breath Behind the Drone

A procedural sacred/ambient drone generator with FM, subtractive, granular and wavetable
synthesis, spatial motion, binaural beats, evolving effects, and a real-time Web UI.

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
│  Railway (Python backend)                               │
│  FastAPI + NumPy/SciPy synthesis engine                 │
│  Streams PCM audio chunks to browser                    │
└─────────────────────────────────────────────────────────┘
```

**Local mode:** Both frontend and backend run on your machine (`python main.py --gui`).

### Signal Chain

```
Per-Layer (each layer independently):
  Synthesis (FM / Subtractive / Granular / Wavetable)
  → Filter (LP/HP/BP/Comb/Formant) + LFO
  → Distortion (tanh soft / hard clip)
  → Panner (quadrant + trajectory + elevation)
  → Chorus → Flanger → Phaser
  → sum into stereo bus

Global (after all layers are mixed):
  DC Block (18 Hz HP)
  → Soft Saturation (tanh warmth)
  → FDN Reverb (8-tap Feedback Delay Network)
  → Shimmer FX (pitch-shifted feedback tail)
  → Earth + Air (sub-bass rumble / breath texture — kept dry, post-reverb)
  → Master EQ + Compressor
  → Crossfade (hot-reload)
  → Binaural (absolutely last — psychoacoustic L/R preserved to headphones)

Offline export (website and Python):
  4× Oversampled Saturation → Convolution Reverb
  → non-boosting 4× true-peak check at −1 dBFS
```

---

## ⚡ Performance

MANTICE renders **2-3x faster than realtime** across all synthesis modes, with excellent memory efficiency.

### Rendering Speed (6s renders @ 48kHz)

| Mode | Realtime Factor | Render Time | Description |
|------|-----------------|-------------|-------------|
| **FM** | **75x** realtime | 0.08s | Fastest — pure FM synthesis |
| **Granular** | **59x** realtime | 0.10s | Excellent — sample-based |
| **Subtractive** | **52x** realtime | 0.12s | Great — saw/square waveforms |
| **Multi-layer** | **24x** realtime | 0.25s | Fast — 3 layers combined |

**All modes exceed realtime by a wide margin** — you can render hours of audio in seconds.

### Memory Usage (30s renders @ 48kHz)

| Mode | Peak Memory | Init Memory | Notes |
|------|-------------|-------------|-------|
| FM / Sub | ~45 MB | ~660 KB | Minimal footprint |
| Gran / Multi | ~49 MB | ~5 MB | Includes sample loading |

- ✅ **No memory leaks** — Linear scaling, predictable behavior
- ✅ **Efficient** — Only 2x audio size overhead
- ✅ **Segmented rendering available** — For very long renders (>60s)

### Optimization Details

See [PERFORMANCE_REPORT.md](PERFORMANCE_REPORT.md) and [MEMORY_REPORT.md](MEMORY_REPORT.md) for detailed profiling data.

**Key Optimizations:**
- Pre-computed compression parameters (2-3x speedup)
- Stateful filter processing (zero-copy streaming)
- NumPy vectorization throughout
- Efficient chunk-based rendering

---

## 🎛 Features

- **FM Synthesis** — up to 12 detuned voices per layer with configurable harmonics and harmonic decay
- **Subtractive Synthesis** — dual detuned oscillator pairs (saw/square/triangle) + sine sub-oscillator; classic Reese bass style
- **Granular Clouds** — sample-based grain synthesis with 17 CC0 sound sources (singing bowls, gongs, wind, etc.)
- **Wavetable Synthesis** — import WAV tables, scan frames slowly, and package imported tables with shared presets
- **Per-Layer Filter & LFO** — LP/HP/BP biquad, Comb (metallic resonance), and Formant (vowel shaping A/E/I/O/U) with LFO modulation
- **Per-Layer Distortion** — soft (tanh) and hard-clip waveshaping, 0–5 drive
- **Per-Layer Chorus** — multi-voice LFO-modulated delay for stereo width and organic animation
- **Per-Layer Flanger** — LFO comb sweep (0.5–10 ms) with feedback; independent wet/rate/depth/feedback per layer
- **Per-Layer Phaser** — 4-stage all-pass phase shift with configurable centre frequency, rate, depth, and feedback
- **Global Shimmer FX** — pitch-shifted feedback tail using a two-head circular buffer; selectable intervals (−12 to +24 semitones) with feedback control
- **Spatial Motion** — per-layer panning trajectories (orbit, drift, bounce) with elevation panning (HRTF-inspired)
- **Binaural Beats** — theta/delta/alpha entrainment; carrier mode (true L/R sine pair) and detune mode (energy-preserving cos²/sin² L/R alternation)
- **FDN Reverb** — 8-tap feedback delay network with Hadamard mixing, per-line damping, and stereo decorrelation
- **Master EQ & Compressor** — 5-band EQ plus feedforward compression; defaults are −18 dB / 2.5:1 / +4 dB makeup with 0 dB output gain
- **47 Presets** — across 5 categories (essentials, cinematic, experimental, sacred, subharmonic)
- **Real-time Web UI** — stream, tweak, save, and export from your browser; layer sub-tabs (Synth/Filter/Space/FX)
- **Generator** — one directly loaded preset from the original six mood algorithms plus Essential-inspired **Classic**, with FM/Sub/Granular engine switches
- **Preset Save/Load** — create, modify, share, and reconstruct website-exported YAML directly in Python

---

## 📦 Deployment

### GitHub Pages (frontend)
1. Push to GitHub
2. Settings → Pages → Source: `/docs` folder
3. Your UI is live at `https://bassimatte.github.io/mantice/`

### Railway (backend)
1. Create a Railway project and deploy from the GitHub repo
2. Railway auto-detects the `Dockerfile`
3. Add required service variables, such as `GITHUB_TOKEN` and `FREESOUND_API_KEY`
4. Backend runs at `https://mantice-production.up.railway.app`
5. Update `docs/index.html` and `engine/static/index.html` → `MANTICE_API_BASE` if the Railway URL changes

The Railway deployment config lives in `railway.toml`. It uses `/api/presets`
as the health check endpoint and the Docker container listens on Railway's
runtime `PORT` variable.

---

## All Settings Reference

### Global Settings

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Duration | `global.duration_seconds` | 1–3600 s | 60 | Total audio length |
| Sample Rate | `global.sample_rate` | 22050/48000 | 22050 | Audio sample rate |
| Bit Depth | `global.bit_depth` | 16-bit/24-bit | 16-bit | Output resolution |
| Seed | `seed` | any integer | random | Reproducible output |
| Saturation (Warmth) | `saturation` | 0.0–1.0 | 0.3 | Master soft saturation / tape warmth (normalized tanh waveshaping) |

### Master Bus

#### Master Compressor

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Threshold | `master.comp.threshold_db` | -40–0 dB | -18 | Level above which compression starts |
| Ratio | `master.comp.ratio` | 1–20 | 2.5 | Compression ratio (e.g. 4 = 4:1) |
| Attack | `master.comp.attack_ms` | 1–500 ms | 50 | Time to reach full compression after threshold crossed |
| Release | `master.comp.release_ms` | 10–2000 ms | 200 | Time to return to unity after level drops below threshold |
| Knee | `master.comp.knee_db` | 0–12 dB | 3 | Soft-knee width — gradual onset around threshold |
| Makeup Gain | `master.comp.makeup_db` | -6–12 dB | +4 | Gain applied after compression |
| Output Gain | `master.output_gain_db` | -6–12 dB | 0 | Final master gain; 0 dB preserves export headroom |

Missing or partial `master` sections receive these same defaults in the website and Python
loader. Explicit preset values always win. Offline exports then perform a non-boosting,
4× oversampled true-peak check at **−1 dBFS**: hot renders are attenuated uniformly and
quiet renders are left unchanged.

#### Master EQ

5-band EQ on the master bus. Bass and Air are shelving filters; Lo Mid and Hi Mid are
constant-Q peaking (bell) filters. Each band's **Freq** and **Q** sub-controls are
hidden when the band's gain is set to 0 dB, keeping the UI uncluttered.

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Low Cut Freq | `master.eq.low_cut_hz` | 20–400 Hz | 20 | High-pass cut-off — rolls off everything below this frequency |
| Bass Gain | `master.eq.bass_db` | −12–12 dB | 0 | Low-shelf boost/cut |
| Bass Freq | `master.eq.bass_hz` | 40–500 Hz | 100 | Low-shelf transition frequency |
| Lo Mid Gain | `master.eq.lo_mid_db` | −12–12 dB | 0 | Bell boost/cut in the low-mid range |
| Lo Mid Freq | `master.eq.lo_mid_hz` | 100–1000 Hz | 250 | Bell centre frequency |
| Lo Mid Q | `master.eq.lo_mid_q` | 0.3–5.0 | 1.0 | Bell width — higher Q = narrower peak |
| Hi Mid Gain | `master.eq.hi_mid_db` | −12–12 dB | 0 | Bell boost/cut in the high-mid range |
| Hi Mid Freq | `master.eq.hi_mid_hz` | 500–8000 Hz | 2500 | Bell centre frequency |
| Hi Mid Q | `master.eq.hi_mid_q` | 0.3–5.0 | 1.0 | Bell width |
| Air Gain | `master.eq.air_db` | −12–12 dB | 0 | High-shelf boost/cut |
| Air Freq | `master.eq.air_hz` | 2000–16000 Hz | 10000 | High-shelf transition frequency |

> **Backward compatibility** — old presets that use `master.eq.mid_db` are automatically
> mapped to Lo Mid gain; all other fields default to 0 / standard values.

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

Five filter types, applied after synthesis and before distortion in the per-layer chain:

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Filter Type | `filter_type` | off / lp / hp / bp / comb / formant | off | Filter type |
| Cutoff | `filter_cutoff` | 20–20000 Hz | 2000 | Cutoff frequency (LP/HP/BP); comb delay frequency (Comb) |
| Resonance / Feedback / Strength | `filter_resonance` | 0.1–8 | 1.0 | Q factor (LP/HP/BP); feedback gain 0–0.97 (Comb); wet mix (Formant) |
| Vowel | `filter_vowel` | a / e / i / o / u | a | Vowel shape — selects F1/F2/F3 formant frequencies (Formant only) |
| LFO Rate | `filter_lfo_rate` | 0.01–5 Hz | 0.1 | Cutoff modulation speed (LP/HP/BP only) |
| LFO Depth | `filter_lfo_depth` | 0.0–1.0 | 0.0 | Modulation amount — 0 = off (LP/HP/BP only) |
| LFO Shape | `filter_lfo_shape` | sine / triangle / square | sine | LFO waveform (LP/HP/BP only) |

**Comb filter** — feedforward FIR comb (`y[n] = x[n] + g·x[n−D]`) where D = SR / cutoff. Resonance maps to feedback gain (0–0.97). Produces metallic ringing and spectral combing.

**Formant filter** — three parallel Butterworth bandpass filters at human vowel formant frequencies. Vowels: A (800/1200/2500 Hz), E (400/2000/2800), I (270/2300/3000), O (570/850/2500), U (380/950/2200). Resonance sets the wet mix (0–1).

#### Per-Layer Distortion

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Drive | `distortion_drive` | 0.0–5.0 | 0.0 | Waveshaping intensity — 0 = bypassed |
| Type | `distortion_type` | soft / hard | soft | Soft = tanh (warm, analog); Hard = clipping (aggressive) |

Applied after the filter stage. Soft distortion uses normalised tanh waveshaping; hard clips at ±1.

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
| Volume | `dynamics.volume_db` | -60 to +6 dB | 0 dB | Layer gain in master mix (replaces old Mix + Loudness) |
| Amp Min | `dynamics.amp_min` | 0.0–1.0 | 0.001 | Per-voice minimum amplitude (internal tuning, not shown in UI) |
| Amp Max | `dynamics.amp_max` | 0.0–1.0 | 0.05 | Per-voice maximum amplitude (internal tuning, not shown in UI) |
| Drift | `dynamics.drift` | 0.0–0.1 | 0.01 | Pitch drift amount (organic beating) |

#### Unison (FM only)

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Spread | `spread` | 0–2 | 1.0 | Voice stereo field width: 0=mono, 1=default (π/8–3π/8), 2=full 0–π/2 |
| Blend | `blend` | 0–1 | 1.0 | Voice amplitude taper: 1=all equal, 0=centre-dominant pyramid window |

What makes sense for each layer type:

| Layer Style | Spread | Blend | Notes |
|-------------|--------|-------|-------|
| Mono sub / foundation | 0–0.3 | 0.8–1.0 | Wide spread kills low-end mono punch |
| Mid pad / harmonic cloud | 0.8–1.4 | 0.7–1.0 | Some spread adds air without losing body |
| High shimmer / overtone halo | 1.2–2.0 | 0.4–0.8 | Full spread + blend taper sounds lush |
| Solo lead tone | 0.3–0.7 | 0.9–1.0 | Slight spread for warmth; keep blend high for focus |
| Cluster / cluster noise | 1.0–2.0 | 0.5–0.7 | High spread + moderate blend creates diffuse clouds |

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

### Per-Layer Flanger

LFO-modulated comb delay applied independently per layer after chorus in the signal chain.

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Wet | `flanger_wet` | 0.0–1.0 | 0.0 (off) | Dry/wet balance — 0 bypasses the effect |
| Rate | `flanger_rate` | 0.01–2.0 Hz | 0.25 | LFO speed |
| Depth | `flanger_depth` | 0.0–1.0 | 0.5 | LFO sweep range (maps to 0.5–10 ms delay) |
| Feedback | `flanger_feedback` | 0.0–0.95 | 0.4 | Feedback amount — higher = more resonant comb coloration |

### Per-Layer Phaser

4-stage all-pass phase modulator applied per layer after flanger in the signal chain.

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Wet | `phaser_wet` | 0.0–1.0 | 0.0 (off) | Dry/wet balance — 0 bypasses the effect |
| Rate | `phaser_rate` | 0.01–2.0 Hz | 0.5 | LFO sweep speed |
| Depth | `phaser_depth` | 0.0–1.0 | 0.7 | LFO modulation depth |
| Centre Hz | `phaser_center_hz` | 100–8000 Hz | 800 | Base frequency of the all-pass sweep |
| Feedback | `phaser_feedback` | 0.0–0.95 | 0.0 | Feedback into the all-pass chain |
| Stages | `phaser_stages` | 2–8 | 4 | Number of all-pass stages (higher = more notches) |

### Shimmer FX (Global)

Pitch-shifted feedback tail inserted after FDN Reverb in the global signal chain.
Two read heads traverse a circular buffer at `2^(semitones/12)` speed; Hann-window
cross-fading (`sin²+cos²=1`) ensures gapless output. Feedback re-injects the shifted
signal for an ever-evolving, self-sustaining ethereal tail.

| Setting | YAML Key | Range | Default | Description |
|---------|----------|-------|---------|-------------|
| Wet | `shimmer.wet` | 0.0–1.0 | 0.0 (off) | Dry/wet mix — 0 bypasses the effect |
| Pitch | `shimmer.pitch_semitones` | −12 to +24 | 12.0 | Pitch shift in semitones (12 = octave up, 7 = fifth, etc.) |
| Feedback | `shimmer.feedback` | 0.0–0.95 | 0.5 | How much shimmer re-enters the buffer — higher = longer tail |

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
  sample_rate: 22050
  bit_depth: 16-bit

saturation: 0.3        # Master warmth (0=clean, 1=heavy saturation)

reverb:
  enabled: true
  space: cathedral
  mix: 0.4
  decay_trim: 1.0

shimmer:               # Global shimmer FX (post-reverb, pre-Earth&Air)
  wet: 0.3
  pitch_semitones: 12  # -12 / +5 / +7 / +12 / +19 / +24
  feedback: 0.5

binaural:
  enabled: true
  method: detune       # or "carrier"
  beat_hz: 6.0

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
      volume_db: 0.0   # layer gain in dB (replaces old mix: 0–1)
      amp_min: 0.005
      amp_max: 0.08
      drift: 0.003
    spread: 1.0        # voice stereo spread (0=mono, 2=full)
    blend: 1.0         # voice amplitude taper (0=pyramid, 1=equal)
    chorus_rate: 0.5
    chorus_depth: 0.005
    chorus_mix: 0.3
    flanger_wet: 0.0   # per-layer flanger (0 = off)
    phaser_wet: 0.0    # per-layer phaser  (0 = off)
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
- **Generator panel** — original six mood algorithms plus Classic, direct generation and preview, engine switches, history, and balanced mutation
- **Format selector** — WAV, FLAC, OGG, and MP3 export
- **Standard / Hi-Res export** — 22.05kHz/16-bit by default; optional 48kHz/24-bit mode
- **True-peak protection** — website and Python exports share a non-boosting −1 dBFS ceiling
- **Parameter Automation** — breakpoint timeline per parameter with lin/exp/S curves and 5 global templates
- **Just Intonation mode** — exact-fraction layer roots from a single tonic; zero-beating pure intervals
- **Settings reference** — ⓘ button opens in-app docs modal
- **Guided tours** — First Breath introduces the core workflow; the optional Deep Dive maps layers, tuning, FX, mastering, automation, morphing, and export

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

## What's New in V26.0

### Parameter Automation

Every parameter can now evolve over the duration of a render or stream. Open the **Automation** card and enable any global or per-layer parameter. Each row shows a compact inline breakpoint editor — up to three nodes with configurable timing (t%), value, and curve shape (linear / exponential / S-curve). Click the shape label to cycle through shapes; `+ mid` adds a midpoint at the largest gap; `− mid` removes it.

Five **global templates** (Journey, Arc, Breathe, Meditate, Sunrise) appear as quick-set pills at the top of the card — one click wires up a coherent automation across multiple parameters so you don't have to start from scratch.

The YAML format is backward-compatible: existing `{start, end, shape}` V1/V2 automation blocks are auto-promoted to V3 breakpoints on load.

### Just Intonation (JI) Tuning Mode

Enable **JI** in the Synth tab (or globally). Instead of snapping each layer root to 12-TET, all layer roots are derived from a single tonic via exact rational fractions (e.g. 3/2 for a perfect fifth, 5/4 for a major third). Intervals between layers are therefore pure — no beating on sustained drones. A `●` dot in the layer header confirms JI is active. Existing decimal-ratio presets still load without change.

### Audio Quality Improvements

- **4× oversampled master saturation** — the tanh waveshaper now runs at 4× internal sample rate to eliminate aliasing artefacts on harmonically rich material
- **True look-ahead limiter on render path** — replaces the per-chunk peak scaler; no more gain steps at chunk boundaries in exported files
- **Streaming click fixes** — five independent artefact sources eliminated: chunk-boundary gain jumps, AudioContext / engine sample-rate mismatch, air-state discontinuity across chunks, per-chunk noise rescaling, and chorus delay-line underflow

### UI Polish

- Spread & Blend controls moved under **Voice** (Synth tab), where they belong alongside the oscillator stack
- Generator panel compacted — FM/Sub controls on line 1, Harm/Chord/Maj on line 2; clean 2×3 mood grid

---

## What's New in V25.0

### Signal Chain Overhaul

- **Earth & Air moved post-reverb** — sub-bass rumble and breath texture are now added _after_ FDN Reverb so they remain dry and uncoloured by the room
- **Binaural moved last** — psychoacoustic L/R difference now reaches headphones without any further processing; carrier and detune modes both corrected
- **Streaming binaural** — binaural was silently absent from the real-time web preview; now fully implemented with energy-preserving `cos²/sin²` detune mode and proper carrier-pair sine generation
- **Preview = Export parity** — `DroneEngine` now delegates to `StreamingDroneEngine`, so CLI exports (`python main.py`) and the web "Render" button produce identical output

### Shimmer FX (Global)

- New global effect: **Shimmer** — two read heads on a circular buffer advance at `2^(semitones/12)` speed with Hann cross-fading (`sin²+cos²=1`); feedback creates an ever-building ethereal tail
- Selectable intervals: −12 / +5 / +7 / +12 / +19 / +24 semitones
- Position in chain: after FDN Reverb, before Earth & Air
- Tab added to **Global FX** card in UI (order: Reverb → Shimmer → Earth & Air → Binaural)

### Per-Layer Flanger & Phaser

- **Global Flanger removed** — flanger is now a per-layer effect with independent `flanger_wet/rate/depth/feedback`
- **Per-Layer Phaser added** — 4-stage all-pass phase modulator per layer with `phaser_wet/rate/depth/center_hz/feedback/stages`
- 9 presets migrated from global flanger to per-layer (Deep Orbit, Gear Meditation, Ice Cathedral, Solar Flare, Delta Pulse, Stellar Vowel, Liquid Chrome, Magnetic Sweep, Resonant Cave)

### Layer UI Reorganisation

- Layer parameters split into four sub-tabs: **Synth** / **Filter** / **Space** / **FX**
- FX tab contains: Chorus, Flanger, Phaser

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
  `dark`, `bright`, `cinematic`, `classic`, `minimal`, `industrial`, `nature`
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

# Essential-style warm, stable FM drone
python main.py --generate --mood classic --seed 42
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

## 📐 Master EQ — Filter Design

All EQ filters are implemented as single biquad **SOS (Second-Order Sections)** using
the Audio EQ Cookbook (R. Zölzer / R. W. Bristow-Johnson) formulas, applied via SciPy's
`sosfilt` for offline rendering and `sosfilt_zi` stateful form for gapless streaming.

### Low Cut — Butterworth High-Pass

A 2nd-order Butterworth high-pass generated by SciPy `butter`:

```
H(z) from butterworth(order=2, Wn=fc/Nyquist, btype='high')
```

Only applied when `low_cut_hz > 22 Hz`. Rolls off sub-bass content at −12 dB/octave.

### Bass — Low Shelf (S = √2 / 2)

Audio EQ Cookbook shelving filter at transition frequency `bass_hz`:

```
A  = 10^(gain_dB / 40)
w0 = 2π · fc / fs
α  = sin(w0) · √2 / 2

b0 = A·[(A+1) − (A−1)·cos(w0) + 2·√A·α]
b1 = 2A·[(A−1) − (A+1)·cos(w0)]
b2 = A·[(A+1) − (A−1)·cos(w0) − 2·√A·α]
a0 =    (A+1) + (A−1)·cos(w0) + 2·√A·α
a1 = −2·[(A−1) + (A+1)·cos(w0)]
a2 =    (A+1) + (A−1)·cos(w0) − 2·√A·α
```

Boosts/cuts frequencies below `bass_hz`. Fixed slope of ±6 dB/octave at shelf edge.

### Lo Mid / Hi Mid — Peaking Bell (constant-Q)

```
A  = 10^(gain_dB / 40)
w0 = 2π · fc / fs
α  = sin(w0) / (2 · Q)

b0 = 1 + α·A      b1 = −2·cos(w0)    b2 = 1 − α·A
a0 = 1 + α/A      a1 = −2·cos(w0)    a2 = 1 − α/A
```

Bell width is controlled by **Q**: `Q = fc / BW` where BW is the −3 dB bandwidth.
Higher Q = narrower, more surgical peak. At Q = 1.0: ~1 octave bandwidth.

### Air — High Shelf (S = √2 / 2)

Symmetric counterpart of the low shelf:

```
b0 = A·[(A+1) + (A−1)·cos(w0) + 2·√A·α]
b1 = −2A·[(A−1) + (A+1)·cos(w0)]
b2 = A·[(A+1) + (A−1)·cos(w0) − 2·√A·α]
a0 =    (A+1) − (A−1)·cos(w0) + 2·√A·α
a1 = 2·[(A−1) − (A+1)·cos(w0)]
a2 =    (A+1) − (A−1)·cos(w0) − 2·√A·α
```

Boosts/cuts frequencies above `air_hz`. Used for "air" or "presence" shaping.

### Filter Chain Order

Filters are chained in series in this fixed order:

```
Input → [Low Cut HP] → [Bass Shelf] → [Lo Mid Bell] → [Hi Mid Bell] → [Air Shelf] → Output
```

A band is **skipped entirely** (zero overhead) when its gain is within ±0.1 dB of 0.
This keeps the default pass-through case as efficient as possible.

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

# High-resolution (48kHz/24-bit)
python main.py --name "Om" --hires --duration 120

# Apply automation template
python main.py --name "Crystal Bowl" --auto-template journey --duration 300

# Render journey quick-set (multi-preset morphing)
python main.py --journey-template drift --duration 600 --hires

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

### Automation Templates

Apply pre-defined parameter automation curves to any preset:

- `journey` — Fade-in, filter opens, reverb builds, binaural drifts alpha→delta
- `arc` — Sweeping rise and fall, full frequency journey
- `breathe` — Gentle pulsing, in-out cycles
- `meditate` — Ultra-slow drift, minimal movement
- `sunrise` — Gradual brightening, low→high frequency shift
- `wander` — Random walk, seeded smooth chaos
- `trance` — Rhythmic cycling, hypnotic patterns
- `shimmer` — Fast high-frequency modulation
- `sustain` — Pure static drone, no automation (La Monte Young style)
- `drift` — Ultra-slow filter evolution (barely perceptible)
- `pulse` — Slow breathing envelope (classic drone technique)

### Journey Templates

Render multi-preset sequences with auto-selected presets and timed crossfades:

- `drift` (30s holds, 12s morphs, loop) — Very slow evolution for meditation/sleep
- `flow` (15s holds, 6s morphs, pingpong) — Smooth back-and-forth breathing texture
- `pulse` (8s holds, 2s morphs, loop) — Rhythmic cycling with crisp morphs
- `ceremony` (60s holds, 20s morphs, loop) — Monumental pace, very long holds
- `dawn` (20s holds, 8s morphs, one-shot) — One-time journey, no loop
- `shimmer` (4s holds, 1s morphs, pingpong) — Fast shifting, constantly morphing

Each template auto-selects 2-4 presets matching its keywords (e.g., "forest", "rain" for drift).

```bash
# Examples
python main.py --journey-template drift --duration 600 --hires
python main.py --journey-template ceremony --format flac --seed 42
python main.py --journey-template shimmer --duration 300
```

## Requirements

- Python 3.8+
- `numpy`, `scipy`, `soundfile`, `pyyaml`
- `fastapi`, `uvicorn[standard]` (for `--gui`)
- `sounddevice` (for `--preview`)
- `ffmpeg` in PATH (for MP3 export only)
