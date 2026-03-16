from pydantic import BaseModel, EmailStr, field_validator
from enum import Enum

class OrganizationEnum(str, Enum):
    Google = "Google"
    Amazon = "Amazon"
    Meta = "Meta"

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    username: str
    organization: OrganizationEnum

    @field_validator("email")
    def normalize_email(cls, v):
        return v.lower().strip()
    
    @field_validator("username")
    def normalize_username(cls, v):
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        if not v.replace("_", "").replace("-", "").replace(".", "").isalnum():
            raise ValueError("Username may only contain letters, numbers, underscores, hyphens and dots")
        return v.lower()
    
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    organization: OrganizationEnum

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshRequest(BaseModel):
    refresh_token: str

class UserResponse(BaseModel):
    id: str
    email: str

    class Config:
        from_attributes = True
class UserWithOrgResponse(BaseModel):
    id: str
    email: str
    username: str | None = None
    organizations: list[dict] = []

    class Config:
        from_attributes = True