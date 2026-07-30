# Ampere SW CarbotApp — MyCarBot Backend

A FastAPI backend that bridges mobile HTTP/WebSocket clients to a cloud MQTT broker for vehicle interactions. It provides request/response correlation over MQTT, pushes unsolicited vehicle state to authorized WebSocket clients, and includes a local FakeCar simulator for development.

## Quick summary
- FastAPI service (app.main) with a single long-lived MQTT client (app.Mqtt.bus).
- WebSocket registry (app.ws_registery) routes vehicle state messages to sockets that are authorized for the VIN.
- FakeCar.py simulates the vehicle broker for local development and testing.

## Stack
- Python 3 (asyncio)
- FastAPI + Uvicorn
- aiomqtt (MQTT), SQLAlchemy (async DB), pydantic

## Repo layout (relevant files)
- app/                FastAPI application code (routers, MQTT, DB init, ws registry)
- FakeCar.py          Local car simulator (car broker emulator)
- requirements.txt    Python dependencies
- test_assistant.py   Tests/examples
- scalingPlan.md      Notes on scaling & architecture

## Environment / configuration
See app/Config.py for defaults and required vars. Required before running:
- JWT_SECRET — mandatory (used to sign access tokens)

Optional (but important) environment variables:
- DATABASE_URL — default: sqlite+aiosqlite:///./mycarbot.db
- MQTT_HOST, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD
- RESPONSE_TIMEOUT — default 5.0
- MQTT_TLS_CA, MQTT_TLS_CERT, MQTT_TLS_KEY — for TLS / mTLS

## Run (development)
Install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Start the backend:
```bash
uvicorn app.main:app --reload --port 8000
```

Start the local fake car (separate terminal):
```bash
python FakeCar.py
```

Health check:
GET /health — returns {"status":"ok","pending_requests":...}

## Testing
Run the included tests or scripts:
```bash
python test.py
python test_assistant.py
# or
python -m pytest -q
```

## Development notes
- The MQTT bus (app/Mqtt.py) implements a request()/response pattern: each published message includes a generated request_id; the listener matches incoming messages by request_id and resolves the corresponding Future.
- State broadcasts (topic suffix `/climate/ac/state`) are retained by the car simulator and forwarded to WebSocket clients; these messages do not include request_id and are handled differently.
- app/ws_registery ensures a message for VIN X is only delivered to sockets that registered (and are authorized for) that VIN.

## Contributing
- Follow existing code style, include tests for new behavior.
- Ensure JWT_SECRET is set for integration tests that exercise auth-protected routes.

## License
[Add license here — e.g., MIT]

## Contact
Author: seifeddinebhiri-netizen
