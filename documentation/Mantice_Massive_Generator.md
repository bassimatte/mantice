# Massive generator — local implementation

Select **Massive**, choose synthesis engines and optional HARM key/scale, then
press **Generate**. Preview the three arrangements and select one:

- **A · Weight:** deep foundation, warm body, restrained movement.
- **B · Pressure:** denser harmonics, slow beating, broad presence.
- **C · Space:** wider upper layers, distant harmonics, longer reverb.

Each batch shares its low root (roughly 37–58 Hz), source sample/wavetable,
preview seed and harmonic relationships. Roots are octave-related; the fifth
is omitted when it is outside the selected HARM scale. Each new batch varies
pitch, source, amplitude, filter cutoff and slow motion within bounded ranges.
Existing named moods retain their generation path and immediate playback.

The hand-authored `presets/experimental/Massive A/B/C` references are the
templates for the three arrangements. Four layers form bass, body, mantle and
halo. All checked engine types appear, and unchecked types are excluded.
If FM or Sub is available it supplies the low foundation; otherwise the selected
WT or granular engine supplies it. Granular transposition uses bundled sample
pitch metadata; its texture can be less tonally stable than an oscillator.

Massive previews last 20 seconds to reveal slow movement. Selecting a texture
uses the same synthesis seed for live playback, although preview runs at 48 kHz
and streaming runs at 22.05 kHz, so the two are not sample-identical.
The picker reuses existing fingerprints, Preview/Select buttons and exploration
history. Umami includes `massive` in `mantice_generator_completed`; selection
uses the existing `mantice_candidate_selected` A/B/C buckets.

This step does not change export normalization or add a new scoring algorithm.
The next listening pass should check a batch of trios, especially WT-only and
granular-only palettes, before treating the sound design as release-ready.

Run focused tests with:

```sh
python3 -m unittest test_massive_generator test_generator_intent test_analytics
node --test test_massive_generator_ui.cjs
```
