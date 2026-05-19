"""
Convolution reverb engine for MANTICE V11.

Applies impulse response (IR) based reverb to audio using FFT convolution.
Supports multiple IR spaces with configurable wet/dry mix.
"""
import numpy as np
from pathlib import Path
from scipy.signal import fftconvolve
import soundfile as sf

from . import config

_IR_DIR = Path(__file__).parent / "impulse_responses"

# Available spaces (filename stems)
AVAILABLE_SPACES = ["cathedral", "cave", "hall", "plate", "infinite"]

# Cache loaded IRs to avoid re-reading from disk
_ir_cache: dict[str, np.ndarray] = {}


def get_available_spaces() -> list[str]:
    """Return list of available IR space names."""
    return [f.stem for f in _IR_DIR.glob("*.wav")]


def load_ir(space: str) -> np.ndarray:
    """Load an IR file, resampled to current config sample rate if needed."""
    if space in _ir_cache:
        return _ir_cache[space]

    ir_path = _IR_DIR / f"{space}.wav"
    if not ir_path.exists():
        raise FileNotFoundError(f"IR not found: {ir_path}")

    ir_data, ir_sr = sf.read(str(ir_path), dtype="float32")

    # Resample if needed
    if ir_sr != config.SAMPLE_RATE:
        from scipy.signal import resample
        n_target = int(len(ir_data) * config.SAMPLE_RATE / ir_sr)
        if ir_data.ndim == 2:
            ir_data = np.column_stack([
                resample(ir_data[:, 0], n_target),
                resample(ir_data[:, 1], n_target),
            ])
        else:
            ir_data = resample(ir_data, n_target)

    # Ensure stereo
    if ir_data.ndim == 1:
        ir_data = np.column_stack([ir_data, ir_data])

    _ir_cache[space] = ir_data
    return ir_data


def apply_convolution_reverb(
    audio: np.ndarray,
    space: str = "cathedral",
    mix: float = 0.3,
    decay_trim: float = 1.0,
) -> np.ndarray:
    """
    Apply convolution reverb to stereo audio.

    Parameters
    ----------
    audio : np.ndarray
        Input audio, shape (samples, 2) for stereo.
    space : str
        Name of the IR space to use.
    mix : float
        Wet/dry mix (0.0 = fully dry, 1.0 = fully wet).
    decay_trim : float
        Fraction of IR to use (0.0-1.0). Shorter = tighter reverb.

    Returns
    -------
    np.ndarray
        Processed stereo audio, same length as input.
    """
    if mix <= 0.0:
        return audio

    ir = load_ir(space)

    # Trim IR if requested
    if 0.0 < decay_trim < 1.0:
        trim_samples = int(len(ir) * decay_trim)
        ir = ir[:trim_samples]
        # Fade out the trimmed IR
        fade = int(0.1 * trim_samples)
        ir[-fade:] *= np.linspace(1, 0, fade)[:, np.newaxis]

    # Ensure audio is stereo
    if audio.ndim == 1:
        audio = np.column_stack([audio, audio])

    # FFT convolution per channel
    wet_l = fftconvolve(audio[:, 0], ir[:, 0], mode="full")[:len(audio)]
    wet_r = fftconvolve(audio[:, 1], ir[:, 1], mode="full")[:len(audio)]
    wet = np.column_stack([wet_l, wet_r])

    # Normalize wet signal to match dry RMS
    dry_rms = np.sqrt(np.mean(audio ** 2)) + 1e-10
    wet_rms = np.sqrt(np.mean(wet ** 2)) + 1e-10
    wet *= dry_rms / wet_rms

    # Mix
    output = audio * (1.0 - mix) + wet * mix

    return output
