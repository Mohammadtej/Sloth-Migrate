"""Domain models for demo repository using Pydantic v2 patterns."""

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict


class User(BaseModel):
    id: int
    username: str
    email: str
    bio: Optional[str] = None
    is_active: bool = True

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        populate_by_name=True
    )

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        return v.lower()

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Invalid email format")
        return v.lower()

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_json(self) -> str:
        return self.model_dump_json()


class ProductItem(BaseModel):
    item_id: str
    quantity: int = Field(gt=0)
    unit_price: float = Field(gt=0.0)

    model_config = ConfigDict(
        populate_by_name=True
    )


class Order(BaseModel):
    order_id: str
    customer_email: str
    items: List[ProductItem]
    total_amount: float = 0.0

    model_config = ConfigDict(
        validate_assignment=True
    )

    @model_validator(mode="before")
    @classmethod
    def calculate_total(cls, data: dict) -> dict:
        # In 'before' mode, 'items' is still a list of raw dicts, not ProductItem objects.
        # We must access them via dict keys to avoid AttributeError.
        items_raw = data.get("items") or []
        calculated = sum(item.get("quantity", 0) * item.get("unit_price", 0.0) for item in items_raw)
        data["total_amount"] = round(calculated, 2)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Order":
        return cls.model_validate(data)

    def serialize(self) -> dict:
        return self.model_dump()
