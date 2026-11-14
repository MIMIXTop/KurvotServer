from datetime import datetime

from pydantic import BaseModel, ConfigDict

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
