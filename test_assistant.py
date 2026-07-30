"""Test table for the extractor. Run:  python test_intents.py

This is the real value of a rules-based extractor: you can PROVE what it does.
Add a row every time you find a phrase it gets wrong -- the table becomes your
regression suite, and it's what tells you whether adding a keyword broke
something else.
"""

from app.intents.extractor import extract
from app.intents.schema import Intent

# (phrase, expected intent, expected slots-subset or None)
CASES = [
    # --- AC on ---------------------------------------------------------------
    ("turn on the ac",                 Intent.AC_SET, {"state": "on"}),
    ("start the air conditioning",     Intent.AC_SET, {"state": "on"}),
    ("allume la clim",                 Intent.AC_SET, {"state": "on"}),
    ("active la climatisation",        Intent.AC_SET, {"state": "on"}),

    # --- AC off --------------------------------------------------------------
    ("turn off the ac",                Intent.AC_SET, {"state": "off"}),
    ("stop the air conditioning",      Intent.AC_SET, {"state": "off"}),
    ("eteins la clim",                 Intent.AC_SET, {"state": "off"}),
    ("coupe la climatisation",         Intent.AC_SET, {"state": "off"}),

    # --- temperature ---------------------------------------------------------
    ("what is the temperature",        Intent.TEMPERATURE_READ, {}),
    ("temperature",                    Intent.TEMPERATURE_READ, {}),
    ("quelle est la temperature",      Intent.TEMPERATURE_READ, {}),
    ("combien de degres dans la voiture", Intent.TEMPERATURE_READ, {}),

    # --- recognized but unsupported ------------------------------------------
    ("where is my car",                Intent.LOCATION_READ, {}),
    ("ou est ma voiture",              Intent.LOCATION_READ, {}),
    ("show me the gps position",       Intent.LOCATION_READ, {}),
    ("check the tire pressure",        Intent.TIRES_READ, {}),
    ("pression des pneus",             Intent.TIRES_READ, {}),
    ("what is the battery level",      Intent.BATTERY_READ, {}),
    ("lock the doors",                 Intent.DOORS_LOCK, {"state": "lock"}),
    ("unlock the doors",               Intent.DOORS_LOCK, {"state": "unlock"}),

    # --- out of scope: must be UNKNOWN, not a wrong guess ---------------------
    ("what is the capital of france",  Intent.UNKNOWN, {}),
    ("play some music",                Intent.UNKNOWN, {}),
    ("hello",                          Intent.UNKNOWN, {}),
    ("",                               Intent.UNKNOWN, {}),

    # --- tricky: whole-word matching --------------------------------------
    # "location" contains "on" -- must NOT be read as an AC-on command.
    ("what is my location",            Intent.LOCATION_READ, {}),
    ("where is my location",            Intent.LOCATION_READ, {}),
    ("donne moi la localistation de ma voiture", Intent.LOCATION_READ, {}),
    ("ou est la voiture",            Intent.LOCATION_READ, {}),
    ("ou est-elle",            Intent.LOCATION_READ, {}),


    ("température",                     Intent.TEMPERATURE_READ, {}),
    ("il fait chaud dans la voiture", Intent.TEMPERATURE_READ, {}),
    ("il fait froid dans la voiture", Intent.TEMPERATURE_READ, {}),
    ("quelle est la température de la voiture", Intent.TEMPERATURE_READ, {}),
    ("temperature voiture", Intent.TEMPERATURE_READ, {}),
]


def main() -> None:
    passed = failed = 0
    for phrase, expected_intent, expected_slots in CASES:
        result = extract(phrase)
        ok = result.intent is expected_intent
        if ok and expected_slots:
            ok = all(result.slots.get(k) == v for k, v in expected_slots.items())

        if ok:
            passed += 1
            print(f"PASS  {phrase!r} -> {result.intent.value} {result.slots}")  

        else:
            failed += 1
            print(f"FAIL  {phrase!r}")
            print(f"      expected {expected_intent.value} {expected_slots}")
            print(f"      got      {result.intent.value} {result.slots}")

    print(f"\n{passed} passed, {failed} failed, {len(CASES)} total")


if __name__ == "__main__":
    main()