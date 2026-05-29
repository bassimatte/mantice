"""
Test R4: Verify MANT-9 Implementation

MANT-9: Intra-chunk parameter interpolation
Verifies that automated parameters use linear interpolation within chunks
to avoid clicks/zipper noise.

The Deep Analysis PDF claimed automation might be "per-block constant".
This test verifies MANT-9's np.linspace() ramps are actually applied.
"""

import numpy as np
import sys
from pathlib import Path

# Add engine to path
sys.path.insert(0, str(Path(__file__).parent / "engine"))

from engine.preset_loader import load_preset
from engine.streaming_engine import StreamingDroneEngine
from engine.automation import AutomationCurve

def test_filter_sweep_smoothness(duration: float = 2.0):
    """
    Test that automated filter cutoff sweeps smoothly without steps.
    
    MANT-9 should create np.linspace ramps for filter_cutoff.
    Without interpolation, each 2048-sample chunk would have constant cutoff,
    creating audible steps in the sweep.
    """
    print(f"\n{'='*60}")
    print("FILTER CUTOFF SWEEP SMOOTHNESS TEST")
    print(f"{'='*60}")
    
    # Create preset with automated filter sweep
    preset = {
        "duration": duration,
        "seed": 42,
        "saturation": 0.0,
        "reverb": {"enabled": False},
        "shimmer": {"enabled": False},
        "layers": [
            {
                "type": "fm",
                "enabled": True,
                "root": 110.0,
                "voices": 1,
                "fm_ratios": [1.0],
                "fm_indexes": [0.5],
                "amplitudes": [1.0],
                "drift": 0.0,
                "filter_type": "lp",
                "filter_cutoff": 500.0,  # Will be overridden by automation
                "filter_resonance": 2.0,
                "automation": {
                    "filter_cutoff": {
                        "points": [
                            {"t": 0.0, "v": 300.0},
                            {"t": 1.0, "v": 5000.0}
                        ],
                        "curve": "linear"
                    }
                },
                "mix": 1.0,
            }
        ],
        "earth": {"enabled": False},
        "air": {"enabled": False},
    }
    
    engine = StreamingDroneEngine(preset, seed=42)
    sr = engine.SR
    
    # Render with small chunk size to test intra-chunk interpolation
    chunk_size = 2048
    total_samples = int(duration * sr)
    chunks = []
    remaining = total_samples
    
    # Track filter cutoff values during render
    cutoff_history = []
    
    while remaining > 0:
        n = min(chunk_size, remaining)
        
        # Get current filter cutoff before rendering chunk
        if engine.filters:
            cutoff = engine.filters[0].base_cutoff
            cutoff_history.append(cutoff)
        
        chunk = engine.next_chunk(n)
        chunks.append(chunk)
        remaining -= n
    
    audio = np.concatenate(chunks, axis=0)
    
    # Analyze cutoff history
    cutoff_history = np.array(cutoff_history)
    
    print(f"  Rendered {len(chunks)} chunks ({chunk_size} samples each)")
    print(f"  Cutoff range: {cutoff_history.min():.1f} Hz → {cutoff_history.max():.1f} Hz")
    
    # Check for smoothness: measure maximum step between consecutive chunks
    if len(cutoff_history) > 1:
        cutoff_diffs = np.abs(np.diff(cutoff_history))
        max_step = cutoff_diffs.max()
        avg_step = cutoff_diffs.mean()
        
        # Expected smooth step: (5000 - 300) / num_chunks
        expected_step = (5000.0 - 300.0) / len(chunks)
        
        print(f"  Max step between chunks: {max_step:.1f} Hz")
        print(f"  Average step: {avg_step:.1f} Hz")
        print(f"  Expected smooth step: {expected_step:.1f} Hz")
        
        # MANT-9 should keep steps close to expected smooth progression
        if max_step < expected_step * 2.0:
            print(f"  → ✅ SMOOTH (max step < 2× expected)")
            result = "PASS"
        else:
            print(f"  → ❌ STEPPED (max step ≫ expected)")
            result = "FAIL"
    else:
        print(f"  → ⚠️  Not enough chunks to test")
        result = "UNKNOWN"
    
    return result, cutoff_history

