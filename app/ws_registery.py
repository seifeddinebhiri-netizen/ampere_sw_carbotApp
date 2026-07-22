"""Live WebSocket connections, indexed so we can route car telemetry correctly.

THE RULE (same as everywhere else): a message about vehicle X reaches only the
sockets whose user OWNS vehicle X. This is owner_id authorization applied to a
live connection instead of a request. Get it wrong and users see each other's
cars -- the WebSocket version of "the VIN never comes from the client".

Design: we route by VIN. Each socket registers the set of VINs its user owns
(looked up from the DB at connect time). When a state message arrives for a VIN,
we push to exactly the sockets that registered that VIN.
"""

import asyncio
import json

from fastapi import WebSocket
#user A
##  [websocket 1 , (vin 1,vin 2 )]
#vin_of = [(websoket1, [vin 1 , vin 2])]
#vin_by =[(vin 1, [websocket 1]), (vin 2, [websocket 1])]

class ConnectionRegistry:
    def __init__(self) -> None:
        # vin -> set of sockets that are allowed to receive this vin's updates.
        # A set, so multiple devices of the same user (phone + tablet) all get it,
        # and duplicates can't happen.
        self._by_vin: dict[str, set[WebSocket]] = {}
        # Reverse map so disconnect cleanup is O(1) and can't miss anything.
        self._vins_of: dict[WebSocket, set[str]] = {}
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocket, vins: set[str]) -> None:
        """Bind a socket to the VINs its authenticated user owns."""
        async with self._lock:
            self._vins_of[websocket] = set(vins)
            for vin in vins:
                self._by_vin.setdefault(vin, set()).add(websocket)

    async def unregister(self, websocket: WebSocket) -> None:
        """Remove a socket from every index. Must be called on disconnect, or
        we leak dead sockets and eventually push to closed connections."""
        async with self._lock:
            vins = self._vins_of.pop(websocket, set())
            for vin in vins:
                subscribers = self._by_vin.get(vin)
                if subscribers:
                    subscribers.discard(websocket)
                    if not subscribers:
                        del self._by_vin[vin]

    async def push_to_vin(self, vin: str, message: dict) -> None:
        """Send a message to every socket authorized for this VIN.

        A socket is in _by_vin[vin] ONLY if its user owns vin -- so this method
        cannot deliver to an unauthorized user by construction. The authorization
        happened at register() time; here we just fan out.
        """
        async with self._lock:
            targets = list(self._by_vin.get(vin, set()))  # copy: we may mutate

        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                # Socket died without a clean disconnect. Collect and reap.
                dead.append(ws)

        for ws in dead:
            await self.unregister(ws)

    @property
    async def count(self) -> int:
        async with self._lock:
            return len(self._vins_of)


# One registry for the process.
registry = ConnectionRegistry()