"""/car endpoints. Every one requires a valid token.

Notice: no endpoint takes a VIN. That's not an omission -- it's the design. The
VIN is resolved from the authenticated user inside the service. If a VIN ever
appears as a path or query parameter here, anyone could drive anyone's car.
"""

from fastapi import APIRouter, HTTPException, status

from app.Dependecies import CurrentUser, SessionDep
from app.Exeptions import CarRejected, CarTimeout, NoVehicleForUser
from app.schemas.Car import AcOut, AcRequest, TemperatureOut, VehicleOut
from app.services import CarService

router = APIRouter(prefix="/car", tags=["car"])


@router.get("/vehicles", response_model=list[VehicleOut])
async def my_vehicles(user: CurrentUser, session: SessionDep):
    return await CarService.list_vehicles(session, user.id)


@router.get("/temperature", response_model=TemperatureOut)
async def temperature(user: CurrentUser, session: SessionDep):
    try:
        vin, value = await CarService.read_temperature(session, user.id)
    except NoVehicleForUser:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="no vehicle registered for this account")
    except CarTimeout:
        # 504: an UPSTREAM service didn't answer. Not 500 -- we didn't break.
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                            detail="car did not respond in time")
    return TemperatureOut(vin=vin, temperature=value)


@router.post("/ac", response_model=AcOut)
async def set_ac(body: AcRequest, user: CurrentUser, session: SessionDep):
    try:
        vin, state = await CarService.set_ac(session, user.id, body.state)
    except NoVehicleForUser:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="no vehicle registered for this account")
    except CarTimeout:
        # Wording matters. "could not confirm", not "failed" -- the AC may well
        # be running right now and only the ack got lost. The app should show
        # this as uncertainty, never as failure.
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                            detail="could not confirm the command reached the car")
    except CarRejected as exc:
        # 502: the car answered and said no. Unlike a timeout, here we KNOW.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return AcOut(vin=vin, ac=state, ok=True)