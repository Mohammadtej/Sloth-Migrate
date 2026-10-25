from pydantic import BaseModel, validator


class UserProfile(BaseModel):
    username: str
    age: int

    @validator("username")
    def validate_username(cls, v):
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        return v.lower()

    def serialize(self) -> dict:
        # Legacy Pydantic v1 method (.dict is deprecated/removed in v2 in favor of .model_dump)
        return self.dict()