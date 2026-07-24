# Mantice — 360-Degree Product and Technical Assessment

**Snapshot:** 24 July 2026

**Branch assessed:** `dev`

**Baseline commit:** `60ef94e` (`Harden release integrity`)

## Executive assessment

Mantice has moved beyond being a synthesis experiment. It is now a distinctive
instrument with four synthesis engines, a recognisable visual identity, a large
preset library, live browser playback, offline rendering, sharing, discovery,
guided onboarding, and an emerging native plugin.

Its strongest quality is coherence of intent: Mantice is built specifically for
slow, evolving drones rather than trying to be a general-purpose synthesizer.
The wavetable terrain, spatial movement, deep effects, gallery, and generated
textures all support that identity.

The main risk is no longer a lack of features. It is the accumulated complexity
of delivering the same instrument through several paths:

- hosted web frontend and Python backend;
- local web frontend and local Python backend;
- streaming preview and offline export;
- factory, generated, imported, and shared presets;
- desktop and mobile interaction;
- an early native plugin implementation.

The next phase should therefore prioritise predictability, release discipline,
clarity, and measured sonic consistency. Mantice will improve more by making
every existing path trustworthy and understandable than by adding another major
synthesis feature.

## Current product footprint

At this snapshot Mantice includes:

- FM, subtractive, granular, and wavetable synthesis;
- per-layer filtering, modulation, distortion, chorus, flanger, phaser, and
  spatial movement;
- global FDN reverb, shimmer, Earth, Air, binaural processing, EQ, compression,
  and loudness control;
- 63 factory presets across five categories;
- 48 entries in the shared-preset manifest;
- a generator with named moods, Classic, selectable synthesis engines, and
  wavetable support;
- a full-width preset gallery with fingerprints, metadata, auditioning,
  favourites, play counts, and remix lineage;
- local and hosted browser modes;
- standard and high-resolution rendering;
- first-use and deep-dive guides;
- an experimental VST3/standalone target.

The automated release baseline currently passes:

- 95 of 95 unit and integration tests;
- 347 of 347 quick audio-quality checks;
- frontend parity between `engine/static/index.html` and `docs/index.html`;
- a local end-to-end WebSocket check covering audio, session metering, and a
  live control patch.

These are strong foundations, but real-device listening and interaction tests
remain manual.

## Product health scorecard

The scores below are directional, not scientific. They are intended to expose
relative strengths and investment needs.

| Area | Assessment | Score |
|---|---|---:|
| Product identity | Distinctive, focused, memorable, and increasingly coherent | 4.5/5 |
| Sonic range | Broad and unusually capable for drones | 4/5 |
| Preset value | Large library with several excellent demonstrations of the engine | 4/5 |
| Wavetable workflow | One of Mantice's most differentiated areas | 4/5 |
| Live browser experience | Capable and recently much more responsive | 3.5/5 |
| Mobile experience | Viable, but still needs real-device hardening | 3/5 |
| Generator | Powerful, but its model and results still need clearer expectations | 3/5 |
| Gallery and sharing | Ambitious discovery surface; integrity and immediacy need guarding | 3.5/5 |
| Export consistency | Much improved; parity must remain a permanent release gate | 4/5 |
| Reliability | Strong automated baseline after the P0 repair | 4/5 |
| Maintainability | Increasingly constrained by large frontend and engine modules | 2.5/5 |
| Documentation and onboarding | Substantial, helpful, and unusually complete | 4/5 |
| Search discoverability | Technically prepared, but content and external authority are early | 2.5/5 |
| Native plugin | Promising proof of direction, not yet a parity product | 2/5 |

## What Mantice does especially well

### A clear sound-world

Mantice has a point of view. Slow rates, wide spatial motion, subharmonic weight,
shimmer, granular clouds, and evolving wavetables produce a recognisable family
of sounds. The name, typography, colour system, vocabulary, and preset naming
reinforce the same atmosphere.

This is strategically important. The project should protect that specificity
rather than competing with general synthesizers on feature count.

### Deep synthesis without requiring a DAW

The hosted version makes a relatively sophisticated procedural instrument
available from a URL. The local application then removes hosted rendering limits
and offers a path to longer or higher-resolution work. This is a strong
progression from discovery to serious use.

### Wavetable differentiation

Mantice does more than play a wavetable. Frame-based scan ranges, bidirectional
motion, multiple scan waveforms, smooth random, tremor, note locking, unison,
terrain visualisation, imported assets, and shared-preset packaging make the
wavetable layer a meaningful product pillar.

### Reproducibility

