# Mantice Volume and Perceived Loudness Analysis

**Analysis date:** 18 July 2026
**Scope:** Synthesis layers, gain staging, Earth and Air beds, master processing, streaming playback, website export and Python export.

## Executive conclusion

The low-volume problem is real and measurable. It is not primarily caused by the browser or the master compressor.

The largest problem is that Mantice often produces strong **infrasonic energy** that consumes digital headroom without sounding loud. This is especially severe in the recent wavetable presets. The export path then applies an attenuation-only true-peak ceiling, so quiet material is never raised.

The result is a system where meters and peaks can look healthy while the audible part of the drone remains extremely quiet.

The correct repair is:

1. Remove hidden infrasonic headroom consumption.
2. Rebalance the audible bodies of affected presets.
3. Introduce conservative loudness-aware export.
4. Calibrate the complete preset library to a defined loudness window.

A blanket increase to the global output gain would not solve the underlying problem.

## Measurement methodology

All 62 shipped presets were measured using deterministic playback with seed 42. Representative presets were also rendered through isolated processing variants:

- Dry synthesis and per-layer processing
- Global effects without master processing
- Complete master chain
- Streaming preview mode
- Earth disabled
- Earth and Air disabled
- Master low-cut enabled at 30 Hz

The measurements include full-band RMS, peak level, energy above 30 Hz, frequency distribution and an A-weighted RMS diagnostic proxy.

The A-weighted values are useful for comparing perceived audibility, but they are not formal integrated LUFS measurements.

## Library-wide results

Across the 62 shipped presets:

- Median RMS: **−21.1 dBFS**
- RMS range: **−43.9 to −12.8 dBFS**
- Median peak: **−11.5 dBFS**
- Peak range: **−30.4 to −0.5 dBFS**
- Median A-weighted RMS proxy: **−41.3 dBFS**
- 40.5% of layer roots are below 100 Hz
- 70% of layer roots are below 200 Hz
- Median enabled reverb mix is 40%
- 90th-percentile enabled reverb mix is 50%

The approximately 30 dB difference between the quietest and loudest presets is too large for a curated preset library.

## Representative measurements

| Preset | Full RMS | RMS above 30 Hz | Peak | Primary finding |
|---|---:|---:|---:|---|
| Deep Hum | −14.1 dBFS | −23.1 dBFS | −6.0 dBFS | Strong infrasonic component |
| Breathing Cathedral | −15.5 dBFS | −22.2 dBFS | −5.9 dBFS | Large meter level, lower perceived level |
| Event Horizon | −15.3 dBFS | −26.2 dBFS | −6.0 dBFS | Most power is below 100 Hz |
| Warpy Cherry Leviathan | −15.7 dBFS | **−41.1 dBFS** | −10.4 dBFS | Almost all measured energy is infrasonic |
| Warpy Cherry Supervoid | −18.9 dBFS | **−41.4 dBFS** | −13.5 dBFS | Actual drone body is extremely quiet |
| Chopper Siege Engine | −15.4 dBFS | **−38.0 dBFS** | −10.0 dBFS | Earth dominates the complete signal |
| Void Monolith | −21.2 dBFS | Approximately −29 dBFS | −6.5 dBFS | Numerically quieter but perceptually louder |

These results demonstrate why peak and unweighted RMS meters are misleading for the affected presets.

## Root cause 1: Earth consumes the headroom

Earth generates its main tone at approximately 12–18 Hz and another pressure wave at half that frequency, commonly 6–9 Hz:

