from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, WebSocket, status

from app.auth.repository import AuthRepository
from app.config import settings
from app.database.database import SessionDep
from app.database.models import AuthUsers, UserRoles
from app.utils.encrypt import encryption


async def get_current_user(request: Request, session: SessionDep) -> AuthUsers:
    session_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    user = await AuthRepository(session).find_user_by_session_hash(
        encryption.sha256_hex(session_token),
        datetime.now(timezone.utc),
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )
    return user


async def require_admin(
    user: AuthUsers = Depends(get_current_user),
) -> AuthUsers:
    if user.user_role is not UserRoles.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required",
        )
    return user


async def require_admin_websocket(
    websocket: WebSocket,
    session: SessionDep,
) -> AuthUsers:
    session_token = websocket.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_token:
        await websocket.close(code=1008, reason="Authentication required")
        raise RuntimeError("Authentication required")

    user = await AuthRepository(session).find_user_by_session_hash(
        encryption.sha256_hex(session_token),
        datetime.now(timezone.utc),
    )
    if user is None or user.user_role is not UserRoles.ADMIN:
        await websocket.close(code=1008, reason="Administrator role required")
        raise RuntimeError("Administrator role required")
    return user