Seeds, YAML presets, bundled assets, deterministic movement modes, and Python
rendering make sounds reconstructable. This is valuable for musicians and also
provides a good basis for automated regression testing.

### Documentation culture

The project already documents volume, normalisation, wavetable scanning, search
discoverability, local use, settings, and onboarding. Keeping design decisions
in the repository reduces the chance that future fixes unknowingly reverse
previous reasoning.

## Principal risks and opportunities

## 1. Release integrity

### Current state

The P0 release-integrity pass on `dev` repaired four concrete risks:

1. shared wavetable presets can now reconstruct their repository-backed assets
   directly;
2. the live loudness controller no longer creates a chunk-boundary gain step in
   `Gear Meditation`;
3. the FDN reverb is guarded against non-finite state and platform-specific
   matrix warnings;
4. live meters now belong to the active WebSocket session rather than a global
   or incorrectly routed HTTP endpoint.

The full automated baseline is green.

### Remaining risk

There is no repository CI workflow visible at this snapshot. Tests are valuable
only if they run automatically before code reaches production. The dual frontend
copies, shared assets, preset manifest, live backend, and static deployment make
manual-only release discipline fragile.

### Recommendation

Make release integrity a system rather than a cleanup event:

- run unit tests on every push and pull request;
- run the quick audio-quality suite on changes to the engine, presets, renderer,
  or post-processing;
- fail when the two frontend copies differ;
- validate every factory and shared preset plus every referenced asset;
- verify YAML-to-UI-to-YAML reconstruction;
- add a short WebSocket streaming smoke test;
- deploy `dev` to a staging backend before promoting `main`;
- use a written release checklist with real iOS, Android, desktop Safari,
  Chromium, and Firefox checks.

## 2. Sonic consistency and perceived loudness

### Current state

Mantice has corrected major causes of low perceived level:

- infrasonic Earth content no longer consumes disproportionate headroom;
- weak wavetable presets were rebalanced;
- web and Python master defaults were aligned;
- live playback has bounded loudness control;
- completed renders use bounded loudness normalisation and a true-peak ceiling;
- the default master output remains at 0 dB to protect headroom.

### Remaining risk

Perceived loudness varies with spectrum, density, effects, and playback device.
A single LUFS target does not guarantee equal subjective strength between a
sub-heavy monolith, a sparse high drone, and a granular texture. Aggressive
automatic compensation can also alter the intended tone or flatten dynamics.

### Recommendation

Build a small permanent reference set representing:

- a single low drone;
- a bright FM texture;
- a dense cinematic preset;
- a granular preset;
- a wavetable preset;
- an Earth-heavy subharmonic preset;
- a shimmer-heavy sacred preset.

For each reference, compare live preview, website export, and Python export.
Track integrated loudness, short-term loudness, true peak, crest factor, spectral
centroid, low-band energy, and audible transitions. Treat a change in timbre as
seriously as a change in level.

Do not solve remaining loudness differences with a blanket gain increase.

## 3. Generator trust and musical usefulness

### Current state

The generator has been through several interaction models. The present direction
restores the original named-mood algorithms, adds Classic for Essential-like
drones, and reserves deeper shaping for Custom. FM, Sub, Granular, and Wavetable
can participate in generation.

### Core problem

Users need to understand what is fixed, what is random, and what the current
sound contributes. When this is unclear, a generated result feels arbitrary even
if the algorithm is technically correct.

### Recommendation

Make the generator promise simple:

> Choose a musical family, optionally choose engines, hear three textures, then
> select one.

The interface should communicate:

- whether generation starts from scratch or from the loaded sound;
- whether Harmony and Tuning constrain the result;
- which engines are allowed and which were actually used;
- the seed of each candidate;
- the few most meaningful differences between candidates.

Judge generator quality through listening tests, not parameter diversity alone.
Create a fixed bank of seeds for every mood and reject algorithm changes that
reduce the proportion of immediately usable drones.

## 4. Presets, gallery, and sharing

### Current state

The gallery has become a genuine discovery surface rather than a file list.
Fingerprints, tags, metadata, inline auditioning, favourites, play counts, and
lineage give presets meaning and context.

### Risks

This area has already exposed several integrity problems:

- deleted or stale presets surviving in one surface;
- duplicate names;
- gallery and sidebar disagreement;
- shared assets not materialising correctly;
- newly shared presets appearing late;
- anonymous authors dominating the gallery.

These are manifestations of the same architectural issue: more than one
representation can behave as the source of truth.

### Recommendation

Define one canonical shared-preset record with:

- immutable preset ID;
- mutable display name;
- author identity;
- creation timestamp;
- parent/remix ID;
- YAML and gallery metadata;
- asset hashes and repository paths;
- visibility and deletion state;
- deterministic fingerprint.

Generate the sidebar and gallery from that record. Add an integrity test that
compares the manifest, YAML, JSON metadata, gallery cards, referenced assets, and
canonical IDs. Use tombstones or explicit visibility state for deletion instead
of leaving ambiguous stale files.

## 5. Interface clarity

### Current state

The UI has gained more legible colours, larger controls, default markers, value
bubbles, reset gestures, responsive cards, mobile preview controls, and guided
tours. These changes make a deep instrument more approachable.

### Core problem

The interface is carrying many expert controls in one large document. The
frontend is currently more than 10,000 lines in a single HTML file. Even when
individual sections are well designed, the total cognitive load is high.

### Recommendation

Organise the experience around three levels:

1. **Play** — transport, presets, generator, mutate, layer mix, and a small set
   of macro controls;
2. **Shape** — synth, filter, motion, space, and layer effects;
3. **Finish** — global effects, mastering, automation, and export.

Keep the transport and currently selected layer visible while navigating.
Prefer progressive disclosure over adding more permanent panels. Maintain a
compact summary for collapsed sections so users can understand the active sound
without opening every control group.

Control labels should answer three questions without documentation:

- what changes;
- in which unit;
- over what useful range.

## 6. Mobile interaction

### Current state

Recent work reduces control latency, adds a lightweight live-control protocol,
tries live WebSocket audio before compatibility fallback, and improves mobile
interaction handling. Automated tests cover routing and recovery logic.

### Remaining risk

Mobile browsers differ materially in autoplay policy, AudioContext suspension,
WebSocket behaviour, memory pressure, backgrounding, and touch event delivery.
Passing desktop automation does not prove the mobile instrument.

### Recommendation

Create a repeatable real-device matrix:

| Platform | Minimum checks |
|---|---|
| iPhone Safari | Start/stop, mute/solo, sliders, generator modal, background/foreground, reconnect |
| Android Chrome | Same checks plus long preview and network handoff |
| iPad Safari | Layout, touch targets, scrolling, drawer/modal positioning |
| Low-power phone | CPU stability, buffer underruns, thermal behaviour |

Measure:

- tap-to-audible-change latency;
- time to first sound;
- reconnect success;
- underruns during a five-minute preview;
- memory growth;
- percentage of controls reachable without accidental page scrolling.

The target should be an audible response within 150 ms for live-patchable
controls, with clear feedback when a structural change requires rebuilding.

## 7. Export and reconstruction parity

### Current state

Website-exported presets now reconstruct missing and partial master settings
correctly in Python. Standard Python rendering defaults to 22,050 Hz and 16-bit,
matching the normal website path. High-resolution local rendering remains
available without hosted limits.

### Recommendation

Treat parity as a contract:

- the same preset, seed, sample rate, and bit depth should reconstruct the same
  synthesis parameters;
- intentional differences between live and offline effects must be documented;
- every new field needs a default, UI mapping, YAML mapping, and round-trip test;
- asset-backed layers must resolve identically after sharing and cloning;
- export metadata should record engine version, seed, render settings, and
  normalisation mode.

Add a machine-readable preset schema and version migrations before the format
accumulates more compatibility cases.

## 8. Performance and responsiveness

### Current state

Chunk size and preview lookahead have been reduced, safe controls can be patched
without rebuilding synthesis layers, and mobile now attempts the same streaming
path before falling back. This directly improves musical interaction.

### Remaining opportunity

Latency needs observability. Without measurements it is difficult to distinguish
network delay, backend synthesis time, browser scheduling, buffering, and a
structural engine reload.

### Recommendation

Instrument the preview path with optional diagnostics:

- control event timestamp;
- server receipt timestamp;
- patch application chunk;
- audio chunk generation time;
- queued browser duration;
- underrun and reconnect count.

Display this only in a diagnostics panel. Track p50 and p95 control-to-audio
latency on hosted desktop, hosted mobile, and local mode.

## 9. Architecture and maintainability

### Current state

Mantice's architecture is understandable at the system level, but several
implementation units are becoming difficult to change safely:

- `engine/static/index.html` is over 10,000 lines;
- `engine/web_server.py` is over 2,800 lines;
- `engine/streaming_engine.py` is over 2,500 lines;
- the static frontend is duplicated into `docs/index.html`.

The test suite is increasingly compensating for this complexity, which is good,
but test coverage alone does not remove coupling.

### Recommendation

Refactor incrementally, with no visual rewrite:

- split frontend code into state, transport, preset/gallery, generator,
  wavetable, guide, and rendering modules;
- generate or copy the deployed frontend from one canonical source;
- split WebSocket streaming, preset APIs, gallery APIs, render jobs, and asset
  management into focused backend modules;
- separate synthesis state from live control application in the streaming
  engine;
- centralise parameter definitions, defaults, units, ranges, and serialization;
- introduce a versioned preset schema used by Python and the browser.

Each extraction should preserve behaviour and land with tests. A big-bang
framework rewrite would add risk without directly improving the instrument.

## 10. Documentation and onboarding

### Current state

First Breath gives a short first-use path, Deep Dive covers advanced synthesis
and effects, the UI contains settings information, and the README documents
local installation and parameter behaviour.

### Recommendation

Turn documentation into three explicit journeys:

1. **Hear something immediately** — choose a preset and play;
2. **Create a personal drone** — select or generate, mutate, tune, and shape;
3. **Finish and keep it** — share, export, or render locally.

Add short troubleshooting entries for:

- no sound or suspended mobile audio;
- connecting/buffering/stream lost;
- missing local dependencies;
- imported wavetable inspection failures;
- shared preset asset failures;
- differences between live, standard export, and high-resolution export.

Documentation examples should be regression-tested where practical so commands,
paths, and defaults do not drift.

## 11. Search, positioning, and community

### Current state

Mantice has basic technical SEO, structured data, a sitemap, social metadata,
and a discoverability roadmap. It also has natural community bridges through
Freesound and CarveToy.

### Recommendation

Search growth now depends more on useful crawlable content and credible external
references than on further homepage metadata.

The highest-value pages are:

- how to create a deep evolving ambient drone;
- how to turn a wavetable into a drone;
- browser drone synthesizer and generator;
- procedural ambient sound design with reproducible seeds;
- selected preset pages with descriptions, audio previews, and remix lineage.

Community posts should show the instrument through sound and workflow, not read
like generic promotion. Use two or three screenshots:

- the main sound-shaping interface;
- the wavetable terrain and scan controls;
- the gallery or generator with audible examples.

Track indexed pages, relevant non-branded impressions, click-through rate,
referring domains, preset auditions, and successful local installations.

## 12. Native plugin direction

### Current state

The VST3/standalone target demonstrates demand for lower-latency use inside a
music workflow, but it should be considered experimental until its synthesis,
preset, modulation, automation, and rendering behaviour are explicitly compared
with the Python engine.

### Recommendation

Do not promise full Mantice parity yet. Choose one of two clear positions:

- a focused Mantice performance instrument with a curated subset; or
- a full native port with versioned preset compatibility.

The focused subset is the lower-risk path. It should first deliver:

- sample-accurate stable audio;
- a small representative preset bank;
- host automation for essential macros;
- state save and restore;
- consistent loudness and no clicks;
- CPU profiling across common buffer sizes.

Only expand after that core passes repeatable DAW tests.

## Recommended roadmap

## P0 — Release integrity

**Status on `dev`: implemented and committed; not yet promoted to `main`.**

- repair repository-backed shared wavetable reconstruction;
- remove live chunk-boundary loudness steps;
- harden the FDN against warnings and non-finite state;
- deliver meters through the active preview session;
- pass unit, audio-quality, parity, and WebSocket checks;
- complete real-device iOS and Android listening before promotion.

## P1 — Trust, clarity, and repeatability

**Status on `dev`: implemented locally; validation in progress and not yet
committed or pushed.**

### 1. Automate the release gates

Implemented:

- `release_check.py` provides one local and CI entry point;
- GitHub Actions runs the gates on `dev`, `main`, and pull requests;
- checks cover unit/integration tests, the quick audio suite, frontend parity,
  shared-preset/asset integrity, sonic references, and an end-to-end WebSocket
  preview smoke test.

A separate staging deployment still requires deployment credentials and service
configuration outside the repository.

### 2. Build a permanent sonic reference suite

Implemented as a deterministic seven-preset suite covering low drone, bright FM,
dense cinematic, granular, wavetable, subharmonic, and shimmer sounds. It checks
website/Python reconstruction and records live/offline loudness, peak, crest
factor, spectral centroid, low-band energy, and stereo correlation.

### 3. Simplify the main workflow

Implemented as a persistent Play / Shape / Finish navigation layer. The
transport remains visible, the current preset/layer context stays in the
workflow bar, and only the cards relevant to the selected stage are shown.

### 4. Make presets and sharing canonical

