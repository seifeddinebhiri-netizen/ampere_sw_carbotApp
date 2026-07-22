# """
# MyCarBot backend.

# Bridges HTTP (from the Android app) to MQTT (to the car, via the cloud broker).

#   Android app  --HTTP-->  THIS  --MQTT-->  cloud broker --bridge--> car broker --> car

# This process connects ONLY to the cloud broker. It never touches the car broker.
# """

# import asyncio
# import json
# import uuid
# from contextlib import asynccontextmanager
# import os
# from dotenv import load_dotenv
# import aiomqtt
# from fastapi import FastAPI, HTTPException
# from pydantic import BaseModel

# # Load environment variables
# load_dotenv()

# # --- Configuration -----------------------------------------------------------
# CLOUD_BROKER = os.getenv("CLOUD_BROKER", "localhost")
# CLOUD_PORT = int(os.getenv("CLOUD_PORT", 1883))
# MQTT_USERNAME = os.getenv("MQTT_USERNAME", "backend")
# MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "backend_secret")
# VIN = os.getenv("VIN", "TESTVIN123")

# # How long we wait for the car to answer before giving up.
# RESPONSE_TIMEOUT = 5.0     # seconds

# # --- Topics ------------------------------------------------------------------

# TOPIC_TEMP_REQUEST  = f"vehicle/{VIN}/climate/temperature/request"
# TOPIC_AC_COMMAND    = f"vehicle/{VIN}/climate/ac/command"

# # We subscribe with '+' (single-level wildcard) in the VIN slot so this backend
# # can serve many cars later without changing the subscription.
# SUBSCRIPTIONS = [
#     "vehicle/+/climate/temperature/response",
#     "vehicle/+/climate/ac/ack",
# ]

# # --- Pending request tracking ------------------------------------------------
# # The heart of request/response over pub-sub.
# #
# # When we send a request we create a Future (an empty "slot" for an answer that
# # hasn't arrived yet) and file it under its request_id. A background task listens
# # for responses and drops each one into the matching slot. The endpoint waits on
# # its own slot. This is what stops two simultaneous requests getting each other's
# # answers.

# pending: dict[str, asyncio.Future] = {}


# async def _listen(client: aiomqtt.Client) -> None:
#     """Background task: read every incoming MQTT message, route it to its waiter.
#     Runs for the whole life of the server. This is the ONLY place that iterates
#     client.messages -- the client allows a single reader.
#     """
#     async for message in client.messages:
#         print(f"pending1:{pending}")
#         try:
#             payload = json.loads(message.payload.decode())
#         except (json.JSONDecodeError, UnicodeDecodeError):
#             print(f"[mqtt] ignoring non-JSON message on {message.topic}")
#             continue

#         request_id = payload.get("request_id")
#         if request_id is None:
#             print(f"[mqtt] message on {message.topic} has no request_id, ignoring")
#             continue

#         future = pending.pop(request_id, None)
#         if future is None:
#             # Nobody is waiting for this. Usually means it already timed out,
#             # or it's a duplicate. Dropping it is correct.
#             print(f"[mqtt] unmatched response {request_id} on {message.topic}")
#             continue

#         if not future.done():
#             future.set_result(payload)
#         print(f"pending2:{pending}")
#         print(f"future:{future}")


# async def _request_response(client: aiomqtt.Client, request_topic: str,
#                             body: dict, timeout: float = RESPONSE_TIMEOUT) -> dict:
#     """Publish a request, wait for the matching response, return its payload.

#     This is the reusable core: every endpoint below is a thin wrapper around it.
#     Raises asyncio.TimeoutError if the car doesn't answer in time.
#     """
#     request_id = str(uuid.uuid4())
#     body = {**body, "request_id": request_id}
#     print(f"pending3:{pending}")

#     # Create the slot BEFORE publishing. If we published first, a very fast
#     # response could arrive before the slot exists and be dropped as unmatched.
#     # Same lesson as subscribe-before-publish.
#     loop = asyncio.get_running_loop()
#     future = loop.create_future()
#     pending[request_id] = future
#     print(f"pending4:{pending}")

#     try:
#         # qos=1 = at-least-once. Not fire-and-forget: we care that this arrives.
#         await client.publish(request_topic, json.dumps(body), qos=1)
#         print(f"[mqtt] -> {request_topic} {body}")
#         return await asyncio.wait_for(future, timeout=timeout)
#     finally:
#         # Always clean up, whether we succeeded, timed out, or errored.
#         # Otherwise timed-out requests leak into the dict forever.
#         pending.pop(request_id, None)
#         print(f"pending5:{pending}")
    


# # --- App lifecycle -----------------------------------------------------------

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     async with aiomqtt.Client(CLOUD_BROKER, port=CLOUD_PORT, username=MQTT_USERNAME, password=MQTT_PASSWORD) as client:
#         for topic in SUBSCRIPTIONS:
#             await client.subscribe(topic, qos=1)
#             print(f"[mqtt] subscribed {topic}")

#         listener = asyncio.create_task(_listen(client))
#         app.state.mqtt = client
#         print(f"[mqtt] connected to cloud broker {CLOUD_BROKER}:{CLOUD_PORT}")

#         try:
#             yield          # <-- server runs here
#         finally:
#             listener.cancel()
#             print("[mqtt] shutting down")


# app = FastAPI(title="MyCarBot backend", lifespan=lifespan)


# # --- Models ------------------------------------------------------------------

# class AcCommand(BaseModel):
#     state: str  # "on" or "off"


# # --- Endpoints ---------------------------------------------------------------

# @app.get("/health")
# async def health():
#     """Cheap liveness check. Does not touch the car."""
#     return {"status": "ok", "vin": VIN, "pending": len(pending)}


# @app.get("/temperature")
# async def get_temperature():
#     """
#     HTTP GET  ->  MQTT request  ->  bridge  ->  car  ->  MQTT response  ->  HTTP JSON
#     """
#     try:
#         result = await _request_response(app.state.mqtt, TOPIC_TEMP_REQUEST, {})
#     except asyncio.TimeoutError:
#         # 504 = upstream (the car) didn't answer in time. The honest status code.
#         raise HTTPException(status_code=504, detail="car did not respond in time")

#     return {"vin": VIN, "temperature": result.get("value"), "unit": "C"}


# @app.post("/ac")
# async def set_ac(command: AcCommand):
#     if command.state not in ("on", "off"):
#         raise HTTPException(status_code=400, detail="state must be 'on' or 'off'")

#     try:
#         result = await _request_response(
#             app.state.mqtt, TOPIC_AC_COMMAND, {"state": command.state}
#         )
#     except asyncio.TimeoutError:
#         # Important: a timeout does NOT mean the command failed. It means we
#         # don't know. The command may still have executed. Say so honestly.
#         raise HTTPException(status_code=504, detail="car did not acknowledge in time")

#     if not result.get("ok"):
#         raise HTTPException(status_code=502, detail=result.get("error", "car rejected command"))

#     return {"vin": VIN, "ac": result.get("state"), "ok": True}