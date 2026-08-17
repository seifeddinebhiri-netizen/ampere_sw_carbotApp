# Ampere SW CarbotApp — MyCarBot Backend

A FastAPI backend that bridges mobile HTTP/WebSocket clients to a cloud MQTT broker for vehicle interactions. It implements request/response correlation over MQTT, forwards unsolicited vehicle state to connected WebSocket clients, and includes a local vehicle simulator (FakeCar) for development and testing.

Highlights
- Request/response correlation over MQTT with per-request request_id matching.
- WebSocket registry that ensures only authorized sockets receive messages for a VIN.
- Simple local car simulator (FakeCar.py) that answers requests and broadcasts retained state.
- Design notes and a scaling plan for running at fleet scale (10M+ vehicles).

Table of contents
- What this is
- Stack
- Project layout
- Runtime architecture (how it fits together)
- Configuration (env vars & config files)
- Quickstart — run locally
- Running with MQTT brokers (dev notes)
- Tests and developer utilities
- Scaling & production considerations (summary)
- Development notes (key modules)
- Contributing
- License & contact

## What this is
A small, async FastAPI service that exposes application-facing HTTP and WebSocket APIs, translates requests into MQTT publishes to vehicle topics, waits for correlated MQTT responses (by `request_id`), and returns results to clients. It also forwards unsolicited vehicle state updates to authorized WebSocket clients.

### Stack
- Language: Python 3 (asyncio)
- Framework / runtime: FastAPI + Uvicorn (async)
- Notable libraries: aiomqtt (MQTT client), SQLAlchemy (async DB access), pydantic (validation)

## Project layout
Top-level files and directories you will use:
```
README.md
requirements.txt          # pip dependencies
FakeCar.py                # local car simulator (publishes responses, broadcasts state)
run.txt                   # example run commands for local mosquitto + uvicorn
config_files.txt          # sample mosquitto configs & ACLs used in local testing
scalingPlan.md            # design + scaling notes for large fleets (10M vehicles)
app/                      # main FastAPI application code
  Config.py               # config & defaults
  main.py                 # FastAPI app entrypoint
  Mqtt.py                 # MQTT client + request/response machinery
  Backend.py              # higher-level backend glue (request orchestration, logs)
  ws_registery.py         # WebSocket registry: authorized VIN <> sockets
  make_certs.py           # dev cert generation helpers
  routers/                # HTTP route handlers (Auth.py, Car.py, assistant.py, ws.py)
  intents/                # natural-language intent extractor & assistant service
  services/                # business logic (car_service, assistant_service, etc.)
  schemas/                 # pydantic output/input schemas
FakeCar.py
test.py
test_assistant.py
```

How it fits together (runtime shape)
- Uvicorn runs the FastAPI app (app.main).
- HTTP requests and WebSocket connections hit routers in app/routers.
- For vehicle operations (e.g., read temperature, AC commands), the router calls a service which:
  - Builds the MQTT topic (e.g., `vehicle/<VIN>/climate/temperature/request`) and a `request_id`.
  - Publishes the request over the single long-lived aiomqtt client (app.Mqtt.bus).
  - Stores a Future keyed by `request_id`, awaits it with a timeout.
  - When the backend's MQTT listener receives a response with matching `request_id`, it resolves the Future and returns the payload to the HTTP call.
- Unsolicited broadcasts from vehicles (e.g., `vehicle/<VIN>/climate/ac/state`) are routed by VIN to registered WebSocket clients by app/ws_registery.py; they are not matched to a request_id and are handled separately.

## Configuration
See app/Config.py for the source of truth. Notable environment variables used by the app:

Required
- JWT_SECRET — secret used to sign/verify access tokens (integration tests and protected routes depend on this).

Optional (with defaults)
- DATABASE_URL — default: `sqlite+aiosqlite:///./mycarbot.db` (change to PostgreSQL for production)
- MQTT_HOST — default broker hostname (dev: localhost)
- MQTT_PORT — broker port (dev: 1884 / 8883 depending on your broker)
- MQTT_USERNAME, MQTT_PASSWORD — backend credentials for cloud broker
- RESPONSE_TIMEOUT — default 5.0 seconds (how long the backend waits for a correlated response)
- MQTT_TLS_CA, MQTT_TLS_CERT, MQTT_TLS_KEY — filenames to enable TLS / mTLS to the broker

