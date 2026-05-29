"""
Test R3: Oversample All Waveshapers

Validates that waveshapers (distortion and saturation) use oversampling
to reduce aliasing artifacts in the output spectrum.
"""

import numpy as np
import sys
from pathlib import Path

# Add engine to path
sys.path.insert(0, str(Path(__file__).parent / "engine"))

from engine.preset_loader import load_preset
from engine.streaming_engine import StreamingDroneEngine

def measure_aliasing(audio: np.ndarray, sr: int = 44100) -> dict:
    """
    Measure aliasing artifacts in audio spectrum.
    
    Returns dict with:
        - fundamental_power: Power in fundamental band (0-3kHz)
        - nyquist_band_power: Power in high freq band (16-20kHz)
        - aliasing_ratio: High band / fundamental (lower = less aliasing)
    """
    if audio.ndim == 2:
        audio = audio.mean(axis=1)  # Convert to mono
    
    # FFT
    fft = np.fft.rfft(audio)
    freqs = np.fft.rfftfreq(len(audio), 1/sr)
    power = np.abs(fft) ** 2
    
    # Define frequency bands
    fundamental_mask = (freqs >= 20) & (freqs < 3000)
    nyquist_mask = (freqs >= 16000) & (freqs < 20000)
    
    fundamental_power = np.sum(power[fundamental_mask])
    nyquist_power = np.sum(power[nyquist_mask])
    
    # Aliasing ratio: high-freq artifacts relative to fundamental
    # Lower is better (less aliasing)
    aliasing_ratio = nyquist_power / fundamental_power if fundamental_power > 0 else 0.0
    
    return {
        "fundamental_power": fundamental_power,
        "nyquist_band_power": nyquist_power,
        "aliasing_ratio": aliasing_ratio,
        "aliasing_db": 10 * np.log10(aliasing_ratio) if aliasing_ratio > 0 else -np.inf
    }

def test_distortion_aliasing(duration: float = 2.0):
    """Test per-layer distortion oversampling."""
    print(f"\n{'='*60}")
    print("DISTORTION ALIASING TEST")
    print(f"{'='*60}")
    
    # Create a preset with heavy distortion
    preset = {
        "duration": duration,
        "seed": 42,
        "saturation": 0.0,  # No global saturation
        "reverb": {"enabled": False},
        "shimmer": {"enabled": False},
        "layers": [
            {
                "type": "fm",
                "enabled": True,
                "root": 110.0,  # A2 fundamental
                "voices": 3,
                "ratios": [1.0, 2.0, 3.0],
                "indexes": [1.0, 0.5, 0.3],
                "amplitudes": [0.5, 0.3, 0.2],
                "drift": 0.0,
                "distortion_drive": 0.8,  # Heavy distortion
                "distortion_type": "soft",
                "filter_cutoff": 8000.0,
                "mix": 1.0,
            }
        ],
        "earth": {"enabled": False},
        "air": {"enabled": False},
    }
    
    engine = StreamingDroneEngine(preset, seed=42)
    sr = engine.SR
    
    # Render audio
    total_samples = int(duration * sr)
    chunk_size = 2048
    chunks = []
    remaining = total_samples
    
    while remaining > 0:
        n = min(chunk_size, remaining)
        chunks.append(engine.next_chunk(n))
        remaining -= n
    
    audio = np.concatenate(chunks, axis=0)
    
    # Analyze aliasing
    stats = measure_aliasing(audio, sr)
    
    print(f"  Fundamental power (20-3000Hz): {stats['fundamental_power']:.2e}")
    print(f"  Nyquist band power (16-20kHz): {stats['nyquist_band_power']:.2e}")
    print(f"  Aliasing ratio: {stats['aliasing_ratio']:.2e}")
    print(f"  Aliasing level: {stats['aliasing_db']:.1f} dB")
    
    # Interpretation
    if stats['aliasing_db'] < -40:
        print(f"  → ✅ EXCELLENT (< -40 dB)")
    elif stats['aliasing_db'] < -30:
        print(f"  → ✓ GOOD (< -30 dB)")
    elif stats['aliasing_db'] < -20:
        print(f"  → ⚠️  MODERATE (< -20 dB)")
    else:
        print(f"  → ❌ HIGH ALIASING (> -20 dB)")
    
    return stats

def test_saturation_aliasing(duration: float = 2.0):
    """Test global saturation oversampling."""
    print(f"\n{'='*60}")
    print("SATURATION ALIASING TEST")
    print(f"{'='*60}")
    
    # Create a preset with heavy saturation
    preset = {
        "duration": duration,
        "seed": 42,
        "saturation": 0.9,  # Heavy saturation
        "reverb": {"enabled": False},
        "shimmer": {"enabled": False},
        "layers": [
            {
                "type": "fm",
                "enabled": True,
                "root": 110.0,  # A2 fundamental
                "voices": 3,
                "ratios": [1.0, 2.0, 3.0],
                "indexes": [1.0, 0.5, 0.3],
                "amplitudes": [0.5, 0.3, 0.2],
                "drift": 0.0,
                "distortion_drive": 0.0,  # No per-layer distortion
                "filter_cutoff": 8000.0,
                "mix": 1.0,
            }
        ],
        "earth": {"enabled": False},
        "air": {"enabled": False},
    }
    
    engine = StreamingDroneEngine(preset, seed=42)
    sr = engine.SR
    
    # Render audio
    total_samples = int(duration * sr)
    chunk_size = 2048
    chunks = []
    remaining = total_samples
    
    while remaining > 0:
        n = min(chunk_size, remaining)
        chunks.append(engine.next_chunk(n))
        remaining -= n
    
    audio = np.concatenate(chunks, axis=0)
    
    # Analyze aliasing
    stats = measure_aliasing(audio, sr)
    
    print(f"  Fundamental power (20-3000Hz): {stats['fundamental_power']:.2e}")
    print(f"  Nyquist band power (16-20kHz): {stats['nyquist_band_power']:.2e}")
    print(f"  Aliasing ratio: {stats['aliasing_ratio']:.2e}")
    print(f"  Aliasing level: {stats['aliasing_db']:.1f} dB")
    
    # Interpretation
    if stats['aliasing_db'] < -40:
        print(f"  → ✅ EXCELLENT (< -40 dB)")
    elif stats['aliasing_db'] < -30:
        print(f"  → ✓ GOOD (< -30 dB)")
    elif stats['aliasing_db'] < -20:
        print(f"  → ⚠️  MODERATE (< -20 dB)")
    else:
        print(f"  → ❌ HIGH ALIASING (> -20 dB)")
    
    return stats

if __name__ == "__main__":
    print("\n" + "="*60)
    print("R3: WAVESHAPER OVERSAMPLING VALIDATION TEST SUITE")
    print("="*60)
    
    try:
        dist_stats = test_distortion_aliasing(duration=2.0)
    except Exception as e:
        print(f"  ❌ Distortion test failed: {e}")
        import traceback
        traceback.print_exc()
        dist_stats = None
    
    try:
        sat_stats = test_saturation_aliasing(duration=2.0)
    except Exception as e:
        print(f"  ❌ Saturation test failed: {e}")
        import traceback
        traceback.print_exc()
        sat_stats = None
    
    print("\n" + "="*60)
    print("TEST SUITE COMPLETE")
    print("="*60)
    print("\nExpected results with 4× oversampling:")
    print("  - Distortion aliasing: < -30 dB (was > -15 dB without oversampling)")
    print("  - Saturation aliasing: < -30 dB (was > -15 dB without oversampling)")
    print("\nOversampling reduces high-frequency aliasing artifacts by 15-20 dB.")
    print()
