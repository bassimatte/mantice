"""
Just Intonation tuning library for MANTICE.

Intervals stored as exact rational fractions (num, den).
Frequency at synthesis: tonic_hz * num / den  (exact, no floating-point rounding).
"""
import math

# ── JI scale systems ──────────────────────────────────────────────────────────

JI_SYSTEMS: dict[str, dict[str, tuple[int, int]]] = {

    "5limit_ji": {
        # Pure intervals from primes 2, 3, 5
        "unison":    (1, 1),
        "minor_2nd": (16, 15),
        "major_2nd": (9, 8),
        "minor_3rd": (6, 5),
        "major_3rd": (5, 4),
        "fourth":    (4, 3),
        "tritone":   (45, 32),
        "fifth":     (3, 2),
        "minor_6th": (8, 5),
        "major_6th": (5, 3),
        "minor_7th": (16, 9),
        "major_7th": (15, 8),
        "octave":    (2, 1),
    },

    "pythagorean": {
        # All intervals stacked from pure fifths (3:2), no 5-prime
        "unison":    (1, 1),
        "minor_2nd": (256, 243),
        "major_2nd": (9, 8),
        "minor_3rd": (32, 27),
        "major_3rd": (81, 64),
        "fourth":    (4, 3),
        "tritone":   (729, 512),
        "fifth":     (3, 2),
        "minor_6th": (128, 81),
        "major_6th": (27, 16),
        "minor_7th": (16, 9),
        "major_7th": (243, 128),
        "octave":    (2, 1),
    },

    "7limit": {
        # Septimal ratios add expressive dissonances (7-prime)
        "unison":       (1, 1),
        "minor_2nd":    (16, 15),
        "major_2nd":    (9, 8),
        "sep_min_3rd":  (7, 6),
        "major_3rd":    (5, 4),
        "fourth":       (4, 3),
        "sep_tritone":  (7, 5),
        "fifth":        (3, 2),
        "minor_6th":    (8, 5),
        "major_6th":    (5, 3),
        "harmonic_7th": (7, 4),
        "major_7th":    (15, 8),
        "octave":       (2, 1),
    },

    "harmonic_series": {
        # First 16 overtone partials reduced to within one octave
        "h1":  (1, 1),    # fundamental
        "h9":  (9, 8),    # major 2nd
        "h5":  (5, 4),    # major 3rd
        "h11": (11, 8),   # neutral fourth (slightly sharp)
        "h3":  (3, 2),    # fifth
        "h13": (13, 8),   # natural sixth
        "h7":  (7, 4),    # natural seventh (flat minor 7th)
        "h15": (15, 8),   # major seventh
        "h2":  (2, 1),    # octave
    },
}

# Human-readable labels for the UI
DEGREE_LABELS: dict[str, str] = {
    "unison":       "Unison  1:1",
    "minor_2nd":    "Min 2nd  16:15",
    "major_2nd":    "Maj 2nd  9:8",
    "minor_3rd":    "Min 3rd  6:5",
    "major_3rd":    "Maj 3rd  5:4",
    "fourth":       "Fourth  4:3",
    "tritone":      "Tritone  45:32",
    "fifth":        "Fifth  3:2",
    "minor_6th":    "Min 6th  8:5",
    "major_6th":    "Maj 6th  5:3",
    "minor_7th":    "Min 7th  16:9",
    "major_7th":    "Maj 7th  15:8",
    "octave":       "Octave  2:1",
    "sep_min_3rd":  "Sep Min 3rd  7:6",
    "sep_tritone":  "Sep Tritone  7:5",
    "harmonic_7th": "Harm 7th  7:4",
    "h1":  "H1 – Fund.  1:1",
    "h9":  "H9 – Maj 2nd  9:8",
    "h5":  "H5 – Maj 3rd  5:4",
    "h11": "H11 – Neut 4th  11:8",
    "h3":  "H3 – Fifth  3:2",
    "h13": "H13 – Nat 6th  13:8",
    "h7":  "H7 – Nat 7th  7:4",
    "h15": "H15 – Maj 7th  15:8",
    "h2":  "H2 – Octave  2:1",
}

SYSTEM_LABELS: dict[str, str] = {
    "5limit_ji":       "5-limit JI",
    "pythagorean":     "Pythagorean",
    "7limit":          "7-limit",
    "harmonic_series": "Harmonic Series",
}


def get_ji_hz(tonic_hz: float, system: str, degree: str) -> float:
    """
    Return exact frequency for *degree* above *tonic_hz* in *system*.

    The result is octave-shifted to stay in [tonic/2, tonic*4] so layers
    remain musically close to the tonic rather than many octaves away.
    """
    degrees = JI_SYSTEMS.get(system) or JI_SYSTEMS["5limit_ji"]
    num, den = degrees.get(degree, (1, 1))
    hz = tonic_hz * num / den
    # Fold into [tonic_hz/2 … tonic_hz*4] (two octaves)
    while hz < tonic_hz / 2:
        hz *= 2.0
    while hz > tonic_hz * 4:
        hz /= 2.0
    return round(hz, 4)


def nearest_degree(
    hz: float,
    tonic_hz: float,
    system: str,
    max_octaves: int = 3,
) -> tuple[str, float, float]:
    """
    Find the JI degree whose frequency is closest to *hz*.

    Returns (degree_name, ji_hz, cents_error).
    Searches across *max_octaves* octave shifts of the tonic.
    """
    degrees = JI_SYSTEMS.get(system) or JI_SYSTEMS["5limit_ji"]
    best_degree = "unison"
    best_hz = tonic_hz
    best_cents = float("inf")

    for degree, (num, den) in degrees.items():
        for oct_shift in range(-max_octaves, max_octaves + 1):
            candidate = tonic_hz * (num / den) * (2 ** oct_shift)
            if candidate <= 0:
                continue
            cents = abs(1200 * math.log2(hz / candidate))
            if cents < best_cents:
                best_cents = cents
                best_degree = degree
                best_hz = candidate

    return best_degree, round(best_hz, 4), round(best_cents, 1)


def get_system_degrees(system: str) -> list[tuple[str, tuple[int, int]]]:
    """Return (degree_name, (num, den)) pairs sorted by ratio value."""
    degrees = JI_SYSTEMS.get(system) or JI_SYSTEMS["5limit_ji"]
    return sorted(degrees.items(), key=lambda x: x[1][0] / x[1][1])
