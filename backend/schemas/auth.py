from pydantic import BaseModel


class RegisterRequest(BaseModel):
    email: str
    password: str
    username: str | None = None
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class ProfileUpdateRequest(BaseModel):
    username: str | None = None
    display_name: str | None = None


class AppSettingsUpdateRequest(BaseModel):
    theme: str = "dark"
    language: str = "en"
    spoken_language: str = "auto"
    account_label_mode: str = "auto"