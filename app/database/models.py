import uuid
from pydoc import text

import sqlalchemy as sa

from enum import Enum
from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, Text, func, Enum as SQLEnum, text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped


class Base(DeclarativeBase):
    pass

class UserRoles(Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"
    PAPIK = "papik"

class AppSessions(Base):
    __tablename__ = "app_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID,
        primary_key=True,
        default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(sa.UUID, default=uuid.uuid4)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
    )
    session_hash: Mapped[str] = mapped_column(sa.TEXT, default=uuid.uuid4)
    user_agent: Mapped[str] = mapped_column(sa.TEXT, default=uuid.uuid4)

class AuthUsers(Base):
    __tablename__ = "auth_users"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID,
        primary_key=True,
        default=uuid.uuid4
    )
    google_sub: Mapped[str] = mapped_column(
        sa.TEXT,
        unique=True,
        nullable=False,
    )
    email: Mapped[str] = mapped_column(
        sa.TEXT,
        unique=True,
        nullable=False,
    )
    name: Mapped[Optional[str]] = mapped_column(
        sa.TEXT,
    )
    picture_url: Mapped[Optional[str]] = mapped_column(
        sa.TEXT,
    )
    telegram_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
    )
    user_role: Mapped[UserRoles] = mapped_column(
        SQLEnum(UserRoles, name="user_role_enum", native_enum=False),
        default=UserRoles.STUDENT,
        server_default=text("'student'"),
        nullable=False,
    )

class GoogleOAuthTokens(Base):
    __tablename__ = "google_oauth_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID,
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    access_token_enc: Mapped[str] = mapped_column(
        sa.TEXT,
        nullable=False,
    )
    refresh_token_enc: Mapped[Optional[str]] = mapped_column(
        sa.TEXT,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    scope: Mapped[Optional[str]] = mapped_column(
        sa.TEXT,
    )
    token_type: Mapped[Optional[str]] = mapped_column(
        sa.TEXT,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

class OAuthStates(Base):
    __tablename__ = "oauth_states"

    state_hash: Mapped[str] = mapped_column(
        sa.TEXT,
        primary_key=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    consumed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )