"""Related Weight / Pressure / Space arrangements of one seeded foundation."""
import copy
import random
from pathlib import Path

import yaml


ROLES = ('Weight', 'Pressure', 'Space')
DESCRIPTIONS = (
    'Deep foundation, warm body and restrained movement.',
    'Dense harmonics, slow beating and broad presence.',
    'Wide atmosphere, distant harmonics and a long decay.',
)


def generate_massive_candidates(seed=None, allowed_types=None, harmonic_mode=False,
                                harmonic_key='C', harmonic_scale='major'):
    # Local RNG: generation must not alter the running audio engine's randomness.
    from .generator import _CHROMATIC_NOTES, _SCALE_INTERVALS, _WAVETABLES, _GRANULAR_SAMPLES
    rng = random.Random(seed)
    seed = int(seed) if seed is not None else rng.randrange(2**31)
    rng = random.Random(seed)
    supported = ('fm', 'subtractive', 'granular', 'wavetable')
    palette = list(dict.fromkeys(allowed_types if allowed_types is not None else ['fm', 'subtractive']))
    if not palette or any(kind not in supported for kind in palette):
        raise ValueError('Select at least one supported synthesis type.')
    key = _CHROMATIC_NOTES.index(harmonic_key) if harmonic_key in _CHROMATIC_NOTES else 0
    scale = _SCALE_INTERVALS.get(harmonic_scale, _SCALE_INTERVALS['major'])
    notes = [midi for midi in range(26, 35)
             if not harmonic_mode or (midi - key) % 12 in scale]
    midi = rng.choice(notes)
    root = 440 * 2**((midi - 69) / 12)
    fifth = 2**(7/12) if harmonic_mode else 1.5
    ratios = [1.0, fifth, 2.0]
    if harmonic_mode and (midi + 7 - key) % 12 not in scale:
        ratios = [1.0, 2.0]
    bass_type = next(kind for kind in ('fm', 'subtractive', 'wavetable', 'granular') if kind in palette)
    plan = [bass_type, 'subtractive' if 'subtractive' in palette else bass_type]
    plan.extend(kind for kind in palette if kind not in plan)
    while len(plan) < 4:
        plan.append('fm' if 'fm' in palette else palette[len(plan) % len(palette)])
    wavetable, wavetable_name = rng.choice(_WAVETABLES)
    sample = rng.choice(_GRANULAR_SAMPLES)
    scan_start = rng.uniform(0.08, 0.38)
    amp_factors = [rng.uniform(0.90, 1.10) for _ in range(4)]
    cutoff_factor = rng.uniform(0.85, 1.15)
    motion_factor = rng.uniform(0.8, 1.2)
    family = rng.choice(('Glacial', 'Basalt', 'Orbital', 'Amber', 'Tectonic', 'Distant'))
    noun = rng.choice(('Horizon', 'Monolith', 'Continuum', 'Choir', 'Expanse', 'Field'))
    template_dir = Path(__file__).resolve().parent.parent / 'presets' / 'experimental'
    candidates = []
    for index, role in enumerate(ROLES):
        path = template_dir / f'Massive {chr(65 + index)} - {role}.yaml'
        preset = copy.deepcopy(yaml.safe_load(path.read_text(encoding='utf-8')))
        name = f'{family} {noun} - {role}'
        preset['meta'].update(name=name, slug=name.lower().replace(' ', '_'),
                              category='generated', mood=['massive', role.lower()],
                              description=DESCRIPTIONS[index], author='MANTICE Generator',
                              origin='generated')
        preset['seed'] = seed
        for slot, layer in enumerate(preset['layers']):
            kind = plan[slot]
            layer['type'] = kind
            layer['synthesis']['root'] = round(root * 2**slot, 6)
            layer['synthesis']['ratios'] = [1.0] if slot == 0 else ratios.copy()
            layer['dynamics']['amp_min'] *= amp_factors[slot]
            layer['dynamics']['amp_max'] *= amp_factors[slot]
            layer['filter_cutoff'] *= cutoff_factor if slot else 1.0
            layer['spatial_motion']['speed'] *= motion_factor
            if 'filter_lfo_rate' in layer:
                layer['filter_lfo_rate'] *= motion_factor
            if kind == 'fm' and slot == 1:
                layer['band'] = 'mid'
                layer['harmonics'] = 4
                layer['fm'] = {'ratios': [1.0, 2.0], 'index': (0.14, 0.45, 0.22)[index]}
            elif kind == 'subtractive':
                layer.update(waveform='triangle' if slot == 0 or index == 0 else 'saw',
                             detune_cents=0.5 if slot == 0 else (3, 6, 4)[index], sub_mix=0.0)
                layer['synthesis']['voices'] = min(6, layer['synthesis']['voices'])
            elif kind == 'wavetable':
                layer.update(wavetable_source=wavetable, wavetable_name=wavetable_name,
                             wavetable_frame_size=2048, wavetable_frames=256,
                             wavetable_position=scan_start, wavetable_scan_start=scan_start,
                             wavetable_scan_end=scan_start + 0.25,
                             wavetable_scan_rate=(0.0015, 0.003, 0.002)[index],
                             wavetable_scan_mode='sine', wavetable_scan_shape='sine',
                             wavetable_scan_direction='forward', wavetable_tremor_amount=0,
                             wavetable_audio_rate_scan=False,
                             wavetable_detune_cents=0.5 if slot == 0 else (3, 6, 4)[index])
                layer['synthesis']['voices'] = min(5, layer['synthesis']['voices'])
            elif kind == 'granular':
                # Explicit native pitch lets granular tune to synthesis.root.
                layer.update(source=sample, grain_size=180, density=(12, 18, 16)[index],
                             pitch_spread=0.01 if slot == 0 else 0.025,
                             pitch_mode='resample', pitch_semitones=0.0,
                             position=0.45, scatter=0.12, envelope='hann',
                             position_mode='linear', position_chaos=0.05,
                             stereo_width=0.0 if slot == 0 else 0.8)
                # Resolve the bundled sample's pitch so grain transposition follows tuning.
                import json
                cache_path = template_dir.parent.parent / 'samples' / 'pitch_cache.json'
                cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
                sample_hz = cache.get(sample) or 220.0
                layer['sample_root_hz'] = sample_hz
                layer['pitch_spread'] = 0.0 if harmonic_mode else layer['pitch_spread']
        candidates.append(preset)
    return candidates
