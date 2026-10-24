"""Landlord questions based on Boston records for the matched building.

Each question cites one of the allowed sources by name, same as the listing questions.
These never feed any ranking; they only help the student ask about what's on record.
"""

from datetime import date

from app.services.boston import BuildingContext
from app.services.construction import ConstructionContext
from app.services.report_models import LandlordQuestion

# Assessment heat types that usually burn fuel (gas or oil), so carbon monoxide alarms apply.
FUEL_HEAT_PREFIXES = ("W", "F", "S")  # hot water/steam, forced hot air, space heat
SMOKE_RULES_AGE_YEAR = 1975  # MA smoke alarm requirements differ for older buildings
OLD_WIRING_YEAR = 1950
RECENT_ELECTRICAL_YEARS = 20


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _record_phrase(violations: int, complaints: int) -> str:
    parts = []
    if violations:
        parts.append(_plural(violations, "violation"))
    if complaints:
        parts.append(_plural(complaints, "complaint"))
    return " and ".join(parts)


def questions_for_context(ctx: BuildingContext | None, existing: list[LandlordQuestion]) -> list[LandlordQuestion]:
    if ctx is None or ctx.kind != "building" or ctx.history is None:
        return []
    h = ctx.history
    b = h.building
    since = h.first_date[:4] if h.first_date else None
    out: list[LandlordQuestion] = []

    def on_record(category: str, what: str, ask: str) -> None:
        c = h.counts_by_category.get(category)
        if not c or not c.total:
            return
        open_note = f", {c.open} still open," if c.open else ""
        when = f" since {since}" if since else ""
        out.append(
            LandlordQuestion(
                topic={"smoke_alarms": "smoke_alarms", "egress": "two_ways_out", "heating": "heating", "electrical": "electrical"}[category],
                question=(
                    f"Boston records list {_record_phrase(c.violations, c.complaints)} about {what} "
                    f"at this building{when}{open_note}. {ask}"
                ),
                source_id="sanitary_code",
                relation="required_by",
            )
        )

    on_record("smoke_alarms", "smoke or carbon monoxide alarms", "What was fixed, and are all alarms working now?")
    on_record("egress", "exits", "Are all exits and stairways clear and usable now?")
    on_record("heating", "heat", "What was repaired, and does the heat now reach every room?")
    on_record("electrical", "electrical problems", "What was repaired, and by a licensed electrician?")

    if b.year_built and b.year_built < SMOKE_RULES_AGE_YEAR:
        out.append(
            LandlordQuestion(
                topic="smoke_alarms",
                question=(
                    f"This building was built in {b.year_built}. Smoke alarm requirements depend on "
                    "a building's age and renovations. Which requirements apply here, and when were "
                    "the alarms last replaced?"
                ),
                source_id="smoke_alarm_rules",
                relation="based_on",
            )
        )

    if b.year_built and b.year_built < OLD_WIRING_YEAR:
        cutoff = str(date.today().year - RECENT_ELECTRICAL_YEARS)
        recent_electrical = any(p.kind == "electrical" and p.latest >= cutoff for p in h.permits)
        if not recent_electrical:
            out.append(
                LandlordQuestion(
                    topic="electrical",
                    question=(
                        f"Boston's permit records show no electrical permit for this {b.year_built} "
                        f"building in the last {RECENT_ELECTRICAL_YEARS} years. When was the wiring "
                        "last updated or inspected?"
                    ),
                    source_id="sanitary_code",
                    relation="required_by",
                )
            )

    has_co_question = any(q.source_id == "co_alarm_rules" for q in existing)
    if b.heat_type and b.heat_type.startswith(FUEL_HEAT_PREFIXES) and not has_co_question:
        out.append(
            LandlordQuestion(
                topic="smoke_alarms",
                question=(
                    f"City records list the heat as {b.heat_type.split(' - ', 1)[-1].lower()}, which "
                    "usually burns gas or oil. Is there a carbon monoxide alarm on every level?"
                ),
                source_id="co_alarm_rules",
                relation="required_by",
            )
        )
    return out


def construction_questions(cctx: ConstructionContext | None) -> list[LandlordQuestion]:
    """One question when Boston permits show new construction or major work nearby."""
    if cctx is None or cctx.kind != "boston" or not cctx.sites:
        return []
    where = "next door to" if cctx.any_next_door else "near"
    return [
        LandlordQuestion(
            topic="two_ways_out",
            question=(
                f"Boston permits show new construction or major work {where} this building. "
                "How is the site secured, and does the work affect this building's smoke alarms "
                "or exits?"
            ),
            source_id="nfpa_construction",
            relation="based_on",
        )
    ]
