from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AppSessions, AuthUsers, GoogleOAuthTokens, OAuthStates


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_oauth_state(
        self, state_hash: str, telegram_id: int, expires_at: datetime
    ) -> None:
        self.session.add(
            OAuthStates(
                state_hash=state_hash,
                telegram_id=telegram_id,
                expires_at=expires_at,
            )
        )
        await self.session.commit()

    async def consume_oauth_state(
        self, state_hash: str, now: datetime
    ) -> Optional[OAuthStates]:
        result = await self.session.execute(
            select(OAuthStates)
            .where(
                OAuthStates.state_hash == state_hash,
                OAuthStates.consumed_at.is_(None),
                OAuthStates.expires_at > now,
            )
            .with_for_update()
        )
        oauth_state = result.scalar_one_or_none()
        if oauth_state is not None:
            oauth_state.consumed_at = now
        return oauth_state

    async def find_user_by_google_sub(self, google_sub: str) -> Optional[AuthUsers]:
        result = await self.session.execute(
            select(AuthUsers).where(AuthUsers.google_sub == google_sub)
        )
        return result.scalar_one_or_none()

    async def find_user_by_telegram_id(self, telegram_id: int) -> Optional[AuthUsers]:
        result = await self.session.execute(
            select(AuthUsers).where(AuthUsers.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def find_user_by_session_hash(
        self, session_hash: str, now: datetime
    ) -> Optional[AuthUsers]:
        result = await self.session.execute(
            select(AuthUsers)
            .join(AppSessions, AppSessions.user_id == AuthUsers.id)
            .where(
                AppSessions.session_hash == session_hash,
                AppSessions.revoked_at.is_(None),
                AppSessions.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def get_refresh_token(self, user_id) -> Optional[str]:
        result = await self.session.execute(
            select(GoogleOAuthTokens.refresh_token_enc).where(
                GoogleOAuthTokens.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def get_google_tokens(self, user_id: UUID) -> Optional[GoogleOAuthTokens]:
        result = await self.session.execute(
            select(GoogleOAuthTokens).where(GoogleOAuthTokens.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def update_google_tokens(
        self,
        user_id: UUID,
        access_token_enc: str,
        refresh_token_enc: Optional[str],
        expires_at: datetime,
        scope: Optional[str],
        token_type: Optional[str],
    ) -> None:
        tokens = await self.get_google_tokens(user_id)
        if tokens is None:
            raise LookupError("Google OAuth tokens not found")
        tokens.access_token_enc = access_token_enc
        if refresh_token_enc is not None:
            tokens.refresh_token_enc = refresh_token_enc
        tokens.expires_at = expires_at
        tokens.scope = scope
        tokens.token_type = token_type

    async def save_user(
        self,
        user: Optional[AuthUsers],
        google_sub: str,
        email: str,
        name: Optional[str],
        picture: Optional[str],
        telegram_id: int,
        login_at: datetime,
    ) -> AuthUsers:
        if user is None:
            user = AuthUsers(
                google_sub=google_sub,
                email=email,
                name=name,
                picture_url=picture,
                telegram_id=telegram_id,
                last_login_at=login_at,
            )
            self.session.add(user)
            await self.session.flush()
        else:
            user.email = email
            user.name = name
            user.picture_url = picture
            user.telegram_id = telegram_id
            user.last_login_at = login_at
        return user

    async def save_google_tokens(
        self,
        user_id,
        access_token_enc: str,
        refresh_token_enc: Optional[str],
        expires_at: datetime,
        scope: Optional[str],
        token_type: Optional[str],
    ) -> None:
        result = await self.session.execute(
            select(GoogleOAuthTokens).where(GoogleOAuthTokens.user_id == user_id)
        )
        tokens = result.scalar_one_or_none()
        if tokens is None:
            self.session.add(
                GoogleOAuthTokens(
                    user_id=user_id,
                    access_token_enc=access_token_enc,
                    refresh_token_enc=refresh_token_enc,
                    expires_at=expires_at,
                    scope=scope,
                    token_type=token_type,
                )
            )
        else:
            tokens.access_token_enc = access_token_enc
            tokens.refresh_token_enc = refresh_token_enc
            tokens.expires_at = expires_at
            tokens.scope = scope
            tokens.token_type = token_type

    def create_session(
        self,
        user_id,
        session_hash: str,
        expires_at: datetime,
        user_agent: Optional[str],
    ) -> None:
        self.session.add(
            AppSessions(
                user_id=user_id,
                session_hash=session_hash,
                expires_at=expires_at,
                user_agent=user_agent,
            )
        )
