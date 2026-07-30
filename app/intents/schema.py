"""Intent definitions -- the contract for the whole assistant layer.

Two rules that matter:

1. The intent list is CLOSED. An extractor may only return a value from this
   enum, or UNKNOWN. It can never invent an intent, which is what stops a
   future LLM layer from producing a "command" the system then tries to run.

2. UNKNOWN is a first-class result, not a failure. "What's the capital of
   France" should confidently return UNKNOWN. An extractor that always picks
   something is dangerous when the output actuates a vehicle.

Note what is NOT here: no MQTT topics, no handler functions. This layer says
WHAT the user wants, never HOW it gets done. The mapping to handlers lives in
assistant_service, so adding a real GPS route later changes one line there and
nothing here.
"""

from dataclasses import dataclass, field
from enum import Enum


class Intent(str, Enum):
    # --- wired to the car today -------------------------------------------
    TEMPERATURE_READ = "climate.temperature.read"
    AC_SET           = "climate.ac.set"

    # --- recognized, not yet implemented ----------------------------------
    # These exist so the assistant can say "I understood, but that isn't
    # available yet" instead of "I didn't understand". Keep this list honest --
    # only add intents that are actually on the roadmap.
    LOCATION_READ    = "location.read"
    TIRES_READ       = "tires.pressure.read"
    BATTERY_READ     = "battery.level.read"
    DOORS_LOCK       = "doors.lock.set"

    # --- catch-all ---------------------------------------------------------
    UNKNOWN          = "unknown"


@dataclass
class IntentResult:
    """What extract() returns.

    confidence is a rough 0..1 signal from the rules engine (how much of the
    phrase actually matched). It exists so the executor can require confirmation
    before ACTUATING something physical on a weak match -- reading a temperature
    is safe, turning on a compressor is not.
    """

    intent: Intent
    slots: dict = field(default_factory=dict)
    confidence: float = 0.0
    raw_text: str = ""