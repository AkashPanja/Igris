from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SetupState(BaseModel):
    installed: bool
    setup_token_required: bool
    smtp_configured: bool


class SetupStep1(BaseModel):
    app_name: str = Field(min_length=1, max_length=64)
    setup_token: str = ""


class SetupStep2(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)


class SmtpConfig(BaseModel):
    host: str = ""
    port: int = 587
    security: str = "STARTTLS"
    username: str = ""
    password: str = ""
    from_name: str = ""
    from_email: str = ""


class SetupStep3(SmtpConfig):
    pass


class SetupFinish(BaseModel):
    smtp: SetupStep3 | None = None


class LoginRequest(BaseModel):
    username_or_email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)


class SmtpTestResult(BaseModel):
    success: bool
    message: str


class Message(BaseModel):
    detail: str


class HealthOut(BaseModel):
    status: str
    version: str
    installed: bool
