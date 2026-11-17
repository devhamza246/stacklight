"""Payload models per approval kind. Strict: unknown fields are rejected."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_PAYLOAD_BYTES = 50_000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReplyPayload(_Strict):
    ticket_text: str | None = None
    subject: str | None = None
    body: str = Field(min_length=1)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    tone: str = "neutral"


class ReplaceText(_Strict):
    type: Literal["replace_text"]
    find: str = Field(min_length=1)
    replace: str
    # An edit whose `find` occurs more than once is refused at apply time unless this is true.
    replace_all: bool = False


class Archive(_Strict):
    type: Literal["archive"]


class Supersede(_Strict):
    type: Literal["supersede"]
    superseded_by_document_id: int


Change = Annotated[ReplaceText | Archive | Supersede, Field(discriminator="type")]


class KbChangePayload(_Strict):
    document_id: int
    change: Change
    finding_summary: str
    source_document_ids: list[int]


PAYLOAD_MODELS: dict[str, type[BaseModel]] = {"reply": ReplyPayload, "kb_change": KbChangePayload}
