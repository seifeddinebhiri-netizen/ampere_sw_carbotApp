"""Rule-based intent extraction. A PURE FUNCTION: text in, IntentResult out.

No database, no MQTT, no HTTP, no network. That makes it instant, deterministic,
offline-capable, and trivially testable -- all of which matter for something
whose output ends up actuating a vehicle.

How it works: each intent declares keyword groups. A phrase matches an intent
when it hits at least one keyword from EVERY required group. Groups are ANDed,
keywords within a group are ORed:

    AC_SET requires (an ac word) AND (an on/off word)
      "turn on the ac"  -> ac word: "ac", state word: "on"     -> match
      "the ac is nice"  -> ac word: "ac", state word: none     -> no match

The scoring picks the best-matching intent when several are plausible. If
nothing matches, we return UNKNOWN -- deliberately, not as a fallback guess.

Later, an LLM layer sits BEHIND this: only called when this returns UNKNOWN, so
the common cases stay instant and free.
"""

import re
import unicodedata

from app.intents.schema import Intent, IntentResult


# --- normalisation -----------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase, strip accents, collapse punctuation to spaces.

    Accent stripping matters here: users write "climatisation" or "climatisée",
    and "où est ma voiture" must match the same rule as "ou est ma voiture".
    """
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return f" {text.strip()} "        # pad so we can match whole words


def _has_any(text: str, words: list[str]) -> str | None:
    """Return the first keyword found as a WHOLE word, else None.

    Whole-word matching avoids the classic bug where "on" matches inside
    "location" or "front". We padded the text with spaces in _normalise so
    every word has boundaries on both sides.
    """
    for w in words:
        if f" {w} " in text:
            return w
    return None


# --- vocabulary --------------------------------------------------------------
# Bilingual on purpose: the users are French-speaking, the codebase is English.

AC_WORDS      = ["ac", "clim", "climatisation", "climatiseur", "air",
                 "conditioning", "aircon", "cooling"]
ON_WORDS      = ["on", "start", "allume", "allumer", "active", "activer",
                 "demarre", "demarrer", "mets", "met"]
OFF_WORDS     = ["off", "stop", "eteins", "eteindre", "coupe", "couper",
                 "desactive", "desactiver", "arrete", "arreter"]

TEMP_WORDS    = ["temperature", "temp", "degres", "degree", "degrees",
                 "chaud", "froid", "hot", "cold"]
READ_WORDS    = ["what", "whats", "quelle", "quel", "combien", "how",
                 "check", "read", "tell", "donne", "affiche", "show"]

LOCATION_WORDS = ["where", "location", "position", "gps", "ou", "situe",
                  "localiser", "localisation", "trouve"]
CAR_WORDS      = ["car", "voiture", "vehicule", "vehicle", "auto"]

TIRE_WORDS     = ["tire", "tires", "tyre", "tyres", "pneu", "pneus",
                  "pression", "pressure"]
BATTERY_WORDS  = ["battery", "batterie", "charge", "autonomie", "soc"]
DOOR_WORDS     = ["door", "doors", "porte", "portes", "lock", "unlock",
                  "verrouille", "verrouiller", "deverrouille"]


# --- extraction --------------------------------------------------------------

def extract(text: str) -> IntentResult:
    """Turn free text into an intent. Never raises; unknown input -> UNKNOWN."""
    if not text or not text.strip():
        return IntentResult(Intent.UNKNOWN, {}, 0.0, text or "")

    t = _normalise(text)
    candidates: list[tuple[Intent, dict, float]] = []

    # --- AC set (needs an ac word AND a state word) -------------------------
    ac_word = _has_any(t, AC_WORDS)
    if ac_word:
        off_word = _has_any(t, OFF_WORDS)
        on_word = _has_any(t, ON_WORDS)
        # Check OFF first: "turn off" contains no "on" as a whole word, but
        # being explicit about precedence avoids surprises as vocab grows.
        if off_word:
            candidates.append((Intent.AC_SET, {"state": "off"}, 0.95))
        elif on_word:
            candidates.append((Intent.AC_SET, {"state": "on"}, 0.95))

    # --- temperature read ---------------------------------------------------
    temp_word = _has_any(t, TEMP_WORDS)
    if temp_word:
        # A read verb raises confidence, but "temperature?" alone is still a
        # perfectly clear request, so we don't require one.
        conf = 0.9 if _has_any(t, READ_WORDS) else 0.75
        # Guard: "turn on the ac, it's hot" is an AC command, not a temp read.
        # If we already matched AC_SET, let scoring resolve it -- AC_SET's 0.95
        # wins over 0.75.
        candidates.append((Intent.TEMPERATURE_READ, {}, conf))

    # --- location (needs a location word; a car word strengthens it) --------
    loc_word = _has_any(t, LOCATION_WORDS)
    if loc_word:
        conf = 0.9 if _has_any(t, CAR_WORDS) else 0.7
        candidates.append((Intent.LOCATION_READ, {}, conf))

    # --- tyres --------------------------------------------------------------
    if _has_any(t, TIRE_WORDS):
        candidates.append((Intent.TIRES_READ, {}, 0.85))

    # --- battery ------------------------------------------------------------
    if _has_any(t, BATTERY_WORDS):
        candidates.append((Intent.BATTERY_READ, {}, 0.85))

    # --- doors --------------------------------------------------------------
    if _has_any(t, DOOR_WORDS):
        # "unlock"/"deverrouille" are their own words, so check those before
        # treating a generic lock word as "lock".
        unlock = _has_any(t, ["unlock", "deverrouille", "deverrouiller",
                              "ouvre", "ouvrir", "open"])
        state = "unlock" if unlock else "lock"
        candidates.append((Intent.DOORS_LOCK, {"state": state}, 0.8))

    if not candidates:
        return IntentResult(Intent.UNKNOWN, {}, 0.0, text)

    # Highest confidence wins.
    intent, slots, confidence = max(candidates, key=lambda c: c[2])
    return IntentResult(intent, slots, confidence, text)