"""Landlord question bank. Each question cites one allowed source by name.

Only cite a law as "required_by" when the source summary in sources.py supports it.
"""

from app.services.report_models import LandlordQuestion

QUESTION_BANK: dict[str, LandlordQuestion] = {
    # --- Smoke and CO alarms ---
    "smoke_every_level": LandlordQuestion(
        topic="smoke_alarms",
        question=(
            "Is there a working smoke alarm on every level and outside every bedroom, "
            "and are any of them more than 10 years old?"
        ),
        source_id="smoke_alarm_rules",
        relation="required_by",
    ),
    "co_every_level": LandlordQuestion(
        topic="smoke_alarms",
        question=(
            "If the building has gas or oil heat, a gas stove, or an attached garage, "
            "is there a carbon monoxide alarm on every level?"
        ),
        source_id="co_alarm_rules",
        relation="required_by",
    ),
    "owner_maintains_alarms": LandlordQuestion(
        topic="smoke_alarms",
        question=(
            "Will you, as the owner, install and maintain working smoke and carbon monoxide "
            "alarms before move-in?"
        ),
        source_id="sanitary_code",
        relation="required_by",
    ),
    # --- Two ways out ---
    "bedroom_two_ways": LandlordQuestion(
        topic="two_ways_out",
        question=(
            "Does every bedroom have two ways out, such as the door and a window that opens "
            "wide enough to climb through?"
        ),
        source_id="dfs_college",
        relation="recommended_by",
    ),
    "unit_second_exit": LandlordQuestion(
        topic="two_ways_out",
        question="Is there a second way out of the unit, such as a rear stairway or fire escape?",
        source_id="sanitary_code",
        relation="required_by",
    ),
    "basement_attic_bedroom": LandlordQuestion(
        topic="two_ways_out",
        question=(
            "Is the basement or attic bedroom a legal bedroom, with a second way out and its "
            "own smoke alarm?"
        ),
        source_id="amherst_fire",
        relation="based_on",
    ),
    "extra_sleeping_room": LandlordQuestion(
        topic="two_ways_out",
        question=(
            "If a den, loft, or other room would be used as a bedroom, does it have a second "
            "way out and a smoke alarm?"
        ),
        source_id="amherst_fire",
        relation="based_on",
    ),
    "exits_clear": LandlordQuestion(
        topic="two_ways_out",
        question="Are hallways, stairways, and porches kept clear so no exit is blocked?",
        source_id="sanitary_code",
        relation="required_by",
    ),
    # --- Sprinklers ---
    "sprinklers": LandlordQuestion(
        topic="sprinklers",
        question="Does the building have automatic fire sprinklers?",
        source_id="umass_off_campus",
        relation="based_on",
    ),
    # --- Heating ---
    "heat_every_room": LandlordQuestion(
        topic="heating",
        question=(
            "Can the heating system keep every room warm from September 15 through May 31 "
            "without space heaters?"
        ),
        source_id="sanitary_code",
        relation="required_by",
    ),
    "space_heaters": LandlordQuestion(
        topic="heating",
        question=(
            "The listing mentions space heaters. Is the main heating system working in every "
            "room, so they aren't needed?"
        ),
        source_id="sanitary_code",
        relation="required_by",
    ),
    # --- Electrical ---
    "enough_outlets": LandlordQuestion(
        topic="electrical",
        question=(
            "Are there enough outlets in each bedroom so you won't need extension cords or "
            "power strips?"
        ),
        source_id="amherst_fire",
        relation="based_on",
    ),
    "wiring_maintained": LandlordQuestion(
        topic="electrical",
        question=(
            "Has the electrical system been inspected or updated recently, and is it "
            "maintained to code?"
        ),
        source_id="sanitary_code",
        relation="required_by",
    ),
}
