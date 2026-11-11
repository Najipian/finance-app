"""API schemas for categories and category rules (BR-07, BR-08)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from finance_app.modules.categories.models import RuleField, RuleOperator


class CategoryRead(BaseModel):
    """A category the user can assign."""

    id: uuid.UUID
    name: str = Field(examples=["Eating out"])
    icon: str | None = Field(examples=["utensils"])
    is_default: bool = Field(description="Built-in categories can't be deleted.")


class CategoryCreate(BaseModel):
    """A new user category."""

    name: str = Field(min_length=1, max_length=50, examples=["Kids"])
    icon: str | None = Field(default=None, max_length=32, examples=["star"])


class RuleRead(BaseModel):
    """One of the user's categorisation rules."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    match_field: RuleField
    operator: RuleOperator
    value: str = Field(examples=["Pret A Manger"])
    category_id: uuid.UUID
    priority: int
    created_at: datetime


class RuleCreate(BaseModel):
    """A new rule: if ``match_field`` ``operator`` ``value`` then ``category_id``."""

    match_field: RuleField = RuleField.DESCRIPTION
    operator: RuleOperator = RuleOperator.CONTAINS
    value: str = Field(min_length=2, max_length=100, examples=["GYM"])
    category_id: uuid.UUID
    priority: int = Field(default=100, ge=0, le=1000, description="Lower runs first.")
