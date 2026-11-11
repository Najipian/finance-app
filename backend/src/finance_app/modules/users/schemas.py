"""API schemas for users."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserRead(BaseModel):
    """Public view of a user. Never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(examples=["0b8f6f1e-3c3a-4a51-9a51-2f1f0f6b8c11"])
    email: str = Field(examples=["sara@example.com"])
    created_at: datetime