Local MQTT broker testing also uses mosquitto config snippets in config_files.txt (cloud.conf / car.conf) and an ACL example using `pattern readwrite vehicle/%u/#` to scale safely.

## Quickstart — run locally
1. Create and activate a virtualenv, then install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. Start the FastAPI server (development):
```bash
uvicorn app.main:app --reload --port 8000
# OR use the included runner
python test.py
```

3. In a separate terminal, start the local car simulator:
```bash
python FakeCar.py
```

4. Example health check:
```
GET http://localhost:8000/health
# returns JSON like {"status": "ok", "pending_requests": ...}
```

5. Exercise features:
- Temperature read flow (HTTP route exposed by the Car router — see app/routers/Car.py)
- AC set flow (POST/PUT style command -> backend publishes to `vehicle/<VIN>/climate/ac/command` with request_id)
- Connect a WebSocket client and register for VIN updates to receive unsolicited `.../ac/state` broadcasts

## Running with local MQTT brokers (dev notes)
The repo includes sample mosquitto configs and a `run.txt` file with example commands:
- Start a local car broker on port 1884 and a cloud broker on 8883 (with TLS and mTLS settings in config_files.txt).
- The `cloud-acl.txt` sample shows the recommended ACL pattern rule:
  ```
  pattern readwrite vehicle/%u/#
  user backend-service
  topic readwrite vehicle/#
  ```
  Using `%u` with `use_identity_as_username true` ties access to the client certificate CN (recommended for production mTLS).

Tip: the included make_certs.py script can help generate dev certs for local mTLS testing.

## Tests & utilities
- Run the quick tests / scripts:
```bash
python test.py
python test_assistant.py
# or run pytest
python -m pytest -q
```
- test_assistant.py exercises the intents extractor (app/intents/extractor.py) and includes many phrase-to-intent examples to verify the rules-based extractor.

## Scaling & production considerations (summary)
The repo contains a dedicated scalingPlan.md with a handoff-style design for real production (10M vehicles). Key takeaways:
- Connection count is the dominant problem: each vehicle holds an outbound MQTT/TLS connection.
- Broker choice matters: plain Mosquitto does not cluster for subscriber/session state. Prefer a natively-clustering broker (EMQX, HiveMQ, VerneMQ) or adopt a shard-by-VIN architecture.
- Backend request correlation currently uses an in-memory request_id → Future table (stateful). To safely run multiple backend replicas, responses must be routed to the instance that issued the request (per-instance reply topics) or a durable coordination layer must be introduced.
- SQLite is fine for local dev but must be replaced with PostgreSQL (managed DB) for production scale.
- PKI and certificate lifecycle (issuance, rotation, revocation) are full workstreams for real deployments. Use `%u`-based ACLs and mTLS to avoid per-VIN ACL files.

Read scalingPlan.md for full design, trade-offs, and suggested sequencing.

## Development notes (key modules)
- app/main.py — FastAPI app factory and startup/shutdown hooks.
- app/Mqtt.py — Single long-lived aiomqtt client, request()/response() pattern, incoming messages handler.
- app/Backend.py — Orchestrates high-level flows, command logging and persistence.
- app/ws_registery.py — Tracks WebSocket registrations and routes unsolicited VIN broadcasts only to authorized sockets.
- app/routers/Car.py — Vehicle-related HTTP routes (temperature, AC commands, list vehicles).
- app/routers/Auth.py — Authentication endpoints and JWT handling.
- app/intents/* — Intent extractor and assistant service (rules-based NL intent extraction used by assistant router).
- FakeCar.py — Local car simulator; publishes retained AC state and replies to requests, useful for end-to-end dev/test.

If you plan to change request/response behavior, start in app/Mqtt.py and follow the existing request_id Future pattern. The scaling notes explain how that pattern must change for a replicated backend.

## Contributing
- Follow existing code style.
- Add tests for new behavior: unit tests for services and integration tests for request/response flows.
- Set JWT_SECRET for integration tests that exercise auth-protected routes.
- If you want, open issues for larger design changes (e.g., migration to Postgres, clustered brokers, per-instance response topics).

## License
Add license text here (e.g., MIT). Currently a placeholder in the repo.

## Contact
Author: seifeddinebhiri-netizen
