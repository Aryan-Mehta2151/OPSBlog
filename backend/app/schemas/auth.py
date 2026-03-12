from pydantic import BaseModel, EmailStr, field_validator
from enum import Enum

class OrganizationEnum(str, Enum):
    Google = "Google"
    Amazon = "Amazon"
    Meta = "Meta"

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    organization: OrganizationEnum

    @field_validator("email")
    def normalize_email(cls, v):
        return v.lower().strip()
    
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
    organizations: list[dict] = []

    class Config:
        from_attributes = True