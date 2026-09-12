"""Whoop sport-id -> display-name reference data.

Pure lookup data with no behaviour, extracted from the router so that
adding a sport Whoop has newly introduced is a one-line edit to a data
file rather than a change to a module that also owns HTTP routing.
"""

from __future__ import annotations

SPORT_NAMES: dict[int, str] = {
    -1: "Activity",
    0: "Running",
    1: "Cycling",
    16: "Baseball",
    17: "Basketball",
    18: "Rowing",
    19: "Fencing",
    20: "Field Hockey",
    21: "Football",
    22: "Golf",
    24: "Ice Hockey",
    25: "Lacrosse",
    27: "Rugby",
    28: "Sailing",
    29: "Skiing",
    30: "Soccer",
    31: "Softball",
    32: "Squash",
    33: "Swimming",
    34: "Tennis",
    35: "Track & Field",
    36: "Volleyball",
    37: "Water Polo",
    38: "Wrestling",
    39: "Boxing",
    42: "Dance",
    43: "Pilates",
    44: "Yoga",
    45: "Weightlifting",
    47: "Cross Country Skiing",
    48: "Functional Fitness",
    49: "Duathlon",
    51: "Gymnastics",
    52: "Hiking/Rucking",
    53: "Horseback Riding",
    55: "Kayaking",
    56: "Martial Arts",
    57: "Mountain Biking",
    58: "Powerlifting",
    59: "Rock Climbing",
    60: "Paddleboarding",
    61: "Triathlon",
    62: "Walking",
    63: "Surfing",
    64: "Elliptical",
    65: "Stairmaster",
    67: "Meditation",
    68: "Other",
    71: "Duathlon",
    73: "Pickleball",
    74: "Hyrox",
}

FALLBACK_SPORT_NAME = "Activity"


def sport_name(sport_id: int | None) -> str:
    """Display name for a Whoop sport id, falling back to 'Activity'.

    Whoop adds sport ids faster than this table is updated, so an unknown
    id must render as a generic activity rather than blanking the workout.
    """
    return SPORT_NAMES.get(
        sport_id if sport_id is not None else -1, FALLBACK_SPORT_NAME
    )
