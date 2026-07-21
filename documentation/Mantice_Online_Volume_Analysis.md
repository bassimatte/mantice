# Mantice Online Volume Analysis and Repair Plan

**Analysis date:** 21 July 2026
**Scope:** factory and community presets, desktop WebSocket preview, mobile/gallery segmented preview, website downloads, and Python exports.

## Conclusion

Mantice's online playback is objectively too quiet. The browser plays decoded audio at unity gain; the low level originates in the synthesis, spectral balance, preset calibration, and mastering paths.

The current system protects against excessive peaks but does not bring quiet material toward a consistent perceived loudness. Many drones also concentrate energy below the most perceptually useful range, leaving large amounts of digital headroom while sounding weak on headphones.

## Current measurements

All 63 factory presets were rendered through the current live-preview engine for ten seconds with seed 42. The first two seconds were discarded. A-weighted figures below are a comparative diagnostic proxy rather than formal integrated LUFS.

| Measurement | Median | Range |
|---|---:|---:|
| Full-band RMS | −22.5 dBFS | −44.2 to −13.9 dBFS |
| Sample peak | −11.6 dBFS | −30.2 to 0 dBFS |
| A-weighted proxy | −40.2 dBFS | −54.2 to −22.2 dBFS |

Additional findings:

- 29 of 63 factory presets peak below −12 dBFS.
- The median preset leaves approximately 10.6 dB of peak headroom below a −1 dB ceiling.
- 44 of 63 factory presets fall below −35 dBFS on the perceptual proxy.
- Factory preset perceived level spans more than 30 dB.
- Of 43 locally measurable community presets, 20 peak below −12 dBFS and 28 fall below −35 dBFS on the perceptual proxy.

Five community wavetable presets could not be included because their hashed wavetable assets were not present in the local checkout used for measurement.

## Causes

### No live loudness target

The desktop streaming limiter only attenuates chunks whose peaks exceed 0.92. It never raises quiet audio. Mobile and gallery audition segments similarly receive no upward loudness adjustment.

The final export processor named `final_limit_normalize()` is a true-peak safety ceiling. It attenuates signals above −1 dBTP but intentionally leaves quiet renders unchanged.

### Excessive low-frequency bias

The 63 factory presets contain 204 active layers:

- 131 layers are classified as `sub`.
- 50 presets contain a root below 100 Hz.
- 61 presets contain a root below 200 Hz.
- The median layer root is 110 Hz.

Low frequencies need substantially more signal energy to produce the same perceived loudness on headphones, phones, and small speakers.

### Destructive automatic sub filtering

Layers with roots below 200 Hz are automatically classified as `sub`. The current `sub` band then applies a fixed fourth-order low-pass at 140 Hz.

This removes many of the harmonics that make a low drone audible. Fourteen layers even have fundamentals at or above the cutoff, including Simple Drone's 164.8 Hz Octave Shimmer and Singing Bowls' 196 Hz Medium Bowl.

### Conservative source amplitudes

Across the factory library, median layer amplitude settings are approximately 0.006 minimum and 0.030 maximum. Several older presets use values near 0.001. These levels can remain far below the available headroom after filtering and spatial processing.

### Wet/dry power loss

Reverb, chorus, shimmer, flanger, and phaser use linear wet/dry crossfades. Weakly correlated dry and wet signals can lose roughly 3 dB near a 50% mix. Multiple stages can compound the loss.

### Master defaults do not solve perceived loudness

Factory presets receive +4 dB compressor makeup and 0 dB final output gain. The compressor provides a fixed lift and peak control, but it does not target perceived loudness.

Changing the output default from +3 dB to 0 dB reduced level by 3 dB. That is audible, but it cannot explain preset differences reaching 20–30 dB. Restoring a blanket gain would overload already-loud presets while leaving the weakest ones comparatively quiet.

### Browser playback is not attenuating Mantice

Desktop PCM16 is converted back to floating point at unity, and the startup gain ramps from silence to exactly 1.0. Mobile decoded audio is also connected to the destination without a permanent gain reduction.

## Local implementation

The first repair implements:

1. BS.1770-style K-weighted integrated loudness measurement with absolute and relative gating.
2. Completed-render normalization toward −18 LUFS, limited to +9 dB upward gain and followed by the existing −1 dBTP ceiling.
3. An `Original dynamics` option that retains the true-peak ceiling without upward normalization.
4. A slow live loudness controller targeting approximately −20 LUFS, capped at +9 dB, with conservative gain smoothing and peak protection.
5. The same live controller for desktop, mobile, gallery, and Python preview paths.
6. Preservation of the established 140 Hz `sub` filter for legacy presets. An adaptive experiment made familiar drones substantially brighter, so loudness correction remains broadband and does not silently change their spectral identity.

Nine factory outliers also receive deliberate preset-level calibration:

- Ice Cathedral
- Stellar Vowel
- Singing Bowls
- Time Suspended
- Breath of the Forest
- Raga of Stillness
- Delta Pulse
- Crystal Bowl Meditation
- Deep Orbit

Ice Cathedral required a content rebalance rather than more master gain. Its sparse granular layer produced isolated peaks while its sustained FM bodies were nearly inaudible, so the FM layers were strengthened and the blanket master trim was reduced.

The live controller deliberately moves upward slowly. It is intended to correct broad preset-level differences without following every swell and creating obvious pumping.

## Local validation result

After the system repair and targeted preset calibration, the ten-second live-preview measurement of all 63 factory presets is:

| Measurement | Median | Range |
|---|---:|---:|
| Integrated loudness | −21.1 LUFS | −26.8 to −19.2 LUFS |
| Sample peak | −7.4 dBFS | −17.5 to −0.7 dBFS |

- Five intentionally dark or sparse presets fall below −25 LUFS in the measured window; the quietest is −26.8 LUFS.
- Eleven presets peak below −12 dBFS, down from 29 before the repair.
- The remaining integrated-loudness variation is approximately 7.6 LU rather than more than 30 dB on the original perceptual proxy.
- A completed-render reference set confirms that ordinary presets reach −18 LUFS, loud presets are attenuated, weak presets receive no more than +9 dB, and true peaks remain below −1 dBTP.

## Follow-up work

The implementation does not eliminate the need for content mastering. The next steps should be:

1. Render every factory and community preset over a representative 30–60 second window and record integrated LUFS, short-term loudness, true peak, crest factor, and sub-30 Hz energy.
2. Calibrate outliers at the preset and layer level rather than relying entirely on normalization.
3. Store a deterministic loudness trim with curated presets so playback can begin close to target immediately.
4. If wider sub bandwidth is added later, expose it as an explicit per-layer option for new presets rather than changing legacy sounds.
5. Evaluate equal-power or compensated wet/dry laws effect by effect.
6. Add master peak, loudness, gain-reduction, and infrasonic-energy diagnostics to the interface.
7. Audit missing hashed community wavetable assets separately.

## Acceptance criteria

- Quiet factory and generated presets become comfortably audible without changing headphone volume.
- Live gain never exceeds +9 dB and does not create audible fast pumping.
- Completed normalized renders approach −18 LUFS where the gain cap permits.
- True peaks remain at or below −1 dBTP for completed renders.
- Original-dynamics exports remain available.
- Low drones retain their fundamentals while recovering enough upper harmonic energy to translate on ordinary headphones and speakers.
