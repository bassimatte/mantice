"""Generate synthetic impulse responses for convolution reverb."""
import numpy as np
import soundfile as sf
from pathlib import Path
from scipy.signal import butter, filtfilt

IR_DIR = Path("engine/impulse_responses")
IR_DIR.mkdir(parents=True, exist_ok=True)
SR = 44100


def generate_ir(duration, decay_time, pre_delay_ms=0, density=1.0,
                damping=0.5, diffusion=0.8, modulation=0.0, seed=42):
    """Generate a synthetic impulse response."""
    np.random.seed(seed)
    n_samples = int(duration * SR)
    ir = np.zeros(n_samples)

    # Pre-delay
    pre_samples = int(pre_delay_ms * SR / 1000)

    # Early reflections (sparse)
    n_early = int(20 * density)
    for i in range(n_early):
        pos = pre_samples + int(np.random.exponential(0.02 * SR))
        if pos < n_samples:
            amp = np.random.uniform(0.3, 0.8) * (0.9 ** i)
            ir[pos] += amp * (1 if np.random.random() > 0.5 else -1)

    # Diffuse tail (filtered noise with exponential decay)
    noise = np.random.randn(n_samples) * diffusion

    # Frequency-dependent decay
    t = np.arange(n_samples) / SR
    env_low = np.exp(-3.0 * t / decay_time)
    env_high = np.exp(-6.0 * t / (decay_time * (1 - damping * 0.7)))

    # Crossover at ~1kHz
    b_lo, a_lo = butter(2, 1000 / (SR / 2), btype="low")
    b_hi, a_hi = butter(2, 1000 / (SR / 2), btype="high")

    noise_lo = filtfilt(b_lo, a_lo, noise) * env_low
    noise_hi = filtfilt(b_hi, a_hi, noise) * env_high

    tail = noise_lo + noise_hi

    # Apply pre-delay to tail
    if pre_samples > 0:
        tail[:pre_samples] = 0

    ir += tail

    # Optional modulation (chorus-like smearing)
    if modulation > 0:
        mod_freq = 0.5 + np.random.random() * 1.5
        mod = np.sin(2 * np.pi * mod_freq * t) * modulation * 0.001 * SR
        indices = np.clip((np.arange(n_samples) + mod).astype(int), 0, n_samples - 1)
        ir = ir[indices]

    # Normalize
    ir = ir / (np.max(np.abs(ir)) + 1e-10) * 0.9

    # Fade out last 5%
    fade_len = int(0.05 * n_samples)
    ir[-fade_len:] *= np.linspace(1, 0, fade_len)

    return ir


# Define space types
SPACES = {
    "cathedral": {
        "duration": 6.0, "decay_time": 5.0, "pre_delay_ms": 30,
        "density": 1.2, "damping": 0.3, "diffusion": 0.9, "modulation": 0.2,
    },
    "cave": {
        "duration": 8.0, "decay_time": 7.0, "pre_delay_ms": 50,
        "density": 0.6, "damping": 0.2, "diffusion": 0.7, "modulation": 0.1,
    },
    "hall": {
        "duration": 4.0, "decay_time": 3.5, "pre_delay_ms": 20,
        "density": 1.5, "damping": 0.4, "diffusion": 0.85, "modulation": 0.15,
    },
    "plate": {
        "duration": 3.0, "decay_time": 2.5, "pre_delay_ms": 5,
        "density": 2.0, "damping": 0.6, "diffusion": 0.95, "modulation": 0.3,
    },
    "infinite": {
        "duration": 12.0, "decay_time": 11.0, "pre_delay_ms": 80,
        "density": 0.8, "damping": 0.15, "diffusion": 0.6, "modulation": 0.05,
    },
}

if __name__ == "__main__":
    for name, params in SPACES.items():
        # Left channel
        ir_l = generate_ir(**params, seed=42)
        # Right channel (slightly different seed for stereo decorrelation)
        ir_r = generate_ir(**params, seed=43)
        stereo = np.column_stack([ir_l, ir_r])

        out_path = IR_DIR / f"{name}.wav"
        sf.write(str(out_path), stereo, SR, subtype="FLOAT")
        dur = params["duration"]
        decay = params["decay_time"]
        print(f"  {name}.wav  ({dur}s, decay={decay}s)")

    print(f"\nDone — 5 IRs saved to {IR_DIR}/")
