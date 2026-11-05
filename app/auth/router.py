import html
import urllib.parse
from datetime import datetime, timezone

from fastapi.responses import RedirectResponse, JSONResponse, Response

from app.config import settings
from app.utils.encrypt import Encryption, encryption
from sqlalchemy import select, update
from fastapi import APIRouter, Request, HTTPException, status
from app.database.database import SessionDep
from app.database.models import *
from app.auth.google_client import GoogleOAuthClient, GoogleOAuthError
from app.auth.repository import AuthRepository
from app.auth.service import AuthService, OAuthStateError

auth = APIRouter()


SCOPES = [
    "https://www.googleapis.com/auth/forms.responses.readonly",
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms",
    "https://www.googleapis.com/auth/classroom.topics",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials",
    "https://www.googleapis.com/auth/classroom.courses",
    "https://www.googleapis.com/auth/classroom.announcements",
    "https://www.googleapis.com/auth/classroom.rosters",
    "https://www.googleapis.com/auth/classroom.profile.emails",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
    "openid",
    "email",
    "profile"
]

@auth.get("/api/auth/google/start")
async def start(request: Request, session: SessionDep ):
    if settings.GOOGLE_CLIENT_ID is None or settings.GOOGLE_REDIRECT_URI is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Google OAuth config is missing")

    random_token = encryption.random_url_safe_token(32)

    telegram_id = request.query_params.get("telegram_id")
    if telegram_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="In query params not found 'telegram_id'")
    try:
        telegram_id_value = int(telegram_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'telegram_id' must be an integer",
        ) from exc

    service = _create_auth_service(session)
    await service.create_google_state(
        telegram_id_value, random_token, datetime.now(timezone.utc)
    )

    scopes = " ".join(SCOPES)

    base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": scopes,
        "state": random_token,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
    }

    redirect_url = f"{base_url}?{urllib.parse.urlencode(params)}"
    response = RedirectResponse(redirect_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value= random_token,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="lax",
        max_age=300
    )
    return response


@auth.get("/api/auth/telegram-role")
async def get_telegram_role(telegram_id: int, session: SessionDep):
    user = await AuthRepository(session).find_user_by_telegram_id(telegram_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Telegram user is not linked",
        )
    return {"role": user.user_role.value}


@auth.get("/api/auth/google/callback")
async def auth_callback(request: Request, session: SessionDep ):
    params = request.query_params
    google_error = params.get("error")
    if google_error is not None:
        return Response(content=google_error, status_code=status.HTTP_401_UNAUTHORIZED)

    code = params.get("code")
    state = params.get("state")
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google callback requires code and state",
        )

    now = datetime.now(timezone.utc)
    service = _create_auth_service(session)
    try:
        result = await service.authenticate_google(
            code, state, request.headers.get("user-agent"), now
        )
    except OAuthStateError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except GoogleOAuthError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    bot_username = "KiraACR_bot"
    html_body = f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Авторизация успешна</title>
<style>
body {{ font-family: sans-serif; display: flex; align-items: center; justify-content: center;
height: 100vh; background: #f4f6f9; margin: 0; }}
.card {{ background: white; padding: 40px; border-radius: 16px; text-align: center;
box-shadow: 0 4px 20px rgba(0,0,0,.08); }}
.btn {{ background: #2481cc; color: white; text-decoration: none; padding: 12px 24px;
border-radius: 8px; font-weight: bold; display: inline-block; }}
</style></head>
<body><div class="card"><h1>Подключено!</h1>
<p>Google Classroom (<b>{html.escape(result.email)}</b>) успешно привязан.</p>
<a href="tg://resolve?domain={bot_username}" class="btn">Вернуться в Telegram</a>
</div><script>
setTimeout(() => {{ window.location.href = "tg://resolve?domain={bot_username}"; }}, 1500);
</script></body></html>"""
    response = Response(content=html_body, media_type="text/html")
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=result.session_token,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="lax",
        max_age=30 * 24 * 60 * 60,
    )
    return response


def _create_auth_service(session: SessionDep) -> AuthService:
    token_key = settings.TOKEN_ENCRYPTION_KEY or settings.SECRET_KEY
    if not token_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token encryption key is missing",
        )
    return AuthService(
        AuthRepository(session),
        GoogleOAuthClient(
            settings.GOOGLE_CLIENT_ID,
            settings.GOOGLE_CLIENT_SECRET,
            settings.GOOGLE_REDIRECT_URI,
        ),
        Encryption(token_key),
    )

@auth.get("/api/auth/me")
async def get_me(request: Request, session: SessionDep ):
    cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if cookie is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials 'not found cookie'")

    session_hash = encryption.sha256_hex(cookie)
    session_opt = await session.execute(
        select(AppSessions).where(
            AppSessions.session_hash == session_hash
            and AppSessions.revoked_at == None
            and AppSessions.expires_at > time.get_current_time()
        )
    )

    if session_opt.scalar():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    app_session = session_opt.scalar()
    update_app_session = await session.execute(
        update(AppSessions)
        .values(
            last_seen_at=time.get_current_time(),
        )
        .where(
            AppSessions.session_hash == session_hash
        )
    )
    if update_app_session.scalar() is None:
        raise HTTPException( status_code= status.HTTP_500_INTERNAL_SERVER_ERROR,detail="Failed to update app session last_seen_at")

    res_user = await session.execute(
        select(AuthUsers)
        .where(
           AuthUsers.id ==  app_session.user_id
        )
    )
    user = res_user.scalar()

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    json = {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "googleSub": user.google_sub,
        "picture": user.picture_url
    }

    return JSONResponse(status_code=status.HTTP_200_OK, content=json)

@auth.post("/api/auth/logout")
async def logout(request: Request, session: SessionDep ):
    cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if cookie is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Could not validate credentials 'not found cookie'")

    session_hash = encryption.sha256_hex(cookie)
    now = time.get_current_time()

    await session.execute(
        update(AppSessions)
        .values(
            revoked_at=now,
        )
        .where(
            session_hash == session_hash
        )
    )

    response = Response(status_code=status.HTTP_200_OK)
    response.set_cookie(
        httponly=True,
        key=settings.SESSION_COOKIE_NAME,
        max_age=0,
        samesite="none",
        secure=settings.SESSION_COOKIE_SECURE,
        path="/",
    )
    return response
