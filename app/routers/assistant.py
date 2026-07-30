"""/assistant endpoints. Thin HTTP layer, as always."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.Dependecies import CurrentUser, SessionDep
from app.intents import assistant_service

router = APIRouter(prefix="/assistant", tags=["assistant"])


class CommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.post("/command")
async def command(body: CommandRequest, user: CurrentUser, session: SessionDep):
    """Send free text; get an intent + a spoken-style reply.

    Note this returns 200 even for unknown/unsupported intents. That's
    deliberate: "I didn't understand" is a successful CONVERSATION, not an HTTP
    error. Reserve error codes for things that actually went wrong.
    """
    return await assistant_service.handle_text(session, user.id, body.text)


@router.post("/parse")
async def parse(body: CommandRequest):
    """Extract the intent WITHOUT executing anything.

    Useful for tuning the extractor and for demoing recognition coverage to your
    manager without actuating a car every time you test a phrase.
    """
    from app.intents.extractor import extract

    result = extract(body.text)
    return {
        "intent": result.intent.value,
        "slots": result.slots,
        "confidence": round(result.confidence, 2),
    }