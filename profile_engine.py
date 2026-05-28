"""
profile_engine.py
-----------------
Performance profiling tool for Mantice engine.

Profiles CPU time and memory usage for different synthesis modes.

Usage:
    python profile_engine.py                     # profile all modes (6s renders)
    python profile_engine.py --mode fm           # profile FM only
    python profile_engine.py --duration 30       # profile 30s renders
    python profile_engine.py --memory            # include memory profiling
    python profile_engine.py --compare           # compare FM/Sub/Gran side-by-side
"""

import cProfile
import pstats
import io
import sys
import time
import numpy as np
from pathlib import Path

# Import engine
from engine.streaming_engine import StreamingDroneEngine


# === BASE CONFIGURATIONS ===

_LAYER_BASE = {
    'name': 'Test',
    'muted': False,
    'quadrant': 'center',
    'trajectory_x': 'none',
    'trajectory_y': 'none',
    'speed': 0.01,
    'pan': 0.0,
    'width': 1.0,
    'elevation': 0.0,
    'elevation_motion': 'static',
    'elevation_speed': 0.1,
    'elevation_range': 60.0,
    'chorus_rate': 0.5,
    'chorus_depth': 0.005,
    'chorus_mix': 0.0,
    'chorus_voices': 2,
    'filter_type': 'off',
    'filter_cutoff': 2000.0,
    'filter_resonance': 1.0,
    'filter_lfo_rate': 0.1,
    'filter_lfo_depth': 0.0,
    'filter_lfo_shape': 'sine',
    'filter_vowel': 'a',
    'distortion_drive': 0.0,
    'distortion_type': 'soft',
    'waveform': 'saw',
    'detune_cents': 8.0,
    'sub_mix': 0.3,
    'harmonics': 4,
    'harmonic_decay': 0.7,
    'noise_amount': 0.0,
    'noise_color': 'pink'
}

_PRESET_BASE = {
    'seed': 42,
    'duration': 60,
    'spatial_depth': 1.0,
    'spatial_wet': 0.3,
    'swarm_density': 0.5,
    'saturation': 0.2,
    'binaural': None,
    'reverb': None,
    'earth': None,
    'air': None,
    'flanger': None,
    'master': {}
}


# === TEST PRESETS ===

PRESETS = {
    'fm': {
        **_PRESET_BASE,
        'name': 'FM_Test',
        'layers': [
            {
                **_LAYER_BASE,
                'type': 'fm',
                'voices': 4,
                'root': 55.0,
                'ratios': [1.0, 2.0],
                'fm_ratios': [1.0],
                'fm_index': 3.0,
                'drift': 0.05,
                'amp_min': 0.01,
                'amp_max': 0.03,
                'volume_db': 0.0,
                'band': 'mid'
            }
        ]
    },
    'sub': {
        **_PRESET_BASE,
        'name': 'Sub_Test',
        'layers': [
            {
                **_LAYER_BASE,
                'type': 'subtractive',
                'voices': 4,
                'root': 55.0,
                'ratios': [1.0],
                'fm_ratios': [1.0],
                'fm_index': 0.0,
                'waveform': 'saw',
                'drift': 0.05,
                'amp_min': 0.005,
                'amp_max': 0.02,
                'volume_db': 0.0,
                'band': 'mid'
            }
        ]
    },
    'gran': {
        **_PRESET_BASE,
        'name': 'Gran_Test',
        'layers': [
            {
                **_LAYER_BASE,
                'type': 'granular',
                'voices': 4,
                'root': 55.0,
                'source': 'singing_bowl.ogg',
                'grain_size': 80.0,
                'grain_density': 50,
                'grain_jitter': 0.5,
                'drift': 0.05,
                'amp_min': 0.01,
                'amp_max': 0.03,
                'volume_db': 0.0,
                'band': 'mid'
            }
        ]
    },
    'multi': {
        **_PRESET_BASE,
        'name': 'Multi_Layer',
        'layers': [
            {
                **_LAYER_BASE,
                'type': 'fm',
                'voices': 2,
                'root': 55.0,
                'ratios': [1.0, 2.0],
                'fm_ratios': [1.0],
                'fm_index': 2.0,
                'drift': 0.05,
                'amp_min': 0.01,
                'amp_max': 0.02,
                'volume_db': 0.0,
                'band': 'mid'
            },
            {
                **_LAYER_BASE,
                'type': 'subtractive',
                'voices': 2,
                'root': 55.0,
                'ratios': [1.0],
                'fm_ratios': [1.0],
                'fm_index': 0.0,
                'waveform': 'saw',
                'drift': 0.05,
                'amp_min': 0.005,
                'amp_max': 0.01,
                'volume_db': 0.0,
                'band': 'mid'
            },
            {
                **_LAYER_BASE,
                'type': 'granular',
                'voices': 2,
                'root': 55.0,
                'source': 'singing_bowl.ogg',
                'grain_size': 80.0,
                'grain_density': 40,
                'grain_jitter': 0.5,
                'drift': 0.05,
                'amp_min': 0.01,
                'amp_max': 0.02,
                'volume_db': 0.0,
                'band': 'mid'
            }
        ]
    }
}


