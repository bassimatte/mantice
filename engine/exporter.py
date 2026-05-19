"""
engine/exporter.py
------------------
Audio export in multiple formats.

Supported: wav (PCM-24), flac (lossless), ogg (Vorbis), mp3 (via ffmpeg).
"""

import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from . import config

SUPPORTED_FORMATS = ["wav", "flac", "ogg", "mp3"]


def export_audio(path: Path, audio: np.ndarray, fmt: str = "wav") -> None:
    """
    Export stereo audio array to the given path in the specified format.

    For wav/flac/ogg: uses soundfile directly.
    For mp3: writes a temporary WAV then converts via ffmpeg.
    """
    path = Path(path)
    fmt  = fmt.lower()

    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format '{fmt}'. Choose from: {', '.join(SUPPORTED_FORMATS)}"
        )

    sr = config.SAMPLE_RATE
    bd = config.BIT_DEPTH

    _sf_subtypes = {
        "wav":  bd,
        "flac": bd,
        "ogg":  "VORBIS",
    }

    if fmt in ("wav", "flac", "ogg"):
        sf_format = fmt.upper()
        subtype   = _sf_subtypes[fmt]
        sf.write(str(path), audio, sr, format=sf_format, subtype=subtype)

    elif fmt == "mp3":
        # Write temp WAV, convert to MP3 via ffmpeg
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            sf.write(tmp_path, audio, sr, subtype=bd)
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", tmp_path,
                    "-codec:a", "libmp3lame",
                    "-b:a", "320k",
                    str(path),
                ],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg MP3 conversion failed: {result.stderr.strip()}\n"
                    "Make sure ffmpeg is installed and in your PATH."
                )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
