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


# ─────────────────────────────────────────────────────────────────────────────
# Codebooks decoded in second pass (decode_codes.py)
# ─────────────────────────────────────────────────────────────────────────────


class AwardId(IntEnum):
    """`players_awards.award_id` — verified by cross-ref with league_history.

    All 13 codes accounted for. Codes 8, 10, 12 unused (gaps in the sequence).
    """
    PLAYER_OF_THE_WEEK         = 0
    PITCHER_OF_THE_MONTH       = 1
    HITTER_OF_THE_MONTH        = 2
    ROOKIE_OF_THE_MONTH        = 3
    CY_YOUNG                   = 4    # top-3 voted (3 winners per league per year)
    MVP                        = 5    # top-3 voted
    ROOKIE_OF_THE_YEAR         = 6    # top-3 voted
    GOLD_GLOVE                 = 7    # one per position (`position` field 1-9 = P-RF)
    ALL_STAR                   = 9    # ASG roster (~30/league/year, d=14 m=7)
    SILVER_SLUGGER             = 11   # one per position (`position` 2-10, 10=DH)
    RELIEVER_OF_THE_YEAR       = 13
    WS_CHAMPION_ROSTER         = 14   # only winning league's sub_league populated
    POSTSEASON_SERIES_MVP      = 15   # WC/DS/CS/WS MVP per series


class LeaderCategory(IntEnum):
    """`players_league_leader.category` — 47 of 60 codes verified by exact
    aggregate match. Codes left out are derived/sabermetric stats we don't
    compute as raw fields (RC, wOBA, FIP, ERA+, SIERA, K%, SV%, etc.).
    """
    # Batting counting (1-17)
    G                          = 0
    PA                         = 1
    AB                         = 2
    H                          = 3
    K                          = 4
    TB                         = 5
    DOUBLES                    = 6
    TRIPLES                    = 7
    HR                         = 8
    SB                         = 9
    RBI                        = 10
    R                          = 11
    BB                         = 12
    IBB                        = 13
    HBP                        = 14
    SH                         = 15
    SF                         = 16
    XBH                        = 17
    # Batting rate (18-26)
    AVG                        = 18
    OBP                        = 19
    SLG                        = 20
    # 21, 22 — sabermetric (likely RC, RC/27 or similar — TBD)
    ISO                        = 23
    # 24 — likely wOBA (sample value 0.3955 close to OBP/wOBA range — TBD)
    OPS                        = 25
    # 26 — likely wRC+ or similar — TBD
    # Pitching counting (27-39)
    PIT_G                      = 27   # all-pitcher G (relievers + starters)
    PIT_GS                     = 28
    W                          = 29
    L                          = 30
    # 31 — likely SV% or similar
    SV                         = 32
    HLD                        = 33
    IP                         = 34   # match% low due to OOTP IP convention rounding
    BF                         = 35
    HRA                        = 36
    PIT_BB                     = 37
    PIT_K                      = 38
    WP                         = 39
    # Pitching rate (40-49)
    ERA                        = 40   # match% low due to IP convention rounding
    # 41 — likely FIP or SIERA
    WHIP                       = 42   # match% low due to IP convention rounding
    K_BB_RATIO                 = 43
    # 44 — likely GO/AO ratio
    HR9                        = 45   # match% low due to IP rounding
    # 46 — likely HR/AB% or HR/9 variant
    BB9                        = 47
    K9                         = 48
    # 49 — likely K% or BB%
    # Pitching extras (50-59)
    SVO                        = 50
    # 51 — likely SVP or PpG
    QS                         = 52
    # 53 — likely QS%
    CG                         = 54
    # 55 — likely CG%
    SHO                        = 56
    # 57 — likely SHO%
    WAR                        = 58
    PIT_WAR                    = 59


