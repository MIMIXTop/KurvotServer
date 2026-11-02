from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.requests import Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.dashboard.docker_logs import DEFAULT_TAIL, DockerError, list_containers, stream_logs

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
async def home(request: Request):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "cluster_name": "prod-eu-west-01",
            "current_user": {"username": "root_admin", "role": "Cluster Administrator", "permissions": ["admin"]},
            "available_services": ["api.gateway", "auth.service", "telegram.agent"],
            "users": [
                {"id": 1, "username": "alex_dev", "email": "alex@org.io", "role": "Bot Dev",
                 "allowed_services": ["telegram.agent"]},
                {"id": 2, "username": "sec_ops", "email": "sec@org.io", "role": "Sec Auditor",
                 "allowed_services": ["auth.service", "api.gateway"]},
            ],
            "roles": [
                {
                    "title": "Telegram Bot Developer",
                    "slug": "tg-dev",
                    "description": "Отладка агента и интеграций бота",
                    "permissions": [
                        {"label": "Чтение telegram.agent", "granted": True},
                        {"label": "Чтение auth.service", "granted": False}
                    ]
                }
            ]
        }
    )


@dashboard.get("/api/containers")
async def containers():
    """Список запущенных контейнеров для выбора источника логов."""
    try:
        items = await list_containers()
    except DockerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="docker CLI не найден") from exc
    return {"containers": items}


@dashboard.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket, container: str | None = None, tail: int = DEFAULT_TAIL):
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