Implemented through one versioned canonical record normalizer used by gallery,
sidebar, sharing, rename, and play-count writes. An integrity gate now verifies
manifest/YAML membership, unique display names, lineage, referenced wavetable
assets, and content hashes.

### 5. Measure live interaction

Implemented as an optional panel under Settings. It reports time to first sound,
estimated patch-to-audio time, server generation time, server lookahead, browser
queue, underruns, and reconnects. Real-device performance targets still require
measurement on iOS and Android hardware.

## P2 — Quality and scale

Implemented on `dev` as a behaviour-preserving quality pass:

- preset documents now carry a semantic schema version; unversioned presets
  migrate in memory and unsupported future versions fail clearly;
- gallery discovery metadata moved out of the web server, while the first pure
  workflow/context helpers moved out of the monolithic frontend;
- 21 fixed-seed generator candidates now have deterministic fingerprints plus
  drone-rate, pitch, cost, and diversity checks;
- all 63 factory presets now pass a short live-opening calibration gate for
  finite output, audibility, loudness bounds, and headroom, with subjective
  outliers reported for listening rather than automatically retuned;
- the static site now includes a crawlable factory preset atlas, an ambient
  drone synthesis guide, and a wavetable-to-drone guide;
- the native plugin is explicitly positioned as a focused Mantice performance
  instrument rather than a parity port. The complete decision and release gates
  are in `Mantice_Native_Plugin_Product_Decision.md`.

Remaining human work:

- listen to fixed-seed generator candidates and the four factory openings
  currently flagged by the calibration report;
- continue extracting frontend/backend responsibilities in small tested steps;
- measure native-plugin behaviour in real DAWs before any public release.

## P3 — Expansion

Only after P1 and P2 are stable:

- deeper plugin coverage;
- optional user accounts and synchronised favourites;
- curated community collections;
- richer remix graphs;
- additional synthesis or modulation engines;
- offline-capable or installable web application behaviour.

## Proposed release gates

A change should not reach `main` unless the applicable gates pass.

### Automated

- all unit and integration tests pass;
- quick audio-quality suite reports zero failures;
- every preset loads and renders finite audio;
- every shared asset exists and matches its reference;
- frontend source and deployment copy match;
- preset export/import round trips preserve all supported settings;
- WebSocket preview returns audio and session-specific meters;
- safe live patches do not rebuild synthesis layers;
- no new runtime warnings, NaN, Inf, clipping, or chunk-boundary clicks;
- HTML, YAML, JSON, and Python validation pass.

### Manual

- listen to the permanent reference set before and after the change;
- test hosted preview and rendering;
- test local preview and rendering;
- test iPhone Safari and Android Chrome;
- verify generator, gallery, sharing, and imported wavetable paths;
- confirm that a first-time user can reach sound, modify it, and export it
  without documentation.

## Product metrics worth tracking

Avoid vanity metrics. Track whether users reach and keep sound:

- time from page open to first sound;
- preview start success rate;
- median and p95 control-to-audible latency;
- stream failure and recovery rate;
- percentage of sessions that load a preset;
- percentage that modify or generate a sound;
- candidate preview-to-selection rate;
- share completion rate;
- gallery audition-to-load rate;
- export completion rate;
- local-install success rate;
- returning users and favourite reuse;
- preset/audio defects per release.

These should be privacy-conscious and optional where appropriate.

## What not to prioritise now

- another major synthesis engine;
- a complete visual redesign;
- blanket gain increases;
- a big-bang frontend framework rewrite;
- full plugin parity before the native core is stable;
- more generator controls without a simpler mental model;
- more shared-preset features before canonical data integrity is established.

## Recommended immediate sequence

1. Perform the manual iOS and Android checks for P0.
2. Push `dev` and exercise it through a staging deployment.
3. Add CI and make the current green baseline mandatory.
4. Establish the seven-preset sonic reference suite.
5. Define the canonical shared-preset schema and integrity audit.
6. Prototype the Play / Shape / Finish information architecture without
   changing synthesis behaviour.
7. Measure live latency before doing further performance optimisation.

## Definition of the next successful Mantice release

The next release should not be defined by the number of new controls. It should
be the release in which:

- every preset and bundled asset works wherever it appears;
- live changes feel immediate on desktop and mobile;
- live and rendered sound are intentionally consistent;
- generation is easy to predict and produces musically useful choices;
- sharing updates the gallery reliably;
- the principal workflows are understandable without explanation;
- automated checks prevent known classes of regression;
- the instrument retains its strange, slow, monumental character.

That would turn Mantice from a feature-rich browser synthesizer into a dependable
creative instrument.