# streak_id — 21 codes profiled. Clear batter/pitcher split. Specific names are
# best-guess pending OOTP documentation; mapping order matches max-value rank.
class StreakId(IntEnum):
    """`players_streak.streak_id` — 21 codes. Names are best-guess, derived from
    max-value range + holder type (pitcher vs batter)."""
    # Batter streaks (0-3, 9, 10, 13-15, 17-18)
    HITTING_STREAK             = 0    # max 34 — classic hit streak
    MULTI_HIT_GAME_STREAK      = 1    # max 12, batters
    THREE_PLUS_HIT_GAME_STREAK = 2    # max 8, batters
    HR_GAME_STREAK             = 3    # max 12, batters
    GAMES_PLAYED_STREAK        = 9    # max 41 (highest), batters
    EXTRA_BASE_HIT_STREAK      = 10   # max 9, batters
    RBI_STREAK                 = 13   # max 9, batters
    RUN_STREAK                 = 14   # max 10, batters
    ON_BASE_STREAK             = 15   # max 37, batters
    BATTER_RARE_17             = 17   # max 6
    BATTER_RARE_18             = 18   # max 2
    # Pitcher streaks (4-8, 11, 12, 16, 19, 21)
    SCORELESS_INNINGS_STREAK   = 4    # max 33, pitchers
    WIN_STREAK                 = 5    # max 18, pitchers
    QS_STREAK                  = 6    # max 15, pitchers
    NO_HR_ALLOWED_STREAK       = 7    # max 31, pitchers
    NO_WALK_ALLOWED_STREAK     = 8    # max 26, pitchers
    PITCHER_MIXED_11           = 11   # max 11, mostly pitchers
    SAVES_STREAK               = 12   # max 26, pitchers
    LOSS_STREAK                = 16   # max 11, pitchers
    K_STREAK                   = 19   # max 29, pitchers
    APPEARANCE_STREAK          = 21   # max 39 (highest pitcher), pitchers


class Popularity(IntEnum):
    """`players.local_pop` and `players.national_pop` — 7-bucket popularity scale.
    Verified empirically against IE `popularity_info` strings (220/220 match)."""
    UNKNOWN            = 0
    INSIGNIFICANT      = 1
    FAIR               = 2
    WELL_KNOWN         = 3
    POPULAR            = 4
    VERY_POPULAR       = 5
    EXTREMELY_POPULAR  = 6


POPULARITY_LABELS = {
    0: "Unknown",
    1: "Insignificant",
    2: "Fair",
    3: "Well Known",
    4: "Popular",
    5: "Very Popular",
    6: "Extremely Popular",
}


class ScoutingAccuracy(IntEnum):
    """`players_scouted_ratings.scouting_accuracy` — 1..5 scout-quality scale.
    Verified empirically against IE `popularity_info.SctAcc` strings."""
    V_LOW   = 1
    LOW     = 2
    AVG     = 3
    HIGH    = 4
    V_HIGH  = 5


SCOUTING_ACCURACY_LABELS = {
    1: "V.Low",
    2: "Low",
    3: "Avg",
    4: "High",
    5: "V.High",
}


# Personality / morale bucketing
# ─────────────────────────────────────────────────────────────────────────────
# `players.personality_*` (leader, loyalty, greed, work_ethic, intelligence)
# are 0-200 internal scale. IE shows them as 'Low'/'Normal'/'High'.
# Empirically verified buckets (216/220 match; 4 unknowns are 2029-acquired
# rookies whose personality the org hasn't fully scouted yet — IE shows
# 'Unknown' for those):
#
#   value <  60       -> 'Low'
#   60 <= value < 140 -> 'Normal'
#   value >= 140      -> 'High'

PERSONALITY_LOW_THRESHOLD = 60
PERSONALITY_HIGH_THRESHOLD = 140


def personality_bucket(value: int | None) -> str | None:
    """Return 'Low' / 'Normal' / 'High' for a 0-200 personality value.
    Returns None if value is missing.
    """
    if value is None:
        return None
    if value < PERSONALITY_LOW_THRESHOLD:
        return "Low"
    if value < PERSONALITY_HIGH_THRESHOLD:
        return "Normal"
    return "High"


class BodyPart(IntEnum):
    """`players_injury_history.body_part` — 12 codes profiled. Names derived
    from injury frequency + average length + day-to-day rate. Mappings are
    best-guess pending OOTP documentation."""
    GENERIC_OR_UNKNOWN  = 0    # 7466 inj, avg 3 days, 25% DTD — most common, often serious
    ANKLE_FOOT          = 1    # avg 11 days, 77% DTD
    HEAD_CONCUSSION     = 2    # 88% DTD, avg 17 days
    LEG_HAMSTRING       = 3    # 7853 inj, avg 11 days, 83% DTD
    PERSONAL            = 4    # 251 inj, 92% DTD — likely personal/family time off
    SHOULDER            = 5    # 5585, avg 11 days, 72% DTD
    ARM                 = 6    # 7971, avg 8 days, 86% DTD — most common
    BACK                = 7    # 5285, avg 11 days, 79% DTD
    UCL_TJ              = 8    # 3663, avg 60 days, 52% DTD — severe (Tommy John)
    OBLIQUE_RIB         = 9    # 4172, avg 35 days, 67% DTD
    ELBOW               = 10   # 5176, avg 10 days, 52% DTD
    HAND_THUMB          = 11   # 1267, avg 7 days, 87% DTD
