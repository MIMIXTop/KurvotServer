import gzip
import logging
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response

from app.auth.google_client import GoogleOAuthClient, GoogleOAuthError
from app.auth.repository import AuthRepository
from app.auth.token_manager import GoogleTokenManager
from app.classroom.client import GoogleApiClient, GoogleApiProxyError, ProxyResponse
from app.config import settings
from app.database.database import SessionDep
from app.utils.encrypt import Encryption

google_api = APIRouter()

logger = logging.getLogger("google_api.proxy")

MAX_LOG_BODY = 2000


def _content_encoding(headers) -> str:
    for key, value in headers:
        if key.lower() == "content-encoding":
            return value.lower()
    return ""


def _decode_body(raw: bytes, headers) -> bytes:
    encoding = _content_encoding(headers)
    if not raw or not encoding:
        return raw
    try:
        if "gzip" in encoding:
            return gzip.decompress(raw)
        if "deflate" in encoding:
            return zlib.decompress(raw)
    except (OSError, zlib.error) as exc:
        return f"<undecodable {encoding} body: {exc}>".encode()
    return raw


def _truncate(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    if len(text) > MAX_LOG_BODY:
        return text[:MAX_LOG_BODY] + f"... <truncated, {len(text)} chars total>"
    return text


@dataclass(frozen=True)
class GoogleService:
    host: str
    prefix: str


CLASSROOM = GoogleService("https://classroom.googleapis.com", "/v1")
SHEETS = GoogleService("https://sheets.googleapis.com", "/v4/spreadsheets")
DRIVE = GoogleService("https://www.googleapis.com", "/drive/v3")
DRIVE_UPLOAD = GoogleService("https://www.googleapis.com", "/upload/drive/v3")
FORMS = GoogleService("https://forms.googleapis.com", "/v1/forms")


def _token_manager(session: SessionDep) -> GoogleTokenManager:
    key = settings.TOKEN_ENCRYPTION_KEY or settings.SECRET_KEY
    if not key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token encryption key is missing",
        )
    return GoogleTokenManager(
        AuthRepository(session),
        GoogleOAuthClient(
            settings.GOOGLE_CLIENT_ID,
            settings.GOOGLE_CLIENT_SECRET,
            settings.GOOGLE_REDIRECT_URI,
        ),
        Encryption(key),
    )


async def _resolve_user_id(request: Request, session: SessionDep):
    repository = AuthRepository(session)
    telegram_id = request.query_params.get("telegram_id")
    if telegram_id is not None:
        try:
            user = await repository.find_user_by_telegram_id(int(telegram_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid telegram_id") from exc
    else:
        cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)
        if not cookie:
            raise HTTPException(status_code=401, detail="Authentication required")
        key = settings.TOKEN_ENCRYPTION_KEY or settings.SECRET_KEY
        user = await repository.find_user_by_session_hash(
            Encryption(key).sha256_hex(cookie),
            datetime.now(timezone.utc),
        )
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user.id


def _build_target(
    service: GoogleService,
    path: str,
    request: Request,
    *,
    default_query: tuple[str, str] | None = None,
    extra_query: list[tuple[str, str]] | None = None,
) -> str:
    query = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key != "telegram_id"
    ]
    if default_query is not None and not query:
        query.append(default_query)
    if extra_query:
        query.extend(extra_query)
    encoded_path = quote(path.lstrip("/"), safe="/!:")
    target = f"{service.host}{service.prefix}/{encoded_path}"
    if query:
        target += f"?{urlencode(query)}"
    return target


def _response(proxy_response: ProxyResponse) -> Response:
    response = Response(
        content=proxy_response.body,
        status_code=proxy_response.status_code,
    )
    excluded = {"content-length", "connection", "transfer-encoding", "server"}
    for name, value in proxy_response.headers:
        if name.lower() not in excluded:
            response.headers.append(name, value)
    return response


async def _proxy(
    service: GoogleService,
    path: str,
    request: Request,
    session: SessionDep,
    *,
    default_query: tuple[str, str] | None = None,
    extra_query: list[tuple[str, str]] | None = None,
) -> Response:
    user_id = await _resolve_user_id(request, session)
    try:
        token = await _token_manager(session).get_valid_access_token(user_id)
    except (GoogleOAuthError, RuntimeError, LookupError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google token request failed",
        ) from exc
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account is not connected",
        )

    headers = [
        (key, value)
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length", "authorization", "accept-encoding"}
    ]
    headers.append(("Authorization", f"Bearer {token}"))
    target = _build_target(
        service,
        path,
        request,
        default_query=default_query,
        extra_query=extra_query,
    )
    body = await request.body()
    logger.info(
        "→ %s %s | body: %s",
        request.method,
        target,
        _truncate(body) if body else "<empty>",
    )
    try:
        result = await GoogleApiClient().request(
            request.method,
            target,
            body,
            headers,
        )
    except GoogleApiProxyError as exc:
        logger.error("✗ %s %s failed: %s", request.method, target, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    log = logger.warning if result.status_code >= 400 else logger.info
    log(
        "← %s | body: %s",
        result.status_code,
        _truncate(_decode_body(result.body, result.headers)) if result.body else "<empty>",
    )
    return _response(result)


async def classroom_proxy(path: str, request: Request, session: SessionDep):
    default_query = ("courseStates", "ACTIVE") if path == "courses" and request.method == "GET" else None
    return await _proxy(CLASSROOM, path, request, session, default_query=default_query)


async def sheet_proxy(path: str, request: Request, session: SessionDep):
    return await _proxy(SHEETS, path, request, session)


async def sheets_proxy(path: str, request: Request, session: SessionDep):
    return await _proxy(SHEETS, path, request, session)


async def drive_upload(request: Request, session: SessionDep):
    has_upload_type = any(key == "uploadType" for key, _ in request.query_params.multi_items())
    extra_query = [] if has_upload_type else [("uploadType", "multipart")]
    return await _proxy(
        DRIVE_UPLOAD,
        "files",
        request,
        session,
        extra_query=extra_query,
    )


async def drive_proxy(path: str, request: Request, session: SessionDep):
    return await _proxy(DRIVE, path, request, session)

async def forms_proxy(path: str, request: Request, session: SessionDep):
    return await _proxy(FORMS, path, request, session)


# The specific upload route MUST be registered before the generic
# "/api/drive/{path:path}" handler, otherwise Starlette matches "upload" as a
# drive path and forwards it to the wrong Google endpoint (drive/v3/upload
# instead of upload/drive/v3/files) without uploadType=multipart.
google_api.add_api_route(
    "/api/drive/upload",
    drive_upload,
    methods=["POST"],
    operation_id="drive_upload",
)

for _name, _path, _handler in (
    ("classroom", "/api/classroom/{path:path}", classroom_proxy),
    ("sheet", "/api/sheet/{path:path}", sheet_proxy),
    ("sheets", "/api/sheets/{path:path}", sheets_proxy),
    ("drive", "/api/drive/{path:path}", drive_proxy),
    ("forms", "/api/forms/{path:path}", forms_proxy)
):
    for _method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        google_api.add_api_route(
            _path,
            _handler,
            methods=[_method],
            operation_id=f"{_name}_{_method.lower()}",
        )
