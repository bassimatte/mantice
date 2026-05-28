"""
profile_memory.py
-----------------
Memory profiling tool for Mantice engine using tracemalloc.

Profiles memory usage patterns during long renders to identify leaks
and optimize memory allocation.

Usage:
    python profile_memory.py                     # profile all modes (30s renders)
    python profile_memory.py --mode fm           # profile FM only
    python profile_memory.py --duration 60       # profile 60s renders
    python profile_memory.py --compare           # compare all modes
"""

import tracemalloc
import gc
import time
import numpy as np
import sys
from pathlib import Path

# Import engine
from engine.streaming_engine import StreamingDroneEngine

# Import presets from profile_engine.py
sys.path.insert(0, str(Path(__file__).parent))
from profile_engine import PRESETS


def format_size(size_bytes):
    """Format bytes as human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def profile_memory(preset_name: str, preset: dict, duration: float = 30.0):
    """Profile memory usage during a long render."""
    print(f"\n{'='*70}")
    print(f"Memory Profiling: {preset_name} ({duration}s @ 48kHz)")
    print(f"{'='*70}")
    
    # Start memory tracking
    tracemalloc.start()
    gc.collect()
    
    # Baseline memory
    start_mem = tracemalloc.get_traced_memory()
    start_time = time.time()
    
    # Create engine
    engine = StreamingDroneEngine(preset, render_mode=True)
    after_init_mem = tracemalloc.get_traced_memory()
    
    # Render in chunks
    total_samples = int(duration * 48000)
    chunk_size = 4096
    chunks = []
    remaining = total_samples
    
    checkpoints = []
    checkpoint_interval = int(duration / 10)  # 10 checkpoints
    samples_per_checkpoint = checkpoint_interval * 48000
    samples_rendered = 0
    
    while remaining > 0:
        n = min(chunk_size, remaining)
        chunk = engine.next_chunk(n)
        chunks.append(chunk)
        remaining -= n
        samples_rendered += n
        
        # Memory checkpoint every N seconds
        if len(checkpoints) < 10 and samples_rendered >= (len(checkpoints) + 1) * samples_per_checkpoint:
            current_mem = tracemalloc.get_traced_memory()
            checkpoints.append({
                'time': samples_rendered / 48000,
                'current': current_mem[0],
                'peak': current_mem[1]
            })
    
    # Final memory
    audio = np.vstack(chunks)
    final_mem = tracemalloc.get_traced_memory()
    elapsed = time.time() - start_time
    
    # Get top memory allocations
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')
    
    # Stop tracking
    tracemalloc.stop()
    
    # Calculate stats
    init_memory = after_init_mem[0] - start_mem[0]
    render_memory = final_mem[0] - after_init_mem[0]
    peak_memory = final_mem[1]
    
    print(f"\n--- Memory Usage ---")
    print(f"Initialization:  {format_size(init_memory)}")
    print(f"Rendering:       {format_size(render_memory)}")
    print(f"Total Current:   {format_size(final_mem[0])}")
    print(f"Peak Memory:     {format_size(peak_memory)}")
    print(f"Audio Size:      {format_size(audio.nbytes)}")
    print(f"Render Time:     {elapsed:.3f}s")
    print(f"Realtime Factor: {duration / elapsed:.2f}x")
    
    print(f"\n--- Memory Over Time ---")
    print(f"{'Time (s)':<12} {'Current':<15} {'Peak':<15}")
    print(f"{'-'*42}")
    print(f"{'0.0':<12} {format_size(start_mem[0]):<15} {format_size(start_mem[1]):<15}")
    for cp in checkpoints:
        print(f"{cp['time']:<12.1f} {format_size(cp['current']):<15} {format_size(cp['peak']):<15}")
    print(f"{duration:<12.1f} {format_size(final_mem[0]):<15} {format_size(final_mem[1]):<15}")
    
    print(f"\n--- Top 10 Memory Allocations ---")
    for i, stat in enumerate(top_stats[:10], 1):
        frame = stat.traceback[0] if stat.traceback else None
        if frame:
            print(f"{i}. {frame.filename}:{frame.lineno}: {format_size(stat.size)}")
        else:
            print(f"{i}. Unknown location: {format_size(stat.size)}")
    
    return {
        'preset': preset_name,
        'duration': duration,
        'init_memory': init_memory,
        'render_memory': render_memory,
        'peak_memory': peak_memory,
        'audio_size': audio.nbytes,
        'elapsed': elapsed,
        'checkpoints': checkpoints
    }


def compare_modes(duration: float = 30.0):
    """Compare memory usage across all modes."""
    print(f"\n{'='*70}")
    print(f"MEMORY COMPARISON ({duration}s renders @ 48kHz)")
    print(f"{'='*70}\n")
    
    results = []
    for mode in ['fm', 'sub', 'gran', 'multi']:
        result = profile_memory(mode.upper(), PRESETS[mode], duration)
        results.append(result)
    
    # Summary table
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"{'Mode':<12} {'Init Mem':<15} {'Render Mem':<15} {'Peak Mem':<15} {'Audio Size':<15}")
    print(f"{'-'*70}")
    
    for r in results:
        print(f"{r['preset']:<12} {format_size(r['init_memory']):<15} "
              f"{format_size(r['render_memory']):<15} {format_size(r['peak_memory']):<15} "
              f"{format_size(r['audio_size']):<15}")
    
    print(f"{'='*70}\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Profile Mantice engine memory usage')
    parser.add_argument('--mode', choices=['fm', 'sub', 'gran', 'multi', 'all'], default='all',
                        help='Synthesis mode to profile')
    parser.add_argument('--duration', type=float, default=30.0,
                        help='Render duration in seconds (default: 30.0)')
    parser.add_argument('--compare', action='store_true',
                        help='Compare all modes side-by-side')
    
    args = parser.parse_args()
    
    if args.compare:
        compare_modes(args.duration)
    elif args.mode == 'all':
        for mode in ['fm', 'sub', 'gran', 'multi']:
            profile_memory(mode.upper(), PRESETS[mode], args.duration)
    else:
        profile_memory(args.mode.upper(), PRESETS[args.mode], args.duration)


if __name__ == '__main__':
    main()