def profile_preset(preset_name: str, preset: dict, duration: float = 6.0, sample_rate: int = 48000):
    """Profile a single preset render."""
    print(f"\n{'='*70}")
    print(f"Profiling: {preset_name} ({duration}s @ {sample_rate}Hz)")
    print(f"{'='*70}")
    
    # Create profiler
    profiler = cProfile.Profile()
    
    # Profile the render
    start_time = time.time()
    profiler.enable()
    
    engine = StreamingDroneEngine(preset, render_mode=True)
    total_samples = int(duration * sample_rate)
    chunk_size = 4096
    chunks = []
    remaining = total_samples
    
    while remaining > 0:
        n = min(chunk_size, remaining)
        chunk = engine.next_chunk(n)
        chunks.append(chunk)
        remaining -= n
    
    audio = np.vstack(chunks)
    
    profiler.disable()
    elapsed = time.time() - start_time
    
    # Calculate stats
    samples = audio.shape[0]
    channels = audio.shape[1]
    realtime_factor = duration / elapsed if elapsed > 0 else float('inf')
    
    print(f"\n--- Results ---")
    print(f"Duration:        {duration:.1f}s")
    print(f"Sample Rate:     {sample_rate} Hz")
    print(f"Samples:         {samples:,} ({channels} channels)")
    print(f"Render Time:     {elapsed:.3f}s")
    print(f"Realtime Factor: {realtime_factor:.2f}x")
    print(f"Peak:            {np.max(np.abs(audio)):.4f}")
    
    # Print top functions
    print(f"\n--- Top 20 CPU-Intensive Functions ---")
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s)
    ps.strip_dirs()
    ps.sort_stats('cumulative')
    ps.print_stats(20)
    print(s.getvalue())
    
    return {
        'preset': preset_name,
        'duration': duration,
        'elapsed': elapsed,
        'realtime_factor': realtime_factor,
        'samples': samples,
        'peak': float(np.max(np.abs(audio))),
        'profiler': profiler
    }


def profile_memory(preset_name: str, preset: dict, duration: float = 30.0):
    """Profile memory usage during render."""
    try:
        from memory_profiler import profile as mem_profile
        print(f"\n{'='*70}")
        print(f"Memory Profiling: {preset_name} ({duration}s)")
        print(f"{'='*70}")
        
        @mem_profile
        def render():
            engine = StreamingDroneEngine(preset, render_mode=True)
            total_samples = int(duration * 48000)
            chunk_size = 4096
            chunks = []
            remaining = total_samples
            
            while remaining > 0:
                n = min(chunk_size, remaining)
                chunk = engine.next_chunk(n)
                chunks.append(chunk)
                remaining -= n
            
            audio = np.vstack(chunks)
            return audio
        
        render()
        
    except ImportError:
        print("\n⚠️  memory_profiler not installed. Install with: pip install memory-profiler")
        print("    Memory profiling skipped.")


def compare_modes(duration: float = 6.0):
    """Compare FM, Sub, Gran side-by-side."""
    print(f"\n{'='*70}")
    print(f"PERFORMANCE COMPARISON ({duration}s renders @ 48kHz)")
    print(f"{'='*70}\n")
    
    results = []
    for mode in ['fm', 'sub', 'gran', 'multi']:
        result = profile_preset(mode.upper(), PRESETS[mode], duration)
        results.append(result)
    
    # Summary table
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"{'Mode':<12} {'Duration':<12} {'Render Time':<15} {'Realtime':<12} {'Peak':<10}")
    print(f"{'-'*70}")
    
    for r in results:
        print(f"{r['preset']:<12} {r['duration']:<12.1f} {r['elapsed']:<15.3f} {r['realtime_factor']:<12.2f}x {r['peak']:<10.4f}")
    
    print(f"{'='*70}\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Profile Mantice engine performance')
    parser.add_argument('--mode', choices=['fm', 'sub', 'gran', 'multi', 'all'], default='all',
                        help='Synthesis mode to profile')
    parser.add_argument('--duration', type=float, default=6.0,
                        help='Render duration in seconds (default: 6.0)')
    parser.add_argument('--memory', action='store_true',
                        help='Include memory profiling (requires memory_profiler)')
    parser.add_argument('--compare', action='store_true',
                        help='Compare all modes side-by-side')
    
    args = parser.parse_args()
    
    if args.compare:
        compare_modes(args.duration)
    elif args.mode == 'all':
        for mode in ['fm', 'sub', 'gran', 'multi']:
            profile_preset(mode.upper(), PRESETS[mode], args.duration)
    else:
        profile_preset(args.mode.upper(), PRESETS[args.mode], args.duration)
    
    if args.memory:
        mode = args.mode if args.mode != 'all' else 'fm'
        profile_memory(mode.upper(), PRESETS[mode], args.duration)


if __name__ == '__main__':
    main()
