from typing import Annotated

from fastapi import Depends

from app.config import get_db_url
from app.database.models import Base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DATABASE_URL = get_db_url()
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 10},
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_session():
    async with async_session() as session:
        yield session

SessionDep = Annotated[AsyncSession, Depends(get_session)]