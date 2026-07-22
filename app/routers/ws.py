"""WebSocket endpoint -- Step 2: authenticate + echo. No MQTT wiring yet.

Why echo-only first: it isolates "can an authenticated app hold a live two-way
connection to the backend" from "does car telemetry flow through it". Prove the
pipe before pushing real data through it.

A WebSocket begins life as an HTTP request, so we can read the JWT from the query
string at connect time and verify it BEFORE accepting the socket. An
unauthenticated socket that will later stream car state would be a hole -- so we
close it here if the token is bad.

Connect URL (dev):
  ws://<PC_IP>:8000/ws?token=<access_token>
"""
from sqlalchemy import select
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.DataBase.DB import SessionLocal
from app.DataBase.Models import Vehicle
from app.DataBase.Security import decode_access_token
from app.services import AuthService
from app.Exeptions import InvalidToken
from app.ws_registery import registry

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None):
    # --- authenticate BEFORE accepting -------------------------------------
    # We can inspect the token before completing the handshake. If it's bad, we
    # reject the connection outright -- the client never gets an open socket.
    if token is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = decode_access_token(token)
    if user_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Confirm the user still exists / is active (mirrors get_current_user).
    # type: AsyncSession
    async with SessionLocal() as session:  
        try:
            user = await AuthService.get_user(session, user_id)
        except InvalidToken:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        result = await session.scalars(
            select(Vehicle.vin).where(Vehicle.owner_id == user.id)
        )
        owned_vins = set(result)

    # --- accept and echo ----------------------------------------------------
    await websocket.accept()
    print(f"[ws] connected: user {user.id} vins={owned_vins or '{}'}")
    await registry.register(websocket, owned_vins)

    # Confirm to the client that auth succeeded and the pipe is live.
    await websocket.send_json({"type": "connected", "user_id": user.id,"vins": list(owned_vins),})

    try:
        while True:
            # For the echo test: whatever the client sends, we send back.
            # Later, this loop mostly just KEEPS THE SOCKET OPEN while a separate
            # path pushes car telemetry in.
            msg = await websocket.receive_text()
            await websocket.send_json({"type": "echo", "data": msg})
    except WebSocketDisconnect:
        print(f"[ws] disconnected: user {user.id}")
    finally:
        # ALWAYS unregister, even on error, or dead sockets accumulate.
        await registry.unregister(websocket)