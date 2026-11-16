import secrets
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.requests import Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.auth.dependencies import require_admin, require_admin_websocket
from app.auth.repository import AuthRepository
from app.database.database import SessionDep
from app.database.models import AuthUsers
from app.dashboard.agent_logs import agent_log_hub, parse_agent_log_line
from app.dashboard.docker_logs import DEFAULT_TAIL, DockerError, list_containers, stream_logs
from app.dashboard.schemas import AgentLogBatch, PublicUser, UpdateUserRole

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = (BASE_DIR / "static").resolve()

dashboard = APIRouter(prefix="/dashboard", tags=["dashboard"])

templates = Jinja2Templates(directory=BASE_DIR / "templates")


@dashboard.get("/static/{file_path:path}", name="dashboard_static")
async def dashboard_static(file_path: str):
    """Статика дашборда: /dashboard/static/css/dashboard.css и т.д."""
    target = (STATIC_DIR / file_path).resolve()
    if not target.is_relative_to(STATIC_DIR) or not target.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(target)


@dashboard.get("/", response_class=HTMLResponse)
async def home(request: Request, _: AuthUsers = Depends(require_admin)):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"request": request}
    )


@dashboard.get("/api/containers")
async def containers(_: AuthUsers = Depends(require_admin)):
    """Источники логов: агент с хоста + запущенные Docker-контейнеры."""
    items: list[dict[str, str]] = []
    warning: str | None = None

    if settings.AGENT_LOG_TOKEN:
        online = agent_log_hub.is_online()
        items.append(
            {
                "id": settings.AGENT_LOG_SERVICE,
                "name": settings.AGENT_LOG_SERVICE,
                "image": "agent process on host",
                "state": "running" if online else "offline",
                "status": (
                    "логи приходят с хоста"
                    if online
                    else "агент ещё не присылал логи"
                ),
            }
        )

    try:
        items.extend(await list_containers())
    except DockerError as exc:
        warning = str(exc)
    except FileNotFoundError as exc:
        warning = str(exc) or "docker CLI не найден"

    return {"containers": items, "warning": warning}


@dashboard.post("/api/logs/ingest", status_code=204)
async def ingest_agent_logs(
    request: Request,
    payload: AgentLogBatch,
):
    """Принимает логи Telegram-агента, работающего вне Docker."""
    expected = settings.AGENT_LOG_TOKEN
    if not expected:
        raise HTTPException(status_code=503, detail="Agent log ingestion is disabled")

    provided = request.headers.get("x-log-token", "")
    if not secrets.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid log token")

    service = (payload.service or settings.AGENT_LOG_SERVICE)[:64]
    # One request carries a small batch; ignore anything absurd.
    for line in payload.lines[:200]:
        if line.strip():
            agent_log_hub.publish(parse_agent_log_line(service, line))

    return Response(status_code=204)


@dashboard.get("/api/users", response_model=list[PublicUser])
async def users(session: SessionDep, _: AuthUsers = Depends(require_admin)):
    repository = AuthRepository(session)
    return [
        PublicUser(
            name=user.name,
            email=user.email,
            role=user.user_role,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
            telegram_linked=user.telegram_id is not None,
            status="active" if user.last_login_at else "pending",
        )
        for user in await repository.list_users()
    ]


@dashboard.patch("/api/users/{email}/role", response_model=PublicUser)
async def update_user_role(
    email: str,
    payload: UpdateUserRole,
    session: SessionDep,
    admin: AuthUsers = Depends(require_admin),
):
    if email == admin.email and payload.role.value != "admin":
        raise HTTPException(
            status_code=400,
            detail="An administrator cannot remove their own administrator role",
        )
    user = await AuthRepository(session).update_user_role_by_email(email, payload.role)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return PublicUser(
        name=user.name,
        email=user.email,
        role=user.user_role,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        telegram_linked=user.telegram_id is not None,
        status="active" if user.last_login_at else "pending",
    )


@dashboard.websocket("/ws/logs")
async def ws_logs(
    websocket: WebSocket,
    container: str | None = None,
    tail: int = DEFAULT_TAIL,
    _: AuthUsers = Depends(require_admin_websocket),
):
    """Отдаёт логи источника в реальном времени.

    Для ``telegram-agent`` используется внутренняя шина: агент работает на
    хосте и присылает записи через ``/api/logs/ingest``. Остальные имена —
    Docker-контейнеры.
    """
    await websocket.accept()
    target = (container or settings.LOGS_CONTAINER or "").strip()

    async def notify(level: str, message: str) -> None:
        await websocket.send_json(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": level,
                "name": "dashboard",
                "msg": message,
            }
        )

    try:
        if not target:
            await notify("ERROR", "Не выбран источник логов")
            return

        if target == settings.AGENT_LOG_SERVICE:
            queue = agent_log_hub.subscribe()
            try:
                # Сначала подписываемся, потом отдаём историю: строка,
                # пришедшая между снимком и подпиской, не потеряется.
                for entry in agent_log_hub.snapshot():
                    await websocket.send_json(entry)
                while True:
                    await websocket.send_json(await queue.get())
            finally:
                agent_log_hub.unsubscribe(queue)
            return

        async for entry in stream_logs(target, tail=tail):
            await websocket.send_json(entry)
    except DockerError as exc:
        await notify("ERROR", str(exc))
    except (WebSocketDisconnect, RuntimeError):
        # клиент отключился — просто выходим
        pass
    except Exception as exc:  # noqa: BLE001 - не роняем сервер из-за одного клиента
        try:
            await notify("ERROR", f"Ошибка чтения логов: {exc}")
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
