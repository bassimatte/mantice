"""
engine/preview.py
-----------------
Real-time audio preview with hot-reload and infinite mode.

Features:
  - Streams drone audio to speakers via sounddevice
  - Watches preset YAML file for changes → crossfades to updated preset
  - Infinite mode: runs until Ctrl+C (no fixed duration)
  - Fixed-duration mode: plays for preset duration then stops
"""

import sys
import time
import threading
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

from . import config
from .streaming_engine import StreamingDroneEngine
from .preset_loader import load_preset


class PreviewSession:
    """
    Manages a real-time preview session.

    Usage:
        session = PreviewSession(preset_path, infinite=True)
        session.start()  # blocks until Ctrl+C or duration ends
    """

    def __init__(
        self,
        preset_path: Path,
        infinite: bool = False,
        duration_override: Optional[float] = None,
    ):
        if sd is None:
            raise RuntimeError(
                "sounddevice is required for preview mode.\n"
                "Install it with: pip install sounddevice"
            )

        self.preset_path       = Path(preset_path)
        self.infinite          = infinite
        self.duration_override = duration_override

        self._running   = False
        self._engine: Optional[StreamingDroneEngine] = None
        self._lock      = threading.Lock()
        self._elapsed   = 0.0
        self._duration  = 0.0

        # File watcher state
        self._last_mtime: Optional[float] = None
        self._watcher_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the preview. Blocks until playback completes or Ctrl+C."""
        # Load initial preset
        preset = self._load_current_preset()
        self._duration = preset["duration"]

        if self.duration_override is not None:
            self._duration = self.duration_override

        self._engine = StreamingDroneEngine(preset)
        self._running = True
        self._elapsed = 0.0
        self._last_mtime = self.preset_path.stat().st_mtime

        # Start file watcher
        self._watcher_thread = threading.Thread(target=self._watch_file, daemon=True)
        self._watcher_thread.start()

        # Print info
        mode = "∞ infinite" if self.infinite else f"{self._duration:.0f}s"
        print(f"\n🔊 Preview: {preset['meta'].get('name', self.preset_path.stem)}")
        print(f"   Mode: {mode} | Sample rate: {config.SAMPLE_RATE} Hz")
        print(f"   Hot-reload: watching {self.preset_path.name}")
        print(f"   Press Ctrl+C to stop.\n")

        chunk_size = 2048

        try:
            with sd.OutputStream(
                samplerate=config.SAMPLE_RATE,
                channels=2,
                dtype="float32",
                blocksize=chunk_size,
                callback=self._audio_callback,
            ):
                # Keep main thread alive while streaming
                while self._running:
                    time.sleep(0.1)
                    self._print_status()

                    # Check duration in non-infinite mode
                    if not self.infinite and self._elapsed >= self._duration:
                        self._running = False

        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            sys.stdout.write("\r" + " " * 80 + "\r")
            print("⏹  Preview stopped.")

    def _audio_callback(self, outdata, frames, time_info, status):
        """Called by sounddevice to fill the output buffer."""
        if status:
            pass  # underflow/overflow — ignore silently

        with self._lock:
            if self._engine is None or not self._running:
                outdata[:] = 0
                return

            chunk = self._engine.next_chunk(frames)
            outdata[:] = chunk.astype(np.float32)
            self._elapsed += frames / config.SAMPLE_RATE

    def _print_status(self) -> None:
        """Print a live status line."""
        mins = int(self._elapsed) // 60
        secs = int(self._elapsed) % 60

        if self.infinite:
            status = f"\r  ▶ Playing: {mins:02d}:{secs:02d} (infinite)"
        else:
            remaining = max(0, self._duration - self._elapsed)
            r_mins = int(remaining) // 60
            r_secs = int(remaining) % 60
            pct = min(100, self._elapsed / self._duration * 100)
            status = f"\r  ▶ Playing: {mins:02d}:{secs:02d} / {int(self._duration)//60:02d}:{int(self._duration)%60:02d} ({pct:.0f}%) — {r_mins:02d}:{r_secs:02d} remaining"

        sys.stdout.write(status)
        sys.stdout.flush()

    def _watch_file(self) -> None:
        """Background thread: watch preset file for modifications."""
        while self._running:
            time.sleep(0.5)
            try:
                current_mtime = self.preset_path.stat().st_mtime
                if self._last_mtime is not None and current_mtime > self._last_mtime:
                    self._last_mtime = current_mtime
                    self._hot_reload()
            except (OSError, IOError):
                pass

    def _hot_reload(self) -> None:
        """Reload the preset and crossfade the engine."""
        try:
            new_preset = self._load_current_preset()

            if self.duration_override is not None:
                new_preset["duration"] = self.duration_override

            with self._lock:
                self._engine.reload(new_preset, crossfade_secs=3.0)

            name = new_preset["meta"].get("name", self.preset_path.stem)
            sys.stdout.write(f"\r  🔄 Hot-reload: {name} (crossfading 3s){'':30}\n")
            sys.stdout.flush()

        except Exception as exc:
            sys.stdout.write(f"\r  ⚠  Reload failed: {exc}{'':30}\n")
            sys.stdout.flush()

    def _load_current_preset(self) -> dict:
        """Load and validate the current preset file."""
        import warnings
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            return load_preset(self.preset_path)
