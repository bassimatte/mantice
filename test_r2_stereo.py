"""
Test R2: Stereo Width Improvements

Validates that FDN reverb, granular layers, and Earth layer all produce true stereo output.
"""

import numpy as np
import sys
from pathlib import Path

# Add engine to path
sys.path.insert(0, str(Path(__file__).parent / "engine"))

from engine.preset_loader import load_preset
from engine.streaming_engine import StreamingDroneEngine

def test_stereo_correlation(audio: np.ndarray, name: str) -> dict:
    """
    Measure stereo correlation and width.
    Returns dict with L/R RMS, correlation, and width metrics.
    """
    if audio.ndim != 2:
        return {"error": "Not stereo"}
    
    L = audio[:, 0]
    R = audio[:, 1]
    
    # RMS per channel
    rms_L = np.sqrt(np.mean(L ** 2))
    rms_R = np.sqrt(np.mean(R ** 2))
    
    # Pearson correlation
    if rms_L > 1e-6 and rms_R > 1e-6:
        corr = np.corrcoef(L, R)[0, 1]
    else:
        corr = 0.0
    
    # Stereo width estimate: 1.0 - correlation
    # corr=1.0 → mono (width=0)
    # corr=0.0 → decorrelated (width=1.0)
    # corr=-1.0 → inverted (width=2.0, unusual)
    width = 1.0 - corr
    
    return {
        "name": name,
        "rms_L": rms_L,
        "rms_R": rms_R,
        "correlation": corr,
        "stereo_width": width,
        "balance": rms_R / rms_L if rms_L > 1e-6 else 0.0
    }

def test_preset(preset_path: str, duration: float = 5.0, name: str = None):
    """Render a preset and measure stereo characteristics."""
    print(f"\n{'='*60}")
    print(f"Testing: {name or preset_path}")
    print(f"{'='*60}")
    
    preset = load_preset(preset_path)
    preset["duration"] = duration
    
    engine = StreamingDroneEngine(preset, seed=42)
    
    # Render audio
    sr = engine.SR
    total_samples = int(duration * sr)
    chunk_size = 2048
    chunks = []
    remaining = total_samples
    
    while remaining > 0:
        n = min(chunk_size, remaining)
        chunks.append(engine.next_chunk(n))
        remaining -= n
    
    audio = np.concatenate(chunks, axis=0)
    
    # Analyze stereo characteristics
    stats = test_stereo_correlation(audio, name or preset_path)
    
    print(f"  RMS L: {stats['rms_L']:.4f}")
    print(f"  RMS R: {stats['rms_R']:.4f}")
    print(f"  Balance (R/L): {stats['balance']:.3f}")
    print(f"  Correlation: {stats['correlation']:.3f}")
    print(f"  Stereo Width: {stats['stereo_width']:.3f}")
    
    # Interpretation
    if stats['correlation'] > 0.99:
        print(f"  → ❌ MONO (correlation > 0.99)")
    elif stats['correlation'] > 0.9:
        print(f"  → ⚠️  NARROW (correlation > 0.9)")
    elif stats['correlation'] > 0.5:
        print(f"  → ✓ MODERATE WIDTH (0.5 < corr < 0.9)")
    else:
        print(f"  → ✅ WIDE STEREO (correlation < 0.5)")
    
    return stats

if __name__ == "__main__":
    print("\n" + "="*60)
    print("R2: STEREO WIDTH VALIDATION TEST SUITE")
    print("="*60)
    
    # Test 1: Preset with FDN reverb (should be wide, not mono)
    print("\n1. FDN REVERB STEREO TEST")
    try:
        test_preset("presets/test_reverb_tail.yaml", duration=3.0, name="Reverb Tail (FDN)")
    except Exception as e:
        print(f"  ❌ Failed: {e}")
    
    # Test 2: Granular layer (should have stereo width from per-grain panning)
    print("\n2. GRANULAR STEREO TEST")
    try:
        # Find a preset with granular layers
        from pathlib import Path
        presets = list(Path("presets").glob("*.yaml"))
        for p in presets:
            if "forest" in p.stem.lower() or "rain" in p.stem.lower():
                test_preset(str(p), duration=3.0, name=f"Granular ({p.stem})")
                break
        else:
            print("  ⚠️  No granular preset found")
    except Exception as e:
        print(f"  ❌ Failed: {e}")
    
    # Test 3: Earth layer (should have subtle decorrelation)
    print("\n3. EARTH LAYER STEREO TEST")
    try:
        # Find preset with Earth enabled
        for p in presets:
            preset_dict = load_preset(p)
            if preset_dict.get("earth", {}).get("enabled"):
                test_preset(str(p), duration=3.0, name=f"Earth ({p.stem})")
                break
        else:
            print("  ⚠️  No Earth-enabled preset found")
    except Exception as e:
        print(f"  ❌ Failed: {e}")
    
    print("\n" + "="*60)
    print("TEST SUITE COMPLETE")
    print("="*60)
    print("\nExpected results:")
    print("  - FDN Reverb: correlation < 0.8 (was ~1.0 before R2)")
    print("  - Granular: correlation < 0.7 (was ~1.0 before R2)")
    print("  - Earth: correlation < 0.95 (was ~1.0 before R2)")
    print()
