"""
engine/fm_voice.py
------------------
Single FM voice with:
  - per-voice random drift RATE (previously hardcoded to 0.003 Hz for all voices)
  - random phase offset so voices start at different points in their cycle
  - raised-cosine per-voice envelope (smooth attack + release)
"""

import random

import numpy as np

from . import config


class GentleFMVoice:

    def __init__(
        self,
        carrier_freq: float,
        mod_ratio:    float,
        fm_index:     float,
        amplitude:    float,
        duration:     float,
        drift:        float = 0.002,
        drift_rate:   float = None,    # Hz; randomised per-voice if None
        attack_secs:  float = 3.0,
        release_secs: float = 4.0,
    ):
        self.carrier_freq = carrier_freq
        self.mod_ratio    = mod_ratio
        self.fm_index     = fm_index
        self.amplitude    = amplitude
        self.duration     = duration
        self.drift        = drift
        # Each voice gets its own slow drift cycle — avoids all voices
        # modulating in sync (which flattens into a sterile wobble).
        self.drift_rate   = drift_rate if drift_rate is not None \
                            else random.uniform(0.001, 0.006)
        self.attack_secs  = attack_secs
        self.release_secs = release_secs

    def generate(self) -> np.ndarray:
        samples = int(self.duration * config.SAMPLE_RATE)
        t       = np.linspace(0, self.duration, samples, endpoint=False)

        mod_freq  = self.carrier_freq * self.mod_ratio
        modulator = np.sin(2 * np.pi * mod_freq * t)

        # Pitch drift — unique rate per voice
        drift_signal = np.sin(2 * np.pi * self.drift_rate * t) * self.drift

        phase = random.uniform(0, 2 * np.pi)
        signal = np.sin(
            2 * np.pi * self.carrier_freq * (1.0 + drift_signal) * t
            + modulator * self.fm_index
            + phase
        )

        # Raised-cosine per-voice envelope (smoother than linear ramp)
        env          = np.ones(samples)
        attack_n     = min(int(self.attack_secs  * config.SAMPLE_RATE), samples // 3)
        release_n    = min(int(self.release_secs * config.SAMPLE_RATE), samples // 3)

        env[:attack_n]    = 0.5 * (1 - np.cos(np.pi * np.arange(attack_n)  / attack_n))
        env[-release_n:]  = 0.5 * (1 + np.cos(np.pi * np.arange(release_n) / release_n))

        return signal * self.amplitude * env
