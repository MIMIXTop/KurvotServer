import logging
import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.auth.router import auth
from app.google_api.router import google_api
from app.dashboard.routs import dashboard
from app.database.database import engine
from app.database.models import Base


def _configure_logging() -> None:
    proxy_logger = logging.getLogger("google_api.proxy")
    if proxy_logger.handlers:
        return
    proxy_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    proxy_logger.addHandler(handler)
    proxy_logger.propagate = False


_configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(auth)
app.include_router(google_api)

app.include_router(dashboard)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)