"""Assistant orchestration: extract an intent, then execute it if we can.

THE REGISTRY is the point of this file. It maps each intent to a handler, or to
None meaning "recognized, not implemented yet".

  - None            -> "I understood, but that isn't available yet."
  - Intent.UNKNOWN  -> "I didn't understand."

Those are DIFFERENT replies and the distinction matters: one tells the user the
feature is coming, the other tells them to rephrase.

When the GPS route becomes real, you replace one None with a function. The
extractor never changes -- which is exactly why no MQTT topic appears in the
intent layer.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.Exeptions import CarRejected, CarTimeout, NoVehicleForUser
from app.intents.extractor import extract
from app.intents.schema import Intent, IntentResult
from app.services import CarService

# Confidence below this, for an intent that PHYSICALLY ACTUATES something, gets
# a confirmation question instead of being executed. Reading data is safe;
# starting a compressor on a shaky guess is not.
CONFIRM_THRESHOLD = 0.85

# Intents that change the physical state of the car (vs. just reading it).
ACTUATING = {Intent.AC_SET, Intent.DOORS_LOCK}


# --- handlers ----------------------------------------------------------------
# Each takes (session, user_id, slots) and returns a reply string.

async def _handle_temperature(session: AsyncSession, user_id: str,
                              slots: dict) -> str:
    vin, value = await CarService.read_temperature(session, user_id)
    return f"The cabin temperature is {value} degrees."


async def _handle_ac(session: AsyncSession, user_id: str, slots: dict) -> str:
    state = slots.get("state")
    if state not in ("on", "off"):
        return "Did you want the air conditioning on or off?"
    vin, result_state = await CarService.set_ac(session, user_id, state)
    return f"Air conditioning is now {result_state}."


# --- the registry ------------------------------------------------------------

Handler = Callable[[AsyncSession, str, dict], Awaitable[str]]

HANDLERS: dict[Intent, Handler | None] = {
    # wired to the car
    Intent.TEMPERATURE_READ: _handle_temperature,
    Intent.AC_SET:           _handle_ac,

    # recognized, backend route not built yet -- replace None when it exists
    Intent.LOCATION_READ:    None,
    Intent.TIRES_READ:       None,
    Intent.BATTERY_READ:     None,
    Intent.DOORS_LOCK:       None,
}

# Human-readable names for the "not supported yet" message.
INTENT_LABELS: dict[Intent, str] = {
    Intent.LOCATION_READ: "your car's location",
    Intent.TIRES_READ:    "tyre pressure",
    Intent.BATTERY_READ:  "battery level",
    Intent.DOORS_LOCK:    "door locking",
}


# --- orchestration -----------------------------------------------------------

async def handle_text(session: AsyncSession, user_id: str, text: str) -> dict:
    """Full pipeline: text -> intent -> handler (or placeholder) -> reply.

    Returns a dict the router turns into JSON. We include the intent and
    confidence so the app can display/debug what was understood -- useful while
    the extractor is still being tuned.
    """
    result: IntentResult = extract(text)

    base = {
        "intent": result.intent.value,
        "slots": result.slots,
        "confidence": round(result.confidence, 2),
        "supported": False,
        "executed": False,
    }

    # 1. Didn't understand at all.
    if result.intent is Intent.UNKNOWN:
        return {**base,
                "reply": "Sorry, I didn't understand that. "
                         "You can ask about the temperature or the air conditioning."}

    handler = HANDLERS.get(result.intent)

    # 2. Understood, but no handler wired yet.
    if handler is None:
        label = INTENT_LABELS.get(result.intent, "that")
        return {**base, "supported": False,
                "reply": f"I understood you want {label}, "
                         f"but that isn't available yet."}

    # 3. Understood and supported -- but if it ACTUATES and we're not confident,
    #    ask rather than act. A wrong read is harmless; a wrong actuation isn't.
    if result.intent in ACTUATING and result.confidence < CONFIRM_THRESHOLD:
        return {**base, "supported": True,
                "reply": f"Did you want me to {result.intent.value.split('.')[-2]} "
                         f"{result.slots.get('state', '')}? Please confirm."}

    # 4. Execute. Domain errors map to plain-language replies -- the assistant
    #    speaks, it doesn't return HTTP codes.
    try:
        reply = await handler(session, user_id, result.slots)
        return {**base, "supported": True, "executed": True, "reply": reply}
    except NoVehicleForUser:
        return {**base, "supported": True,
                "reply": "There's no vehicle registered on your account."}
    except CarTimeout:
        # Honest wording: a timeout means we DON'T KNOW, not that it failed.
        return {**base, "supported": True,
                "reply": "I couldn't reach the car in time, so I can't confirm that."}
    except CarRejected as exc:
        return {**base, "supported": True,
                "reply": f"The car refused that: {exc}"}