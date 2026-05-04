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
    """`players_league_leader.category` — 58 of 60 codes verified by exact
    aggregate match. The remaining 2 codes (44, 49) are pitching rate stats
    in the 8-10 and 47-70 ranges respectively that don't match any standard
    stat we've tried; presumed OOTP-specific or composite — see DATA_NOTES.
    """
    # Batting counting (0-17)
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
    RC                         = 21   # Bill James technical RC, with IBB-correction in B-factor:
                                      #   A = H+BB-CS+HBP-GDP
                                      #   B = TB + 0.26*(BB-IBB+HBP) + 0.52*(SH+SF+SB)
                                      #   C = AB+BB+HBP+SF+SH
                                      #   RC = A*B/C
    RC27                       = 22   # RC * 27 / batting_outs; outs = AB-H+GDP+SH+SF+CS
    ISO                        = 23
    WOBA                       = 24   # OOTP-calibrated weights — close to FG-standard but with
                                      #   per-league wOBA-scale calibration; expect ~3% gap if
                                      #   computed with raw FG weights
    OPS                        = 25
    OPS_PLUS                   = 26   # likely wRC+ or OPS+; both values track within ~1% so
                                      #   indistinguishable without exact formula
    # Pitching counting (27-39)
    PIT_G                      = 27   # all-pitcher G (relievers + starters)
    PIT_GS                     = 28
    W                          = 29
    L                          = 30
    WIN_PCT                    = 31   # W / (W + L)
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
    OPP_BABIP                  = 41   # (HA - HRA) / (Pit_AB - K - HRA + SF)  — verified 8/8 100%
    WHIP                       = 42   # match% low due to IP convention rounding
    K_BB_RATIO                 = 43
    # 44 — UNRESOLVED (pitching rate, values 8-10 across MLB SP leaders); not K/9 (mapped 48),
    #     not HA/9 (46), not HR/9 (45), not WHIP (42). Possibly an OOTP-specific composite.
    HR9                        = 45   # match% low due to IP rounding
    HA9                        = 46   # 9 * HA / IP — verified 8/8 100%
    BB9                        = 47
    K9                         = 48
    # 49 — UNRESOLVED (pitching rate, values 47-70 across MLB SP leaders); not ERA-/FIP-/K%
    #     in obvious form. Possibly a normalized/scaled OOTP stat.
    # Pitching extras (50-59)
    SVO                        = 50
    GF                         = 51   # Games Finished — verified 8/8 100% (closer/setup metric)
    QS                         = 52
    QS_PCT                     = 53   # QS / GS
    CG                         = 54
    CG_PCT                     = 55   # CG / GS
    SHO                        = 56
    GB_PCT                     = 57   # GB / (GB + FB) — verified 8/8 100%
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


# ─────────────────────────────────────────────────────────────────────────────
# Position + level name mappings
#
# Not IntEnums (these display strings rather than carry semantic flags), but
# they belong in this module per CLAUDE.md: codebooks for OOTP integer fields
# live here. Multiple feature modules need them — draft tables, the player
# API route, future scouting / roster UIs — so a single source of truth keeps
# the mapping consistent.
# ─────────────────────────────────────────────────────────────────────────────


# `players.position` codes — primary fielding position. See DATA_NOTES.md.
# 10 = DH (DH-only player; rare for two-way / position players to carry this).
POSITION_NAMES: dict[int, str] = {
    1: "P",   2: "C",   3: "1B",  4: "2B",  5: "3B",
    6: "SS",  7: "LF",  8: "CF",  9: "RF",  10: "DH",
}


# `teams.level` / `players_career_*.level_id` — playing level. Lower = closer
# to MLB. Levels 1-6 are US-affiliated minors (the path the audit uses);
# level 7+ are independent leagues / overseas (KBO, NPB, etc.).
LEVEL_NAMES: dict[int, str] = {
    1: "MLB",  2: "AAA",  3: "AA",  4: "A+",  5: "A",
    6: "Rk",   7: "DSL",  8: "DSL2",
}


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
