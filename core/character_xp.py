"""Cumulative XP for character and specialization levels."""

_XP_MULTIPLIER = 60.0
_SPECIALIZATION_XP_MULTIPLIER = 80.0
_XP_POWER = 2.8
_XP_OFFSET = 7.33

# Hardcoded cumulative XP for levels 1-10 (formula doesn't fit these)
_XP_TABLE_1_10 = {
    1: 0,
    2: 857,
    3: 1740,
    4: 3349,
    5: 5875,
    6: 9496,
    7: 14385,
    8: 20707,
    9: 28625,
    10: 38297,
}


def calc_xp_for_level(level: int) -> int:
    """Return the minimum cumulative XP required to reach *level*."""
    if level < 1:
        return 0
    if level <= 10:
        return _XP_TABLE_1_10.get(level, 0)
    return int(_XP_MULTIPLIER * (level ** _XP_POWER + _XP_OFFSET))


def calc_xp_for_specialization_level(level: int) -> int:
    """Return cumulative specialization XP required for *level*.

    NCS uses the same power/offset curve as character progression, but the
    specialization curve is scaled by 80 rather than 60.  The 701 cap value
    exported by the game (7,431,910,510) is an exact match for this formula;
    keeping this separate from ``calc_xp_for_level`` prevents silently writing
    character XP values into the specialization record.
    """
    if level < 1:
        return 0
    return int(_SPECIALIZATION_XP_MULTIPLIER * (level ** _XP_POWER + _XP_OFFSET))
