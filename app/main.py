"""Entrypoint. Wiring only -- no logic lives here.

Run:  uvicorn app.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.DataBase.DB import init_db
from app.Mqtt import bus
from app.routers import Auth, Car


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await bus.start()
    try:
        yield          # <-- the server runs here, for as long as it lives
    finally:
        await bus.stop()


app = FastAPI(title="MyCarBot backend", version="0.2.0", lifespan=lifespan)

app.include_router(Auth.router)
app.include_router(Car.router)


@app.get("/health", tags=["meta"])
async def health():
    """Liveness only -- deliberately does NOT touch the car.

    Keep these separate: otherwise you can't tell "my server is down" from "the
    car is in a tunnel". pending_count is your leak detector -- if it climbs and
    never falls, something is wrong.
    """
    return {"status": "ok", "pending_requests": bus.pending_count}