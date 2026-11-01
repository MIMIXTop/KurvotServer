from datetime import datetime, timedelta
from typing import Optional

from app.auth.google_client import GoogleOAuthClient
from app.auth.repository import AuthRepository
from app.auth.schemas import AuthResult
from app.utils.encrypt import Encryption


class OAuthStateError(RuntimeError):
    pass


class AuthService:
    def __init__(
        self,
        repository: AuthRepository,
        google_client: GoogleOAuthClient,
        encryption: Encryption,
    ) -> None:
        self.repository = repository
        self.google_client = google_client
        self.encryption = encryption

    async def create_google_state(
        self, telegram_id: int, state_token: str, now: datetime
    ) -> None:
        await self.repository.create_oauth_state(
            self.encryption.sha256_hex(state_token),
            telegram_id,
            now + timedelta(minutes=5),
        )

    async def authenticate_google(
        self,
        code: str,
        state_token: str,
        user_agent: Optional[str],
        now: datetime,
    ) -> AuthResult:
        oauth_state = await self.repository.consume_oauth_state(
            self.encryption.sha256_hex(state_token), now
        )
        if oauth_state is None:
            raise OAuthStateError("OAuth state is invalid or expired")

        token = await self.google_client.exchange_code_for_tokens(code)
        google_user = await self.google_client.fetch_user_info(token.access_token)
        user = await self.repository.find_user_by_google_sub(google_user.sub)

        refresh_token_enc = (
            self.encryption.text_encrypt(token.refresh_token)
            if token.refresh_token is not None
            else await self.repository.get_refresh_token(user.id) if user else None
        )
        user = await self.repository.save_user(
            user,
            google_user.sub,
            google_user.email,
            google_user.name,
            google_user.picture,
            oauth_state.telegram_id,
            now,
        )
        await self.repository.save_google_tokens(
            user.id,
            self.encryption.text_encrypt(token.access_token),
            refresh_token_enc,
            now + timedelta(seconds=token.expires_in),
            token.scope,
            token.token_type,
        )

        session_token = self.encryption.random_url_safe_token(32)
        self.repository.create_session(
            user.id,
            self.encryption.sha256_hex(session_token),
            now + timedelta(days=30),
            user_agent,
        )
        await self.repository.session.commit()
        return AuthResult(
            user_id=user.id,
            session_token=session_token,
            email=google_user.email,
            telegram_id=oauth_state.telegram_id,
            login_at=now,
        )
