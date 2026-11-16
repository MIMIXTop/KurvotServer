from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.database.models import UserRoles


class PublicUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None
    email: str
    role: UserRoles
    created_at: datetime
    last_login_at: datetime | None
    telegram_linked: bool
    status: str


class UpdateUserRole(BaseModel):
    role: UserRoles


class AgentLogBatch(BaseModel):
    """A batch of formatted log records pushed by the Telegram agent."""

    service: str = "telegram-agent"
    lines: list[str] = Field(default_factory=list, max_length=200)
