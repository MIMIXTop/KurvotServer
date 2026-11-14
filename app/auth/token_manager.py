from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from app.auth.google_client import (
    GoogleOAuthClient,
    GoogleOAuthError,
    GoogleReauthRequired,
)
from app.auth.repository import AuthRepository
from app.utils.encrypt import Encryption

# Google returns this when the refresh token was revoked, expired (for
# example, OAuth consent screen left in "Testing" mode) or already used.
REAUTH_ERROR_CODES = {"invalid_grant"}


class GoogleTokenManager:
    def __init__(
        self,
        repository: AuthRepository,
        google_client: GoogleOAuthClient,
        encryption: Encryption,
    ) -> None:
        self.repository = repository
        self.google_client = google_client
        self.encryption = encryption

    async def get_valid_access_token(self, user_id: UUID) -> Optional[str]:
        tokens = await self.repository.get_google_tokens(user_id)
        if tokens is None:
            return None

        now = datetime.now(timezone.utc)
        if tokens.expires_at > now + timedelta(seconds=60):
            return self.encryption.text_decrypt(tokens.access_token_enc)

        if not tokens.refresh_token_enc:
            return None

        refresh_token = self.encryption.text_decrypt(tokens.refresh_token_enc)
        try:
            refreshed = await self.google_client.refresh_access_token(refresh_token)
        except GoogleOAuthError as exc:
            if exc.code in REAUTH_ERROR_CODES:
                # The stored token can never work again. Drop it so the next
                # request reports "not connected" and the user is asked to
                # reconnect instead of hitting Google on every call.
                await self.repository.delete_google_tokens(user_id)
                await self.repository.session.commit()
                raise GoogleReauthRequired(
                    "Google refresh token is expired or revoked; "
                    "the user must reconnect the Google account",
                    code=exc.code,
                    description=exc.description,
                ) from exc
            raise

        refreshed_refresh_token = (
            self.encryption.text_encrypt(refreshed.refresh_token)
            if refreshed.refresh_token
            else None
        )
        await self.repository.update_google_tokens(
            user_id,
            self.encryption.text_encrypt(refreshed.access_token),
            refreshed_refresh_token,
            now + timedelta(seconds=refreshed.expires_in),
            refreshed.scope or tokens.scope,
            refreshed.token_type or tokens.token_type,
        )
        await self.repository.session.commit()
        return refreshed.access_token
