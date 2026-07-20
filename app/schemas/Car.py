"""Request/response shapes for /car."""

from typing import Literal

from pydantic import BaseModel


class AcRequest(BaseModel):
    # Literal does the validation for us: anything but "on"/"off" is rejected by
    # FastAPI with a 422 before our code ever runs.
    state: Literal["on", "off"]


class TemperatureOut(BaseModel):
    vin: str
    temperature: float
    unit: str = "C"


class AcOut(BaseModel):
    vin: str
    ac: str
    ok: bool


class VehicleOut(BaseModel):
    id: str
    vin: str
    name: str

    model_config = {"from_attributes": True}