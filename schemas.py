from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict

class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: EmailStr
    role: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = 'bearer'

class BookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    author: str
    description: str
    category: str
    cover_url: str | None
    file_size: int
    uploader_id: int
    downloads: int
    created_at: datetime

class BookUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=250)
    author: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(default=None, min_length=1, max_length=100)
