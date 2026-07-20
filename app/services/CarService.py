"""Car business logic.

The rule enforced here, and it is the whole authorization model:

    THE VIN NEVER COMES FROM THE CLIENT.

The client sends a token. We resolve the user, then look up THEIR vehicle, and
use that VIN to build the topic. A user cannot ask for a car they don't own,
because they cannot ask for a car at all.

If this ever accepts a VIN as an argument from a router, the system is broken.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.Exeptions import CarRejected, CarTimeout, NoVehicleForUser
from app.DataBase.Models import CommandLog, Vehicle
from app.Mqtt import bus


def _topic(vin: str, suffix: str) -> str:
    return f"vehicle/{vin}/{suffix}"


async def _vehicle_for_user(session: AsyncSession, user_id: str) -> Vehicle:
    """THE authorization check. One query, and it's the security boundary."""
    vehicle = await session.scalar(
        select(Vehicle).where(Vehicle.owner_id == user_id)
    )
    if vehicle is None:
        raise NoVehicleForUser(user_id)
    return vehicle


async def _log(session: AsyncSession, user_id: str, vehicle: Vehicle,
               action: str, status: str, request_id: str | None = None,
               detail: str | None = None) -> None:
    session.add(
        CommandLog(
            user_id=user_id,
            vehicle_id=vehicle.id,
            vin=vehicle.vin,          # denormalised: the VIN as it was NOW
            action=action,
            status=status,
            request_id=request_id,
            detail=detail,
        )
    )
    await session.commit()


async def list_vehicles(session: AsyncSession, user_id: str) -> list[Vehicle]:
    result = await session.scalars(
        select(Vehicle).where(Vehicle.owner_id == user_id)
    )
    return list(result)


async def read_temperature(session: AsyncSession, user_id: str) -> tuple[str, float]:
    vehicle = await _vehicle_for_user(session, user_id)

    try:
        result = await bus.request(_topic(vehicle.vin, "climate/temperature/request"))
    except asyncio.TimeoutError:
        await _log(session, user_id, vehicle, "temperature.read", "timeout")
        raise CarTimeout()

    await _log(session, user_id, vehicle, "temperature.read", "ok",
               request_id=result.get("request_id"))
    return vehicle.vin, float(result["value"])


async def set_ac(session: AsyncSession, user_id: str, state: str) -> tuple[str, str]:
    vehicle = await _vehicle_for_user(session, user_id)
    action = f"ac.{state}"

    try:
        result = await bus.request(
            _topic(vehicle.vin, "climate/ac/command"), {"state": state}
        )
    except asyncio.TimeoutError:
        # "timeout", NOT "failed". We genuinely do not know whether the AC came
        # on -- the command may have executed and only the ack got lost. The log
        # must preserve that, and so must the UI.
        await _log(session, user_id, vehicle, action, "timeout")
        raise CarTimeout()

    if not result.get("ok"):
        detail = result.get("error", "car rejected command")
        await _log(session, user_id, vehicle, action, "rejected",
                   request_id=result.get("request_id"), detail=detail)
        raise CarRejected(detail)

    await _log(session, user_id, vehicle, action, "ok",
               request_id=result.get("request_id"))
    return vehicle.vin, result.get("state", state)