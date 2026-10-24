"""Cheap check that text looks like a rental listing or lease before analyzing it.

Runs before the Claude call, so off-topic text (a recipe, an essay, a question for a chatbot)
never costs an API call. Claude does a second check for anything that slips through.
"""

import re

NOT_A_LISTING_MESSAGE = (
    "This doesn't look like a rental listing or lease. TwoWaysOut only checks rental "
    "listings and leases for fire safety. Paste the listing text or upload the lease."
)

# Distinct housing terms; a listing or lease almost always uses several.
HOUSING_TERMS = re.compile(
    r"\b(?:"
    r"\d\s*(?:br|bd|bed|bedrooms?|ba|bath)s?"
    r"|bedrooms?|bathrooms?|baths?|kitchen|living\s+room|apartment|apt|condo|duplex|triple[\s-]decker"
    r"|studio|unit|units|floor|basement|attic|porch|house|home|dwelling|premises|property"
    r"|rent|rental|lease|leases|leasing|tenants?|landlord|lessor|lessee|sublet"
    r"|security\s+deposit|deposit|utilities|heat|hot\s+water|laundry|parking"
    r"|move[\s-]in|available|per\s+month|/\s*mo(?:nth)?|sq\.?\s*ft|square\s+feet"
    # Fire-safety terms that show up in listings, leases, and housing complaints.
    r"|smoke\s+(?:detectors?|alarms?)|carbon\s+monoxide|sprinklers?|sprinklered|fire\s+escapes?"
    r"|egress|space\s+heaters?|extension\s+cords?|boiler|furnace|radiators?"
    r")\b",
    re.IGNORECASE,
)
MIN_DISTINCT_TERMS = 2


def looks_like_rental_text(text: str) -> bool:
    found = {re.sub(r"\s+", " ", m.group().lower()) for m in HOUSING_TERMS.finditer(text or "")}
    # Count "2br" and "3br" as one term.
    found = {re.sub(r"^\d\s*", "#", t) for t in found}
    return len(found) >= MIN_DISTINCT_TERMS
