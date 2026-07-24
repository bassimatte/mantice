# Mantice Native Plugin — Product Decision

**Decision date:** 24 July 2026
**Status:** Accepted for the next native milestone

## Decision

Build the native plugin as a **focused Mantice performance instrument**, not as
a full port of the browser/Python product.

The plugin should express Mantice's core sound and work reliably inside a DAW.
It should not promise that every web preset, synthesis engine, effect, gallery
feature, or render option will load identically. Full preset parity remains a
possible later project, contingent on a stable native core and demonstrated
user demand.

## Why this is the right boundary

Mantice's web/Python instrument already has four synthesis engines, asset-backed
presets, deep modulation, sharing, gallery workflows, offline rendering, and a
large interface. Porting all of that before validating the native instrument
would multiply compatibility, distribution, licensing, CPU, and support risk.

A focused instrument can become trustworthy sooner:

- the audio callback can remain allocation-free and deterministic;
- a smaller parameter surface is easier to automate musically;
- curated presets can be calibrated for DAW gain staging;
- state restore and host behaviour can be tested exhaustively;
- the native sound can develop a clear role instead of imitating the website
  incompletely.

## Version-one product promise

The first public native version should provide:

- FM and subtractive layers that cover the essential Mantice sound;
- continuous drone and MIDI-gated performance modes;
- slow drift, filter motion, stereo movement, chorus, space, saturation,
  Earth, and Air;
- a small bank of native presets designed and calibrated specifically for the
  plugin;
- host automation for a concise set of performance macros and key parameters;
- reliable state save/restore across supported hosts;
- click-free parameter changes and transport behaviour;
- stable loudness with documented headroom;
- predictable CPU use at 44.1, 48, 88.2, and 96 kHz and common buffer sizes.

## Explicitly outside version one

- importing the complete Python/YAML factory library;
- granular and wavetable file import;
- browser gallery, sharing, favourites, or remix lineage;
- Python rendering and website export parity;
- full shimmer, binaural, automation-breakpoint, and journey systems;
- visual parity with the browser interface.

These are exclusions, not promises for the next release.

## Compatibility language

Use separate identifiers for native presets and web/Python presets. A native
preset must record a native schema version. Do not silently accept a browser
preset and discard unsupported fields.

If cross-product preset import is added later, it must:

1. declare the supported source schema versions;
2. report every unsupported or approximated field;
3. package or resolve referenced assets;
4. pass a documented perceptual comparison suite;
5. never overwrite the source preset.

## Release gates

The native plugin is ready for a public test only when:

- automated DSP and state tests pass in Release builds;
- no allocation, lock, file access, or network access occurs in the audio
  callback;
- preset/state recall is deterministic;
- automation produces no clicks under fast and slow host ramps;
- mono, stereo, bypass, sample-rate change, buffer-size change, and transport
  restart are stable;
- a representative preset bank stays finite and within its peak/headroom
  limits;
- CPU measurements are published for at least 64, 128, 256, 512, and
  1024-sample buffers;
- the plugin is tested in a small declared host matrix;
- distribution licensing, signing, and notarisation are resolved.

## Reconsidering full parity

Reopen the parity decision only after the focused plugin has:

- a stable public release;
- evidence that users need web-to-plugin preset transfer;
- a versioned native preset schema;
- measured CPU room for additional engines;
- an asset-packaging design for granular and wavetable sources;
- ownership for ongoing cross-engine perceptual regression testing.

Until then, the native plugin and web/Python instrument share an identity and
sound philosophy, but they are separate products with honest capability
boundaries.
