from pydantic import BaseModel, field_validator

class UserProfile(BaseModel):
    username: str
    age: int

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        return v.lower()

    def serialize(self) -> dict:
        return self.model_dump()