- [`engine/streaming_engine.py`](../engine/streaming_engine.py#L2077)

Its amplitude is directly proportional to `pressure`, which is commonly around `0.4`. This is enormous compared with synthesis-layer amplitudes that are often around `0.01–0.05` per voice.

The relevant Earth calculation is:

```python
earth = np.sin(2 * np.pi * (freq + wobble) * earth_t)
pressure_wave = np.sin(2 * np.pi * freq * 0.5 * earth_t) * 0.6
signal = (earth * 0.7 + pressure_wave * 0.3) * pressure
```

The processing order is currently:

```text
Drone layers
→ 18 Hz DC block
→ saturation
→ reverb
→ shimmer
→ Earth and Air added here
→ master EQ and compressor
→ limiter
```

Earth is added after the engine’s DC-blocking filter:

- [`engine/streaming_engine.py`](../engine/streaming_engine.py#L1730)
- [`engine/streaming_engine.py`](../engine/streaming_engine.py#L1761)

The default master low-cut value is 20 Hz, but the filter is only constructed when the value is greater than 22 Hz:

- [`engine/master_processing.py`](../engine/master_processing.py#L104)

Therefore the default 20 Hz low cut does not run at all.

The practical result is:

- The meters see a large signal.
- The limiter sees a large signal.
- The export true-peak ceiling sees a large signal.
- Most speakers and human hearing reproduce very little of that signal.
- The audible drone cannot be raised because infrasonic energy owns the available headroom.

This is the primary architectural cause of the perceived low volume.

## Root cause 2: the wavetable presets are under-gained

When Earth is disabled:

- Warpy Cherry Leviathan falls from −15.7 dBFS to approximately **−41.4 dBFS**.
- Warpy Cherry Supervoid falls to approximately **−42.8 dBFS**.
- Chopper Siege Engine falls to approximately **−38.3 dBFS**.

This proves that Earth creates the apparently healthy full-band measurement, while the actual wavetable, FM and subtractive drone body is roughly 20–25 dB quieter.

The affected presets combine several conservative choices:

- Small oscillator amplitudes
- Wavetable layer volumes around −13 to −20 dB
- Low FM and subtractive layer gains
- Very low fundamental frequencies
- Filtering
- Multiple wet/dry effects

The audible synthesis layers need genuine calibration. Raising Earth further or adding a global output boost would only conceal the imbalance.

## Root cause 3: “normalize” never raises quiet audio

The export function called `final_limit_normalize()` only attenuates signals whose oversampled true peak exceeds −1 dBTP:

- [`engine/post_processing.py`](../engine/post_processing.py#L15)

Its behavior is explicitly described in the code:

> Quiet renders are never boosted.

Consequently:

- A render peaking at −14 dBFS remains at −14 dBFS.
- A render with RMS at −35 dBFS remains at −35 dBFS.
- A render dominated by 12 Hz energy cannot be made perceptually loud.

The current function is a **true-peak ceiling**, not normalization in the conventional mastering sense. Calling the result normalized creates an expectation the implementation does not satisfy.

## Root cause 4: excessive low-frequency bias

Across the complete preset library:

- 40.5% of layer roots are below 100 Hz.
- 70% of layer roots are below 200 Hz.
- Some massive presets put more than 99% of their measured energy below 100 Hz.

Low-frequency drones need controlled upper harmonics and midrange structure to sound physically large. Infrasonic or near-infrasonic energy can look impressive on a meter while sounding weak on headphones and disappearing almost completely on phones, laptops and compact monitors.

Impossible Chamber illustrates the opposite behavior. Its unweighted RMS is approximately −19.4 dBFS, but it is among the strongest A-weighted presets because it contains useful audible midrange energy. It can sound louder than presets measuring −15 dBFS.

## Secondary contributor: wet/dry gain laws

Several effects use a linear crossfade:

```python
output = dry * (1.0 - mix) + wet * mix
```

The convolution reverb first RMS-matches the wet return and then applies this linear mix:

- [`engine/convolution_reverb.py`](../engine/convolution_reverb.py#L118)

When dry and wet signals are weakly correlated, a 50/50 linear crossfade can lose approximately 3 dB of power. Reverb, shimmer, chorus, flanger and phaser may accumulate additional attenuation.

This is a secondary problem. It does not explain the 20–30 dB discrepancies found in the quietest presets.

## Secondary contributor: standard website export mode

The standard-resolution website render constructs the engine with:

```python
render_mode=hires
```

- [`engine/web_server.py`](../engine/web_server.py#L1257)

When hi-res is disabled, `render_mode` is therefore false and the streaming limiter remains active during an offline render. That limiter can attenuate hot chunks and make standard and hi-res output levels diverge.

This is an export-path inconsistency, but it is not the primary cause of the overall low-volume problem.

## What is not causing the problem

### Browser playback

The browser does not apply a hidden permanent attenuation:

- PCM16 data is converted back to floating point at unity.
- The startup gain ramps from silence to exactly `1.0`.
- There is no persistent browser volume reduction in the Mantice signal graph.

Relevant code:

- [`engine/static/index.html`](../engine/static/index.html#L6255)
- [`engine/static/index.html`](../engine/static/index.html#L6303)

### Master compressor defaults

The default master compressor uses +4 dB of makeup gain:

- [`engine/preset_loader.py`](../engine/preset_loader.py#L45)

It normally raises the signal. It does not explain the general low-volume behavior.

### The 0 dB master output default

Changing the master output default from +3 dB to 0 dB reduced level by 3 dB, which is audible, but it cannot explain a measured preset spread of approximately 30 dB.

Restoring a blanket +3 dB default would make already-loud presets clip while barely helping the quietest ones.

## Recommended repair order

### 1. Fix infrasonic headroom first

- Move Earth before the protective high-pass stage.
- Make the default 20 Hz low cut operate as an actual filter.
- Reduce and constrain Earth’s amplitude.
- Consider moving Earth’s useful energy toward 25–45 Hz.
- Add controlled upper harmonics so Earth remains perceptible on smaller playback systems.
- Measure and cap Earth independently from the musical layers.

The goal is to preserve the physical character without allowing inaudible energy to own the master bus.

### 2. Rebalance the wavetable presets

The recent wavetable presets require approximately 12–20 dB more audible-band energy, depending on the preset.

This adjustment should come from:

- Oscillator amplitude calibration
- Layer `volume_db`
- Better balance between wavetable, FM and subtractive bodies
- Spectral support above the fundamental
- Reduced dependency on Earth for apparent size

Do not normalize every layer independently. Preserve the intended internal hierarchy and calibrate the complete preset at the master output.

### 3. Introduce loudness-aware export

A safe mastering sequence would be:

```text
Complete render
→ infrasonic protection
→ integrated loudness measurement
→ one static gain adjustment
→ conservative maximum gain cap
→ −1 dBTP true-peak ceiling
```

A possible starting target for drones is approximately −18 LUFS, with a deliberate acceptable window around −20 to −16 LUFS.

The gain must remain static over the complete render. This avoids pumping and preserves the slow dynamics of drones.

### 4. Calibrate every shipped preset

Every preset should be rendered over a representative duration and checked for:

- Integrated loudness
- Short-term loudness range
- True peak
- Crest factor
- Energy below 20 Hz
- Energy below 30 Hz
- Audible-band RMS
- Excessive concentration below 100 Hz

Intentional quiet presets can remain quieter, but they should stay within a documented and controlled range.

### 5. Add a master loudness and headroom meter

The UI should display:

- Master peak
- Short-term loudness
- Integrated loudness during rendering
- True-peak headroom
- Infrasonic energy warning

The existing per-layer peak meters cannot reveal that an apparently loud signal consists mainly of inaudible sub-bass.

### 6. Correct effect mix laws and export mode

After the primary gain structure is stable:

- Evaluate equal-power or compensated wet/dry behavior for reverb and shimmer.
- Calibrate wet returns instead of applying blanket gain assumptions.
- Ensure standard and hi-res website exports both use an offline render mode.
- Keep preview and export loudness behavior aligned.

## What should not be done

Avoid these shortcuts:

- Do not restore a blanket +3 dB master default as the main fix.
- Do not peak-normalize without first controlling infrasonic content.
- Do not normalize every layer separately.
- Do not place a fast dynamic limiter across evolving drones to chase loudness.
- Do not use full-band RMS alone to evaluate sub-heavy presets.
- Do not make Earth louder to create the impression of scale.

## Proposed acceptance criteria

A repaired Mantice loudness system should satisfy the following:

1. No shipped preset is dominated by energy below 20 Hz.
2. Earth cannot consume most of the master headroom.
3. Presets fall inside a controlled loudness window unless explicitly marked otherwise.
4. Standard and hi-res exports have comparable perceived loudness.
5. Preview and rendered output remain closely aligned.
6. Quiet renders can receive a safe, static loudness adjustment.
7. Final true peaks remain at or below −1 dBTP.
8. Large drones retain dynamics, depth and low-frequency weight without sounding weak on ordinary systems.

## Final assessment

Mantice’s low-volume behavior comes from a combination of three issues:

1. **Infrasonic Earth energy occupies the headroom.**
2. **Some preset bodies—especially the recent wavetable presets—are substantially under-gained.**
3. **The export ceiling never raises quiet audio.**

The most important insight is that a large numerical signal is not necessarily a loud audible signal. Mantice needs to manage perceptual loudness and infrasonic headroom separately.

Fix Earth first, calibrate the audible drone bodies second, and introduce conservative loudness-aware mastering only after those foundations are correct.
