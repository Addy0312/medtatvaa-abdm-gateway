# app/core/database.py
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from app.core.config import settings

# Async Engine - works with both sqlite+aiosqlite and postgresql+asyncpg
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=(settings.LOG_LEVEL == "DEBUG"),
    future=True
)

# Async Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession
)

# Declarative Base for models
Base = declarative_base()

# FastAPI Dependency to get DB session per request
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()