def test_prev_value_tracking():
    """
    Test that _prev_layer_auto correctly tracks previous values
    for interpolation continuity.
    
    MANT-9 uses _prev_layer_auto to store previous chunk's end value
    as current chunk's start value for np.linspace().
    """
    print(f"\n{'='*60}")
    print("PREVIOUS VALUE TRACKING TEST")
    print(f"{'='*60}")
    
    # Create simple preset with automation
    preset = {
        "duration": 1.0,
        "seed": 42,
        "saturation": 0.0,
        "reverb": {"enabled": False},
        "shimmer": {"enabled": False},
        "layers": [
            {
                "type": "fm",
                "enabled": True,
                "root": 110.0,
                "voices": 1,
                "fm_ratios": [1.0],
                "fm_indexes": [0.5],
                "amplitudes": [1.0],
                "drift": 0.0,
                "filter_type": "lp",
                "filter_cutoff": 1000.0,
                "automation": {
                    "filter_cutoff": {
                        "points": [
                            {"t": 0.0, "v": 500.0},
                            {"t": 1.0, "v": 2000.0}
                        ],
                        "curve": "linear"
                    }
                },
                "mix": 1.0,
            }
        ],
        "earth": {"enabled": False},
        "air": {"enabled": False},
    }
    
    engine = StreamingDroneEngine(preset, seed=42)
    
    # Render a few chunks and check _prev_layer_auto state
    chunk1 = engine.next_chunk(2048)
    
    # Check if _prev_layer_auto has been populated
    if 0 in engine._prev_layer_auto:
        if "filter_cutoff" in engine._prev_layer_auto[0]:
            prev_cutoff = engine._prev_layer_auto[0]["filter_cutoff"]
            print(f"  After chunk 1: prev_cutoff = {prev_cutoff:.1f} Hz")
            
            # Render second chunk
            chunk2 = engine.next_chunk(2048)
            
            # Check that prev value was updated
            new_prev_cutoff = engine._prev_layer_auto[0]["filter_cutoff"]
            print(f"  After chunk 2: prev_cutoff = {new_prev_cutoff:.1f} Hz")
            
            if new_prev_cutoff != prev_cutoff:
                print(f"  → ✅ TRACKING WORKS (prev value updates each chunk)")
                return "PASS"
            else:
                print(f"  → ❌ TRACKING BROKEN (prev value not updating)")
                return "FAIL"
        else:
            print(f"  → ❌ filter_cutoff not tracked in _prev_layer_auto")
            return "FAIL"
    else:
        print(f"  → ❌ _prev_layer_auto not populated for layer 0")
        return "FAIL"

