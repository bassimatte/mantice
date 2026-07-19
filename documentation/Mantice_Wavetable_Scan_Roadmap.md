# Mantice Wavetable Scan and Visualization Roadmap

**Status review:** 19 July 2026

## Context

User feedback identified three limitations in Mantice's wavetable layer:

1. The current `0–0.1 Hz` scan-rate range is too narrow for faster sound design.
2. The available Static, Forward and Ping-pong scan modes do not cover smooth, shaped or random motion.
3. Scan Start and Scan End are difficult to tune without seeing the wavetable frames.

Phase Plant is a useful interaction reference because it treats the current wavetable frame as a modulation target, provides varied modulation sources and gives generator modules responsive visual scopes. Mantice should borrow the clarity of those ideas without reproducing Phase Plant's complete modular system.

## Design position

Most of the feedback is valuable and fits Mantice. The waveform scope, richer shapes and smooth random movement should be added. Scan rate should also extend well beyond `0.1 Hz`, but audio-rate scanning must be treated as an experimental sound-design feature rather than a normal drone default.

Factory presets should retain their slow movement. New controls should expand what users can do without changing the character of existing presets.

## 1. Waveform scope and draggable scan range

This is the first recommended implementation because it makes the existing frame controls immediately easier to understand.

The wavetable layer should show two deliberately separate views:

- The waveform of the currently selected or interpolated frame.
- A fixed perspective terrain containing all frames in the wavetable.
- Scan Start and Scan End handles.
- An animated current-frame ridge in the terrain and playhead on the frame rail.
- Numeric frame values.

Proposed layout:

```text
┌──────────────────────────────────────────┐
│ CURRENT FRAME · 118                      │
│       ╭──╮       ╭────╮                  │
│ ──────╯  ╰───────╯    ╰────────          │
├──────────────────────────────────────────┤
│ ALL FRAMES (fixed perspective terrain)    │
│       ╱╲___╱╲___╱╲                        │
│    ╱╲___╱╲___╱╲                           │
│ 0        [ 24 ═══════●══════ 212 ]   255 │
│           start    current     end       │
└──────────────────────────────────────────┘
```

The upper waveform displays phase across one complete cycle and is allowed to morph as the interpolated frame changes. It must not contain a frame-position cursor. Below it, all frames are drawn as waveform ridges in a fixed perspective landscape: horizontal position is waveform phase, vertical displacement is sample amplitude, and depth is frame number. The current interpolated frame becomes a bright ridge while Start and End bound a translucent terrain region.

Precise frame editing remains on a separate horizontal rail under the terrain. Users can drag Start and End there, and the existing sliders update at the same time. Touch interaction selects the nearest handle so mobile users do not need pixel-perfect accuracy.

The browser should receive downsampled inspection data instead of the complete `256 × 2048` sample table as JSON. Canvas rendering should stop automatically when the layer panel is no longer visible.

## 2. Expanded scan-rate control

A linear `0–100 Hz` slider would make the slow range almost impossible to adjust. Use a split logarithmic mapping:

```text
0.001    0.01     0.1       1       10      100 Hz
  └──── slow drone ────┘     └── fast / audio-rate ──┘
```

The mapping should place `1 Hz` in the middle:

- Left half: `0.001–1 Hz`
- Right half: `1–100 Hz`
- Static remains a separate scan mode.

The value display should include cycle duration:

```text
0.005 Hz · 200s cycle
0.10 Hz  · 10s cycle
1.00 Hz  · 1s cycle
25 Hz    · 40ms cycle
```

Recommended release policy:

- Normal range: `0.001–20 Hz`.
- Advanced **Audio-rate scan** switch: unlock `20–100 Hz`.
- Warning: experimental and potentially aliasing.
- Preserve existing preset values and slow generator defaults.

Increasing the scan rate has little direct CPU cost because Mantice already interpolates frame positions per sample. Sound quality and aliasing are the larger concerns. Band-limited wavetable playback should be investigated before presenting 100 Hz as a fully polished range.

## 3. Additional scan shapes

Proposed modes:

| Mode | Behavior | Compatibility |
|---|---|---|
| Static | Hold one selected frame | Existing Static |
| Ramp Up | Start to End, then return immediately | Existing Forward |
| Ramp Down | End to Start, then return immediately | New |
| Triangle | Start to End to Start | Existing Ping-pong |
| Sine | Smooth acceleration and easing at both ends | New |
| Smooth Random | Wander between seeded random frame targets | New |

Use **Triangle** in the interface, with “Pyramid” in the tooltip if helpful. Existing values should migrate transparently:

