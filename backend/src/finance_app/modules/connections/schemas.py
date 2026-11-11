"""API schemas for institutions and bank connections."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from finance_app.modules.connections.models import ConnectionStatus


class InstitutionRead(BaseModel):
    """A bank the user can connect."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(examples=["mock-bank-uk"])
    name: str = Field(examples=["Mock Bank (UK)"])
    countries: list[str] = Field(examples=[["GB"]])
    logo_url: str | None = None


class StartConnectionRequest(BaseModel):
    """Which bank to connect."""

    institution_id: str = Field(min_length=1, max_length=128, examples=["mock-bank-uk"])


class ConnectionStarted(BaseModel):
    """Send the user's browser to ``authorisation_url`` to approve access at the bank."""

    connection_id: uuid.UUID
    authorisation_url: str


class ConnectionRead(BaseModel):
    """A bank connection and its status (never includes tokens)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    institution_id: str
    institution_name: str
    status: ConnectionStatus
    consent_expires_at: datetime | None
    last_synced_at: datetime | None
    created_at: datetime
