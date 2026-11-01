from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass(frozen=True)
class GoogleTokenResponse:
    access_token: str
    refresh_token: Optional[str]
    expires_in: int
    scope: Optional[str]
    token_type: Optional[str]


@dataclass(frozen=True)
class GoogleUserInfo:
    sub: str
    email: str
    name: Optional[str]
    picture: Optional[str]


@dataclass(frozen=True)
class AuthResult:
    user_id: UUID
    session_token: str
    email: str
    telegram_id: int
    login_at: datetime
