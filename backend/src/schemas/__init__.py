"""Shared Pydantic v2 base classes for response schemas."""

from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    """All response schemas inherit from this so they accept SQLAlchemy ORM
    objects directly via ``model_validate(orm_obj)``.
    """
    model_config = ConfigDict(from_attributes=True)
