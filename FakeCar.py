"""
Fake car: stands in for your friend's SOME/IP <-> MQTT bridge plus the real car.

Connects to the CAR broker (1884). Listens for requests/commands, answers them.
Where this fakes a sensor read, the real bridge would make a SOME/IP call.

Swap this out for the real bridge later -- as long as the topics and the JSON
payload shape stay the same, nothing else in the system changes. That contract
is the thing to agree with your friend.
"""

import asyncio
import json
import random
import sys

import aiomqtt
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

CAR_BROKER = "localhost"
CAR_PORT = 1884            # the CAR broker. It bridges up to the cloud itself.

VIN = "TESTVIN123"

TOPIC_TEMP_REQUEST  = f"vehicle/{VIN}/climate/temperature/request"
TOPIC_TEMP_RESPONSE = f"vehicle/{VIN}/climate/temperature/response"
TOPIC_AC_COMMAND    = f"vehicle/{VIN}/climate/ac/command"
TOPIC_AC_ACK        = f"vehicle/{VIN}/climate/ac/ack"

# The car's actual state. In reality this lives in the hardware.
ac_state = "off"


async def main():
    global ac_state

    # One connection, both roles: subscribe to hear requests, publish to answer.
    async with aiomqtt.Client(CAR_BROKER, port=CAR_PORT) as client:
        print(f"[car] connected to car broker {CAR_BROKER}:{CAR_PORT}")

        await client.subscribe(TOPIC_TEMP_REQUEST, qos=1)
        await client.subscribe(TOPIC_AC_COMMAND, qos=1)
        print(f"[car] listening for requests and commands (VIN {VIN})")

        async for message in client.messages:
            try:
                payload = json.loads(message.payload.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                print(f"[car] bad payload on {message.topic}, ignoring")
                continue

            # Echo this back untouched -- it's how the backend matches the
            # answer to whoever asked. Drop it and the backend never resolves.
            request_id = payload.get("request_id")
            if request_id is None:
                print(f"[car] no request_id on {message.topic}, ignoring")
                continue

            topic = str(message.topic)

            if topic == TOPIC_TEMP_REQUEST:
                # "Read the sensor." The real bridge calls SOME/IP here.
                await asyncio.sleep(0.2)          # pretend it takes a moment
                value = round(random.uniform(19.0, 24.0), 1)
                response = {"request_id": request_id, "value": value}
                await client.publish(TOPIC_TEMP_RESPONSE, json.dumps(response), qos=1)
                print(f"[car] temperature -> {value}")

            elif topic == TOPIC_AC_COMMAND:
                state = payload.get("state")
                if state not in ("on", "off"):
                    ack = {"request_id": request_id, "ok": False,
                           "error": f"unknown state {state!r}"}
                else:
                    # "Actuate the AC." The real bridge calls SOME/IP here.
                    await asyncio.sleep(0.5)      # pretend the compressor responds
                    ac_state = state
                    ack = {"request_id": request_id, "ok": True, "state": ac_state}
                    print(f"[car] AC -> {ac_state}")

                await client.publish(TOPIC_AC_ACK, json.dumps(ack), qos=1)


if __name__ == "__main__":
    asyncio.run(main())