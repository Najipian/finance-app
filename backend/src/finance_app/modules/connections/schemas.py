"""API schemas for institutions and bank connections."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from finance_app.modules.connections.lifecycle import days_until, renewal_due
from finance_app.modules.connections.models import BankConnection, ConnectionStatus, SyncStatus


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


class ConnectionDetail(ConnectionRead):
    """A connection with renewal and sync health for the dashboard (BR-03, NFR-07)."""

    last_sync_status: SyncStatus | None = Field(
        description="ok, retrying (a retry is scheduled) or failed (retries exhausted)."
    )
    last_sync_error: str | None = Field(examples=["provider_unavailable"])
    renewal_due: bool = Field(description="True when consent expires within 7 days.")
    days_until_expiry: int | None = Field(examples=[5])

    @classmethod
    def from_model(cls, connection: BankConnection, now: datetime) -> "ConnectionDetail":
        """Build from the ORM model, computing renewal fields at ``now``."""
        base = ConnectionRead.model_validate(connection).model_dump()
        return cls(
            **base,
            last_sync_status=connection.last_sync_status,
            last_sync_error=connection.last_sync_error,
            renewal_due=renewal_due(connection.consent_expires_at, now),
            days_until_expiry=days_until(connection.consent_expires_at, now),
        )


class SyncQueued(BaseModel):
    """Result of a manual sync request."""

    queued: bool = Field(description="False if a sync was already queued this minute.")