```text
forward  → Ramp Up
pingpong → Triangle
static   → Static
```

Smooth Random should:

- Select deterministic targets from the preset seed.
- Interpolate continuously between targets.
- Stay inside Scan Start and Scan End.
- Preserve its state across streaming chunks and hot reloads.
- Produce the same sequence in browser and Python renders.

The first version needs only Rate and Smooth. A large collection of Chaos, Jitter and probability controls would make the layer unnecessarily difficult to understand.

## 4. Tremor modifier

The suggested “Shaky” behavior is best implemented as an independent modifier rather than another scan mode. **Tremor** fits Mantice's vocabulary.

```text
TREMOR                         [ On ]

Amount       12 frames
Rate         0.30 Hz
```

Processing order:

```text
Base scan shape
→ Add bounded, smoothed random tremor
→ Clamp to Scan Start and Scan End
```

This lets Sine, Triangle, Ramp and Smooth Random retain their basic motion while occasionally becoming unstable.

Start with two controls:

- **Amount:** maximum frame deviation.
- **Rate:** speed of the secondary disturbance.

The offset must be smoothed. Abrupt random frame jumps can produce clicks and harsh artifacts.

## Proposed compact wavetable UI

```text
WAVETABLE
Warpy Cherries · 256 frames             [ Change ]

┌────────────────────────────────────────────┐
│            animated waveform               │
├────────────────────────────────────────────┤
│ 0      [ 18 ═══════●════════ 224 ]     255 │
└────────────────────────────────────────────┘

Scan Start       18
Scan End        224
Mode       [ Sine ▾ ]

Scan Rate     0.008 Hz
              125s cycle

Tremor                              [ Off ]
```

Advanced audio-rate controls should remain collapsed by default.

## Technical model

The scanner should calculate a normalized phase and transform it through the chosen shape:

```text
Ramp Up       phase
Ramp Down     1 − phase
Triangle      1 − |2phase − 1|
Sine          0.5 − 0.5 cos(2πphase)
Smooth Random interpolated seeded targets
```

Then map the result into the selected frame range:

```text
frame = scan_start + shape × (scan_end − scan_start)
```

Tremor is added afterward and clamped to the range.

State that must survive streaming chunks and engine copies:

- Scan phase
- Random generator state
- Current and next random targets
- Smoothed tremor state

Website streaming and Python rendering must share the same algorithm.

## Scope data and performance

Add a safe inspection endpoint that returns:

- Actual frame count and frame size.
- Downsampled waveforms for visualization.
- Source metadata where available.

The browser should draw this data using Canvas. It should not receive the full table as JSON. Rendering at approximately 30 frames per second is sufficient, and animation should stop when the scope is detached or hidden.

For the first version, the client may calculate the visual playhead from the same scan parameters. Exact server-reported scan position can be added later if visual/audio synchronization proves necessary.

## Recommended implementation sequence

1. Waveform scope and draggable Scan Start/End handles.
2. Ramp Down, Sine and renamed Triangle modes.
3. Deterministic Smooth Random.
4. Tremor Amount and Rate.
5. Split-logarithmic `0.001–20 Hz` Scan Rate.
6. Experimental `20–100 Hz` range after aliasing evaluation and band-limiting work.

## Current implementation status

The frame-number Scan Start and Scan End controls are present. On 19 July 2026, all six roadmap items were implemented locally:

- Animated waveform for the currently interpolated frame.
- Current-frame playhead and selected-range overlay.
- Pointer and touch dragging of the nearest Start/End handle.
- Synchronization with the numeric frame sliders.
- Compact, safe inspection data for shipped and imported wavetables.
- Ramp Up and Ramp Down scan modes.
- Triangle as the clearer interface name for the existing Ping-pong behavior.
- Sine scanning with smooth acceleration and easing at both range boundaries.
- Deterministic Smooth Random scanning with seeded targets and cosine interpolation.
- Chunk-continuous random motion shared by website preview and Python rendering.
- Independent Tremor Amount in frames and Tremor Rate in Hz.
- Seeded, smoothed tremor constrained to the selected frame range and preserved through hot reloads.
- Split-logarithmic `0.001–20 Hz` Scan Rate with `1 Hz` at the slider midpoint.
- Frequency and cycle-duration readouts across the complete range.
- Collapsed Advanced Scan switch that unlocks the experimental `20–100 Hz` range.
- Per-voice FFT band-limited wavetable copies with scan-aware Nyquist guard bands.

The `20–100 Hz` range remains explicitly experimental: band-limiting substantially reduces oscillator aliasing, but rapid timbral modulation intentionally creates audible sidebands and can sound bright or rough with discontinuous source frames.
