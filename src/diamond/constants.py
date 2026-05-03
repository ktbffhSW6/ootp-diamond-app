"""OOTP integer codebooks discovered via empirical decoding.

Verified against `dump_2029_11` for save "Building the Green Monster".
All codes were proven by exact aggregate matching (events sum to known totals).
See `audit_output/decoder_report.md` for the verification evidence.
"""

from __future__ import annotations

from enum import IntEnum


class GameType(IntEnum):
    """`games.game_type` values."""

    REGULAR_SEASON = 0
    SPRING_TRAINING = 2
    POSTSEASON = 3
    EXHIBITION = 4          # avg innings 8.25, sparse — best guess
    INTERNATIONAL = 5       # spans full save, 5 leagues — likely WBC / int'l friendlies
    SPECIAL_EVENT = 6
    UNKNOWN_8 = 8           # 1 game only — rare


class SplitId(IntEnum):
    """`*_stats.split_id` values for batting/pitching career rollups."""

    OVERALL = 1
    VS_LHP = 2
    VS_RHP = 3
    POSTSEASON = 21


class AtBatResult(IntEnum):
    """`players_at_bat_batting_stats.result` values.

    Verified completeness: sum of all result events = total overall PA in
    regular-season MLB 2029 (183,906 — exact match, zero-residual).
    """

    STRIKEOUT = 1
    WALK = 2
    GROUND_OUT = 4          # mean LA -28°, mean EV 77 mph
    FLY_OUT = 5             # mean LA +43°, mean EV 82 mph (incl. pop-ups)
    SINGLE = 6              # mean LA +9°, mean EV 86 mph
    DOUBLE = 7              # mean LA +22°, mean EV 94 mph
    TRIPLE = 8              # mean LA +25°, mean EV 95 mph
    HOME_RUN = 9            # mean LA +30°, mean EV 100 mph
    HIT_BY_PITCH = 10
    CATCHERS_INTERFERENCE = 11
    # Note: code 3 unobserved in regular-season MLB 2029.
    # May appear in other game types or leagues (e.g. fielders' choice, ROE).


# Convenience groupings
HIT_RESULTS = (AtBatResult.SINGLE, AtBatResult.DOUBLE, AtBatResult.TRIPLE, AtBatResult.HOME_RUN)
EXTRA_BASE_HIT_RESULTS = (AtBatResult.DOUBLE, AtBatResult.TRIPLE, AtBatResult.HOME_RUN)
BIP_RESULTS = (AtBatResult.GROUND_OUT, AtBatResult.FLY_OUT, *HIT_RESULTS)  # ball put in play
NON_AB_PA_RESULTS = (AtBatResult.WALK, AtBatResult.HIT_BY_PITCH, AtBatResult.CATCHERS_INTERFERENCE)
# (sacrifices are tracked via the at-bat `sac` column, layered on GROUND_OUT/FLY_OUT)
