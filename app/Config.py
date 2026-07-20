"""All configuration in one place, read from .env.

Nothing else in the app calls os.getenv. One file owns config, so you always
know where a value came from and what happens if it's missing.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- Database ---------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./mycarbot.db")

# --- MQTT (cloud broker only -- we never touch the car broker) ---------------
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
RESPONSE_TIMEOUT = float(os.getenv("RESPONSE_TIMEOUT", "5.0"))

# TLS. Three states, and the code below picks one:
#   nothing set          -> plaintext (port 1883). Lab only.
#   CA only              -> TLS: we verify the broker, it verifies our password.
#   CA + cert + key      -> mTLS: we ALSO prove who we are with a certificate,
#                           and the cert's CN becomes our broker username.
MQTT_TLS_CA = os.getenv("MQTT_TLS_CA")
MQTT_TLS_CERT = os.getenv("MQTT_TLS_CERT")
MQTT_TLS_KEY = os.getenv("MQTT_TLS_KEY")

# --- Auth -------------------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "30"))

# Fail loudly at import time, not on the first login at 2am.
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is not set -- add it to your .env")