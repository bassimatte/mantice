# Mantice Sound Volume and Normalization Status

**Status date:** 18 July 2026

## Executive summary

Mantice's largest structural volume problems have been repaired. The engine no longer wastes as much headroom on largely inaudible infrasonic Earth energy, and the six shipped wavetable presets now have substantially stronger audible bodies.

Mantice also has a shared true-peak safety ceiling for website and Python exports. However, it does **not yet have perceived-loudness normalization**. Quiet renders remain quiet because the existing final processor only attenuates signals that exceed its ceiling.

The next major step is conservative, bounded loudness normalization for completed website and Python downloads.

## Work completed

### 1. Safer master output defaults

The final output gain defaults to `0 dB` in both the website and Python render paths. This avoids unnecessary output boost and reduces clipping risk.

The default compressor retains `+4 dB` of makeup gain. This is part of the controlled compressor stage rather than an additional final output boost.

### 2. Infrasonic Earth repair

The largest gain-structure problem was hidden infrasonic energy. Earth generated a strong half-frequency component that commonly landed around 5–10 Hz. That signal consumed peak and RMS headroom while contributing little perceived loudness.

The repair:

- Activates the advertised default 20 Hz master high-pass filter.
- Removes Earth's half-frequency pressure component.
- Replaces it with an audible octave harmonic.
- Preserves the existing Earth controls and stereo behavior.
- Leaves Earth-disabled presets effectively unchanged.

Controlled measurements showed approximately:

- `+9.9 dB` of audible-band energy above 30 Hz for Warpy Cherry Leviathan.
- `+6.4 dB` above 30 Hz for Deep Hum.
- No meaningful change for the Earth-disabled Simple Drone control.

### 3. Wavetable preset repair

All six shipped wavetable presets were recalibrated at the layer level:

- Warpy Cherry Leviathan
- Warpy Cherry Supervoid
- Warpy Cherry Horizon Choir
- Cherry Picker Colonnade
- RND Abyss Monolith
- Chopper Siege Engine

The repair rebalanced wavetable, FM and Subtractive layers. Oscillator amplitude ranges were increased where layer volume alone could not recover the audible body. Roots, tuning, movement, filters, spatial design and effects were preserved.

Results across the six presets:

- Audible energy above 30 Hz increased by approximately `4.3–7.3 dB`.
- Finished full-band RMS falls between approximately `−20.4 and −17.5 dBFS`.
- Sample peaks remain between approximately `−9.0 and −6.9 dBFS`.
- Every reference render retains at least 6.9 dB of sample-peak headroom.

### 4. Current export safety ceiling

Website and Python renders use `final_limit_normalize()` at the end of the export path.

Despite its name, this function is a peak-safety stage rather than loudness normalization. It:

- Attenuates audio that exceeds the `−1 dB` true-peak ceiling.
- Does not boost quiet audio.
- Protects exported files from clipping.
- Preserves quiet renders at their original level.

Mantice therefore has true-peak protection, but it does not yet produce consistent perceived loudness across different presets.

## Work still required

### 1. Add loudness-aware normalization to static exports

The next recommended policy is:

- Integrated loudness target: approximately `−18 LUFS`.
- Maximum upward gain: `+9 dB`.
- Final true-peak ceiling: `−1 dBTP`.
- Attenuate loud renders when necessary.
- Do not force silence or extremely quiet material to the target.
- Apply the same implementation to website and Python exports.

The maximum gain is important. Without it, normalization could excessively amplify noise, sparse layers or long reverb tails.

Recommended processing order:

```text
Complete render
→ Measure integrated loudness
→ Calculate and apply bounded loudness gain
→ Apply the −1 dBTP safety ceiling
→ Export
```

### 2. Decide how normalization is exposed

Recommended behavior:

- Enable conservative loudness normalization by default for downloads.
- Offer an **Original dynamics** option for unnormalized exports.
- Keep the true-peak safety ceiling enabled in both modes.

Normalization should not be applied independently to short previews. Otherwise, a preview and the complete render could receive substantially different gain.

### 3. Calibrate the complete factory preset library

The wavetable presets have been repaired, but the rest of the factory library has not yet been calibrated against a formal loudness window.

Each preset should be measured with a fixed seed and duration for:

- Integrated LUFS
- True peak
- Audible-band RMS above 30 Hz
- Energy below 20 Hz
- Crest factor
- Limiter and compressor activity

Preset-level calibration should remain the first line of defence. Export normalization should control reasonable variation rather than conceal badly balanced presets.

### 4. Treat live playback separately

Integrated loudness cannot be known accurately before an infinite or live drone has played. Browser playback must therefore rely on:

- Correct preset gain staging
- Effective infrasonic filtering
- Master compression
- A conservative real-time limiter
- Potentially a very slow and transparent gain-control stage

Aggressive real-time automatic gain should be avoided because it could cause audible pumping as drones evolve.

### 5. Add volume diagnostics to the interface

Useful future master diagnostics include:

- Peak level
- Short-term loudness
- Limiter activity
- Compressor gain reduction
- Infrasonic-energy warning

These would make it easier to identify cases where a preset contains substantial signal energy but still has little perceived loudness.

### 6. Review remaining level inconsistencies

After normalization and library calibration, review:

- Wet/dry crossfades that may lose level around their midpoint.
- Standard and high-resolution export limiter behavior.
- Website and Python processing parity.
- Browser playback versus downloaded render levels.

## Recommended next implementation

Implement bounded `−18 LUFS` normalization for completed website and Python downloads, followed by the existing `−1 dBTP` ceiling.

Before enabling it for all exports, compare a controlled reference set in three forms:

1. Current unnormalized output.
2. Loudness-normalized output.
3. A quiet output for which normalization reaches the `+9 dB` gain cap.

This comparison will show whether the target improves consistency without flattening Mantice's spacious dynamics.

## Current repository state

The infrasonic and wavetable preset repairs were committed and pushed to `main` in commit `de695fd` (`Improve low-frequency headroom and wavetable balance`). Loudness-aware normalization remains unimplemented.
