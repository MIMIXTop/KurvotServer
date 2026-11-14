import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.auth.schemas import GoogleTokenResponse, GoogleUserInfo


class GoogleOAuthError(RuntimeError):
    def __init__(
        self,
        message: str,
        code: str | None = None,
        description: str | None = None,
    ) -> None:
        self.code = code
        self.description = description
        super().__init__(message)


class GoogleReauthRequired(GoogleOAuthError):
    """The stored refresh token is expired, revoked or otherwise unusable."""


@dataclass(frozen=True)
class GoogleOAuthClient:
    client_id: str
    client_secret: str
    redirect_uri: str

    async def exchange_code_for_tokens(self, code: str) -> GoogleTokenResponse:
        data = await self._request(
            "https://oauth2.googleapis.com/token",
            {
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        try:
            return GoogleTokenResponse(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                expires_in=int(data.get("expires_in", 3600)),
                scope=data.get("scope"),
                token_type=data.get("token_type"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GoogleOAuthError("Google token response is invalid") from exc

    async def fetch_user_info(self, access_token: str) -> GoogleUserInfo:
        data = await self._request(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            {"access_token": access_token},
            method="GET",
        )
        try:
            return GoogleUserInfo(
                sub=data["sub"],
                email=data["email"],
                name=data.get("name"),
                picture=data.get("picture"),
            )
        except (KeyError, TypeError) as exc:
            raise GoogleOAuthError("Google user info response is invalid") from exc

    async def refresh_access_token(self, refresh_token: str) -> GoogleTokenResponse:
        data = await self._request(
            "https://oauth2.googleapis.com/token",
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        try:
            return GoogleTokenResponse(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                expires_in=int(data.get("expires_in", 3600)),
                scope=data.get("scope"),
                token_type=data.get("token_type"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GoogleOAuthError("Google refresh response is invalid") from exc

    async def _request(
        self,
        url: str,
        params: dict[str, str],
        method: str = "POST",
    ) -> dict[str, Any]:
        def request() -> dict[str, Any]:
            encoded = urllib.parse.urlencode(params).encode()
            if method == "GET":
                target = f"{url}?{encoded.decode()}"
                http_request = urllib.request.Request(target, method="GET")
            else:
                http_request = urllib.request.Request(
                    url,
                    data=encoded,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method=method,
                )
            try:
                with urllib.request.urlopen(http_request, timeout=15) as response:
                    result = json.loads(response.read())
            except urllib.error.HTTPError as exc:
                # The OAuth error body carries the real reason
                # (invalid_grant, invalid_client, redirect_uri_mismatch...).
                # urllib hides it behind a generic HTTPError, so read it here.
                body = exc.read().decode("utf-8", errors="replace")
                code = description = None
                try:
                    payload = json.loads(body)
                except (TypeError, ValueError):
                    payload = None
                if isinstance(payload, dict):
                    raw_code = payload.get("error")
                    raw_description = payload.get("error_description")
                    if isinstance(raw_code, str):
                        code = raw_code
                    if isinstance(raw_description, str):
                        description = raw_description
                reason = description or code or f"HTTP {exc.code}"
                raise GoogleOAuthError(
                    f"Google OAuth request failed: {reason}",
                    code=code,
                    description=description,
                ) from exc
            except (OSError, ValueError) as exc:
                raise GoogleOAuthError("Google OAuth request failed") from exc
            if not isinstance(result, dict):
                raise GoogleOAuthError("Google OAuth response is invalid")
            return result

        return await asyncio.to_thread(request)