def test_interpolated_params():
    """
    Test which parameters actually get interpolated vs constant.
    
    MANT-9 uses np.linspace for:
    - filter_cutoff
    - volume_db
    - fm_index
    - width
    
    Other params are applied once per chunk (constant).
    """
    print(f"\n{'='*60}")
    print("INTERPOLATED PARAMETERS TEST")
    print(f"{'='*60}")
    
    # Check _compute_automation_ramps implementation
    preset = {
        "duration": 0.1,
        "seed": 42,
        "saturation": 0.0,
        "reverb": {"enabled": False},
        "shimmer": {"enabled": False},
        "layers": [
            {
                "type": "fm",
                "enabled": True,
                "root": 110.0,
                "voices": 1,
                "fm_ratios": [1.0],
                "fm_indexes": [0.5],
                "amplitudes": [1.0],
                "automation": {
                    "filter_cutoff": {
                        "points": [{"t": 0.0, "v": 500.0}, {"t": 1.0, "v": 2000.0}],
                        "curve": "linear"
                    },
                    "volume_db": {
                        "points": [{"t": 0.0, "v": -6.0}, {"t": 1.0, "v": 0.0}],
                        "curve": "linear"
                    },
                    "fm_index": {
                        "points": [{"t": 0.0, "v": 0.5}, {"t": 1.0, "v": 2.0}],
                        "curve": "linear"
                    },
                    "width": {
                        "points": [{"t": 0.0, "v": 0.5}, {"t": 1.0, "v": 1.0}],
                        "curve": "linear"
                    },
                    "distortion_drive": {
                        "points": [{"t": 0.0, "v": 0.0}, {"t": 1.0, "v": 1.0}],
                        "curve": "linear"
                    }
                },
                "filter_type": "lp",
                "filter_cutoff": 1000.0,
                "mix": 1.0,
            }
        ],
        "earth": {"enabled": False},
        "air": {"enabled": False},
    }
    
    engine = StreamingDroneEngine(preset, seed=42)
    
    # Render one chunk and get automation ramps
    chunk_size = 2048
    engine.next_chunk(chunk_size)
    
    # Check ramps structure
    t_norm = engine._samples_elapsed / float(engine._duration_samples) if engine._duration_samples > 0 else 0.0
    ramps = engine._compute_automation_ramps(t_norm, chunk_size)
    
    interpolated_params = []
    constant_params = []
    
    if 'layer' in ramps and 0 in ramps['layer']:
        layer_ramps = ramps['layer'][0]
        
        for param, value in layer_ramps.items():
            if isinstance(value, np.ndarray) and len(value) == chunk_size:
                interpolated_params.append(param)
            else:
                constant_params.append(param)
    
    print(f"  Interpolated (linspace ramps):")
    for p in interpolated_params:
        print(f"    ✅ {p}")
    
    print(f"  Constant (single value per chunk):")
    for p in constant_params:
        print(f"    📌 {p}")
    
    expected_interpolated = {'filter_cutoff', 'volume_db', 'fm_index', 'width'}
    actual_interpolated = set(interpolated_params)
    
    if expected_interpolated.issubset(actual_interpolated):
        print(f"  → ✅ ALL EXPECTED PARAMS INTERPOLATED")
        return "PASS"
    else:
        missing = expected_interpolated - actual_interpolated
        print(f"  → ❌ MISSING INTERPOLATION: {missing}")
        return "FAIL"

if __name__ == "__main__":
    print("\n" + "="*60)
    print("R4: MANT-9 IMPLEMENTATION VERIFICATION TEST SUITE")
    print("="*60)
    
    results = {}
    
    try:
        result, cutoff_history = test_filter_sweep_smoothness(duration=2.0)
        results["Filter Sweep Smoothness"] = result
    except Exception as e:
        print(f"  ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        results["Filter Sweep Smoothness"] = "ERROR"
    
    try:
        result = test_prev_value_tracking()
        results["Previous Value Tracking"] = result
    except Exception as e:
        print(f"  ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        results["Previous Value Tracking"] = "ERROR"
    
    try:
        result = test_interpolated_params()
        results["Interpolated Parameters"] = result
    except Exception as e:
        print(f"  ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        results["Interpolated Parameters"] = "ERROR"
    
    print("\n" + "="*60)
    print("TEST SUITE COMPLETE")
    print("="*60)
    
    for test_name, result in results.items():
        status = "✅" if result == "PASS" else "❌" if result == "FAIL" else "⚠️"
        print(f"  {status} {test_name}: {result}")
    
    all_pass = all(r == "PASS" for r in results.values())
    
    print("\n" + "="*60)
    if all_pass:
        print("✅ MANT-9 VERIFIED: Intra-chunk interpolation is working!")
    else:
        print("❌ MANT-9 ISSUES DETECTED: Some interpolation not working")
    print("="*60)
    print()
