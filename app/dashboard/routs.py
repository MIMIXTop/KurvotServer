from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.requests import Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.auth.dependencies import require_admin, require_admin_websocket
from app.auth.repository import AuthRepository
from app.database.database import SessionDep
from app.database.models import AuthUsers
from app.dashboard.docker_logs import DEFAULT_TAIL, DockerError, list_containers, stream_logs
from app.dashboard.schemas import PublicUser, UpdateUserRole

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
    """Список запущенных контейнеров для выбора источника логов."""
    try:
        items = await list_containers()
    except DockerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="docker CLI не найден") from exc
    return {"containers": items}


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
    """Отдаёт stdout/stderr выбранного контейнера в реальном времени."""
    await websocket.accept()
    target = (container or settings.LOGS_CONTAINER or "").strip()

    async def notify(level: str, message: str) -> None:
        await websocket.send_json(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": level,
                "name": "docker",
                "msg": message,
            }
        )

    try:
        if not target:
            await notify("ERROR", "Не выбран контейнер для логов")
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
