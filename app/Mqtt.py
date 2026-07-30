"""MQTT infrastructure: one persistent client, correlated request/response.

This is the ONLY file that knows MQTT exists. Services call `bus.request()` and
get a dict back -- they don't know a broker is involved. Swap MQTT for something
else and only this file changes.

  backend  --> cloud broker --bridge--> car broker --> car
We connect ONLY to the cloud broker. The car broker is not our business.
"""

import asyncio
import json
import uuid

import aiomqtt

from app.Config import (
    MQTT_HOST,
    MQTT_PASSWORD,
    MQTT_PORT,
    MQTT_TLS_CA,
    MQTT_TLS_CERT,
    MQTT_TLS_KEY,
    MQTT_USERNAME,
    RESPONSE_TIMEOUT,
)

from app.ws_registery import registry 

# '+' is a single-level wildcard in the VIN slot: one subscription serves every
# car, so we never resubscribe as the fleet grows.
SUBSCRIPTIONS = [
    "vehicle/+/climate/temperature/response",
    "vehicle/+/climate/ac/ack",
    "vehicle/+/climate/ac/state", 
]

def _vin_from_topic(topic: str) -> str | None:
        parts = topic.split("/")
        if len(parts) >= 2 and parts[0] == "vehicle":
            return parts[1]
        return None
class MqttBus:
    """Owns the connection and the pending-request table.

    The pending dict is a rack of pagers keyed by request_id:
      - request() takes a pager, publishes, and waits on it
      - the listener buzzes the right pager when its answer arrives
    Without this, two simultaneous requests would grab each other's responses,
    because both answers land on the SAME topic.
    """

    def __init__(self) -> None:
        self._client: aiomqtt.Client | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._listener: asyncio.Task | None = None

    # --- lifecycle ----------------------------------------------------------

    @staticmethod
    def _tls_params() -> aiomqtt.TLSParameters | None:
        """Build TLS settings, or None for plaintext.

        ca_certs is what lets US verify THE BROKER -- without it, anyone who can
        redirect our traffic can impersonate the broker and harvest everything
        we send. certfile/keyfile are the reverse: how the broker verifies US.
        """
        if not MQTT_TLS_CA:
            return None
        return aiomqtt.TLSParameters(
            ca_certs=MQTT_TLS_CA,
            certfile=MQTT_TLS_CERT,   # None in plain-TLS mode -- that's fine
            keyfile=MQTT_TLS_KEY,
        )

    async def start(self) -> None:
        """Open ONE connection for the server's whole life.

        Connecting per request would be slow and wrong. This single client both
        subscribes (to hear responses) and publishes (to send requests) -- one
        client, both roles.
        """
        import sys, asyncio
        if sys.platform == "win32":
        # Harmless if already set; guarantees the selector loop is active
        # by the time we touch aiomqtt's sockets.
          asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
          tls = self._tls_params()

        # Under mTLS the broker takes our identity from the certificate CN
        # (use_identity_as_username), so sending a username/password is
        # pointless -- and leaving them set can confuse the handshake.
        use_certs = tls is not None and MQTT_TLS_CERT is not None

        self._client = aiomqtt.Client(
            MQTT_HOST,
            port=MQTT_PORT,
            username=None if use_certs else MQTT_USERNAME,
            password=None if use_certs else MQTT_PASSWORD,
            tls_params=tls,
        )
        await self._client.__aenter__()

        mode = "mTLS" if use_certs else ("TLS" if tls else "plaintext")
        print(f"[mqtt] transport: {mode}")

        for topic in SUBSCRIPTIONS:
            await self._client.subscribe(topic, qos=1)
            print(f"[mqtt] subscribed {topic}")

        self._listener = asyncio.create_task(self._listen())
        print(f"[mqtt] connected to cloud broker {MQTT_HOST}:{MQTT_PORT}")

    async def stop(self) -> None:
        if self._listener:
            self._listener.cancel()
        if self._client:
            await self._client.__aexit__(None, None, None)
        print("[mqtt] disconnected")

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    # --- internals ----------------------------------------------------------

    async def _listen(self) -> None:
        assert self._client is not None
        async for message in self._client.messages:
            topic = str(message.topic)
            try:
                payload = json.loads(message.payload.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                print(f"[mqtt] non-JSON message on {topic}, ignoring")
                continue
 
            # --- STATE broadcasts: forward to WebSocket clients --------------
            # These are telemetry, not replies. They have no request_id. We
            # extract the VIN from the topic and hand off to the registry, which
            # pushes ONLY to sockets whose user owns that VIN.
            if topic.endswith("/climate/ac/state"):
                vin = _vin_from_topic(topic)
                if vin:
                    await registry.push_to_vin(vin, {
                        "type": "ac_state",
                        "vin": vin,
                        "state": payload.get("state"),
                    })
                    print(f"[mqtt->ws] ac_state {vin} = {payload.get('state')}")
                continue
 
            # --- everything else: the existing request/response correlation --
            request_id = payload.get("request_id")
            if request_id is None:
                print(f"[mqtt] no request_id on {topic}, ignoring")
                continue
 
            future = self._pending.pop(request_id, None)
            if future is None:
                print(f"[mqtt] unmatched response {request_id}")
                continue
 
            if not future.done():
                future.set_result(payload)
    
    # --- public API ---------------------------------------------------------

    async def request(self, topic: str, body: dict | None = None,
                      timeout: float = RESPONSE_TIMEOUT) -> dict:
        """Publish a request, wait for its matching response.

        Raises asyncio.TimeoutError if the car doesn't answer in time.
        """
        if self._client is None:
            raise RuntimeError("MqttBus.start() was never called")

        request_id = str(uuid.uuid4())
        message = {**(body or {}), "request_id": request_id}

        # Take the pager BEFORE publishing. If we published first, a very fast
        # car could answer before the pager exists and the listener would drop
        # it as unmatched. Same lesson as subscribe-before-publish.
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[request_id] = future

        try:
            # qos=1 = at-least-once. Not fire-and-forget: we care that it lands.
            await self._client.publish(topic, json.dumps(message), qos=1)
            print(f"[mqtt] -> {topic} {message}")
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            # Always clean up. A timed-out pager left in the rack is a memory
            # leak that grows every time a car is out of coverage.
            self._pending.pop(request_id, None)


# One instance for the process. Created here, started in main.py's lifespan.
bus = MqttBus()