from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import AsyncIterator

from sqlalchemy import Column, Date, DateTime, Integer, String, insert, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from open_workshop_manager import settings as config

async_engine: AsyncEngine = create_async_engine(
    config.mysql_url("access"),
    pool_pre_ping=True,
)
engine = async_engine
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)
Base = declarative_base()


class StatisticsHour(Base):
    __tablename__ = "statistics_hour"
    id = Column(Integer, primary_key=True)
    date_time = Column(DateTime)

    # user, mod, etc...
    type = Column(String(32))
    type_id = Column(Integer, default=None)

    # views, downloads, etc
    name = Column(String(64))

    count = Column(Integer, default=0)


class StatisticsDay(Base):
    __tablename__ = "statistics_day"
    id = Column(Integer, primary_key=True)
    date = Column(Date)

    # user, mod, etc...
    type = Column(String(32))
    type_id = Column(Integer, default=None)

    # views, downloads, etc
    name = Column(String(64))

    count = Column(Integer, default=0)


class ProcessingTime(Base):
    __tablename__ = "processing_time"
    time = Column(DateTime, primary_key=True)

    # user, mod, etc...
    type = Column(String(32))
    type_id = Column(Integer, default=None)

    # views, downloads, etc
    name = Column(String(64))

    delay = Column(Integer)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def _increment_stat(
    session: AsyncSession,
    model,
    time_field,
    time_value: datetime | date,
    entity_type: str,
    entity_id: int | None,
    name: str,
) -> None:
    result = await session.execute(
        update(model)
        .where(
            time_field == time_value,
            model.type == str(entity_type),
            model.type_id == entity_id,
            model.name == name,
        )
        .values(count=model.count + 1)
    )

    if result.rowcount == 0:
        await session.execute(
            insert(model).values(
                **{
                    time_field.name: time_value,
                    "type": entity_type,
                    "type_id": entity_id,
                    "name": name,
                    "count": 1,
                }
            )
        )


async def create_processing(type: str, type_id: int, name: str, time_start: datetime) -> None:
    """Backward-compatible wrapper for recording processing time."""
    await record_processing_time(
        entity_type=type, entity_id=type_id, name=name, time_start=time_start
    )


async def record_processing_time(
    entity_type: str, entity_id: int, name: str, time_start: datetime
) -> None:
    milliseconds = int((datetime.now() - time_start).total_seconds() * 1000)

    async with session_scope() as session:
        await session.execute(
            insert(ProcessingTime).values(
                time=time_start,
                type=entity_type,
                type_id=entity_id,
                name=name,
                delay=milliseconds,
            )
        )


async def update(type: str, type_id: int, name: str) -> None:
    now = datetime.now()
    async with session_scope() as session:
        await _update_hour(
            session=session, entity_type=type, entity_id=type_id, name=name, now=now
        )
        await _update_day(
            session=session,
            entity_type=type,
            entity_id=type_id,
            name=name,
            today=now.date(),
        )


async def update_hour(session: AsyncSession, type: str, type_id: int, name: str) -> None:
    await _update_hour(
        session=session,
        entity_type=type,
        entity_id=type_id,
        name=name,
        now=datetime.now(),
    )


async def update_day(session: AsyncSession, type: str, type_id: int, name: str) -> None:
    await _update_day(
        session=session,
        entity_type=type,
        entity_id=type_id,
        name=name,
        today=date.today(),
    )


async def _update_hour(
    session: AsyncSession, entity_type: str, entity_id: int, name: str, now: datetime
) -> None:
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    entity_id_value = int(entity_id) if entity_id is not None else None
    await _increment_stat(
        session=session,
        model=StatisticsHour,
        time_field=StatisticsHour.date_time,
        time_value=current_hour,
        entity_type=entity_type,
        entity_id=entity_id_value,
        name=name,
    )


async def _update_day(
    session: AsyncSession, entity_type: str, entity_id: int, name: str, today: date
) -> None:
    entity_id_value = int(entity_id) if entity_id is not None else None
    await _increment_stat(
        session=session,
        model=StatisticsDay,
        time_field=StatisticsDay.date,
        time_value=today,
        entity_type=entity_type,
        entity_id=entity_id_value,
        name=name,
    )


async def init_models() -> None:
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
